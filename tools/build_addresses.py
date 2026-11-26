"""Builds the offline address search database of one country from an OSM extract.

Layout (SQLite, coordinates as integer micro-degrees):
  street(id, name, name_original, city, lat, lon)   one row per street per town, Latin display name
  street_fts(name, city)                             FTS5 over the normalised name and town (rowid = street.id)
  address(street_id, housenumber, lat, lon)          every mapped house number, indexed by street
  meta(key, value)                                   country, OSM data timestamp, schema version

The app finds streets with street_fts, then the house number among that street's addresses.
Few Serbian addresses carry `addr:city`, so each street gets the town it lies in: `addr:city` where mapped,
otherwise the nearest place node (cities count from further away than villages).

Usage: build_addresses.py input.osm.pbf output.sqlite COUNTRY_ID
"""
import math
import sqlite3
import sys
import time
from collections import Counter, defaultdict

import osmium

from serbian import display_name, normalize, to_latin

SCHEMA_VERSION = 1
ROADS = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "pedestrian", "service", "road", "motorway_link", "trunk_link",
    "primary_link", "secondary_link", "tertiary_link",
}
# How far a place reaches, and how strongly it attracts streets compared with smaller places nearby.
PLACE_REACH_METERS = {"city": 15_000, "town": 7_000, "suburb": 2_500, "village": 3_000, "hamlet": 1_200}
PLACE_WEIGHT = {"city": 4.0, "town": 2.5, "suburb": 1.5, "village": 1.0, "hamlet": 0.6}
# Addresses of one street name further apart than a cluster cell are different streets (different towns).
CLUSTER_DEGREES = 0.03
PLACE_GRID_DEGREES = 0.1


def meters(lat1, lon1, lat2, lon2):
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6_371_000 * math.hypot(x, y)


class Collector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.addresses = []          # (street name, housenumber, addr:city, lat, lon)
        self.roads = []              # (name, name:sr-Latn, lat, lon)
        self.places = []             # (Latin name, kind, lat, lon)
        self.place_aliases = {}      # normalised name in any language → Latin name ("belgrade" → "Beograd")

    def _address(self, tags, lat, lon):
        number = tags.get("addr:housenumber")
        street = tags.get("addr:street") or tags.get("addr:place")
        if number and street:
            self.addresses.append((street, number, tags.get("addr:city") or "", lat, lon))

    def node(self, n):
        if not n.location.valid():
            return
        tags = n.tags
        if "addr:housenumber" in tags:
            self._address(tags, n.location.lat, n.location.lon)
        kind = tags.get("place")
        if kind in PLACE_REACH_METERS and "name" in tags:
            name = display_name(tags)
            self.places.append((name, kind, n.location.lat, n.location.lon))
            # Bigger places win an alias they share with a village ("Beograd" the city over a hamlet of that name).
            rank = PLACE_WEIGHT[kind]
            for key in ("name", "name:sr-Latn", "name:en", "int_name", "alt_name", "old_name"):
                for alias in (tags.get(key) or "").split(";"):
                    alias_key = normalize(alias)
                    if alias_key and rank >= self.place_aliases.get(alias_key, ("", 0))[1]:
                        self.place_aliases[alias_key] = (name, rank)

    def way(self, w):
        locations = [node.location for node in w.nodes if node.location.valid()]
        if not locations:
            return
        tags = w.tags
        if "addr:housenumber" in tags:
            lat = sum(l.lat for l in locations) / len(locations)
            lon = sum(l.lon for l in locations) / len(locations)
            self._address(tags, lat, lon)
        if tags.get("highway") in ROADS and "name" in tags:
            middle = locations[len(locations) // 2]
            self.roads.append((tags.get("name"), tags.get("name:sr-Latn"), middle.lat, middle.lon))


class PlaceIndex:
    def __init__(self, places):
        self.grid = defaultdict(list)
        for place in places:
            self.grid[self._cell(place[2], place[3])].append(place)

    @staticmethod
    def _cell(lat, lon):
        return int(math.floor(lat / PLACE_GRID_DEGREES)), int(math.floor(lon / PLACE_GRID_DEGREES))

    def town(self, lat, lon):
        row, column = self._cell(lat, lon)
        best, best_score = None, math.inf
        for dr in (-2, -1, 0, 1, 2):
            for dc in (-2, -1, 0, 1, 2):
                for name, kind, plat, plon in self.grid.get((row + dr, column + dc), ()):
                    distance = meters(lat, lon, plat, plon)
                    if distance > PLACE_REACH_METERS[kind]:
                        continue
                    score = distance / PLACE_WEIGHT[kind]
                    if score < best_score:
                        best, best_score = name, score
        return best or ""


def cluster_key(name, lat, lon):
    return normalize(name), round(lat / CLUSTER_DEGREES), round(lon / CLUSTER_DEGREES)


def build(collector, country, osm_timestamp):
    places = PlaceIndex(collector.places)
    # Streets: one per normalised name per cluster cell, from roads and from addresses' street names.
    streets = {}

    def street_for(name, latin, lat, lon):
        key = cluster_key(name, lat, lon)
        street = streets.get(key)
        if street is None:
            street = streets[key] = {"name": latin or to_latin(name), "original": name, "lat": [], "lon": [], "cities": Counter()}
        street["lat"].append(lat)
        street["lon"].append(lon)
        return key

    for name, latin, lat, lon in collector.roads:
        street_for(name, latin, lat, lon)
    address_rows = []
    aliases = getattr(collector, "place_aliases", {})
    for street, number, city, lat, lon in collector.addresses:
        key = street_for(street, None, lat, lon)
        # `addr:city` counts only when it names a known place, in whatever language it was typed ("Belgrade").
        town = aliases.get(normalize(city)) if city else None
        if town:
            streets[key]["cities"][town[0]] += 1
        address_rows.append((key, number, lat, lon))

    street_ids = {}
    street_rows = []
    for index, (key, street) in enumerate(streets.items(), start=1):
        lat = sum(street["lat"]) / len(street["lat"])
        lon = sum(street["lon"]) / len(street["lon"])
        city = street["cities"].most_common(1)[0][0] if street["cities"] else places.town(lat, lon)
        street_ids[key] = index
        street_rows.append((index, street["name"], street["original"], city, round(lat * 1e6), round(lon * 1e6)))
    return street_rows, [(street_ids[key], number, round(lat * 1e6), round(lon * 1e6)) for key, number, lat, lon in address_rows]


def write(path, street_rows, address_rows, country, osm_timestamp):
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        DROP TABLE IF EXISTS street; DROP TABLE IF EXISTS street_fts; DROP TABLE IF EXISTS address; DROP TABLE IF EXISTS meta;
        CREATE TABLE street(id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_original TEXT NOT NULL, city TEXT NOT NULL, lat INTEGER NOT NULL, lon INTEGER NOT NULL);
        CREATE VIRTUAL TABLE street_fts USING fts5(name, city, content='', tokenize='unicode61', prefix='2 3');
        CREATE TABLE address(street_id INTEGER NOT NULL, housenumber TEXT NOT NULL, lat INTEGER NOT NULL, lon INTEGER NOT NULL);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    db.executemany("INSERT INTO street VALUES (?,?,?,?,?,?)", street_rows)
    db.executemany("INSERT INTO street_fts(rowid, name, city) VALUES (?,?,?)",
                   ((row[0], normalize(row[1]), normalize(row[3])) for row in street_rows))
    db.executemany("INSERT INTO address VALUES (?,?,?,?)", sorted(address_rows))
    db.execute("CREATE INDEX address_street ON address(street_id, housenumber)")
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("schema", str(SCHEMA_VERSION)), ("country", country), ("osm_timestamp", osm_timestamp),
        ("streets", str(len(street_rows))), ("addresses", str(len(address_rows))),
    ])
    db.commit()
    db.execute("INSERT INTO street_fts(street_fts) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()


def main(source, target, country):
    start = time.time()
    header = osmium.io.Reader(source, osmium.osm.osm_entity_bits.NOTHING).header()
    osm_timestamp = header.get("osmosis_replication_timestamp", "")
    collector = Collector()
    collector.apply_file(source, locations=True, idx="flex_mem")
    street_rows, address_rows = build(collector, country, osm_timestamp)
    write(target, street_rows, address_rows, country, osm_timestamp)
    with_city = sum(1 for row in street_rows if row[3])
    print(f"{country}: {len(address_rows)} addresses, {len(street_rows)} streets ({with_city} with a town), "
          f"{len(collector.places)} places, {time.time() - start:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
