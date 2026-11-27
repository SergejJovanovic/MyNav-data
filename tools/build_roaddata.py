"""Builds the offline road data of one country: what MyNav otherwise asks Overpass for.

Contents (SQLite, coordinates as integer micro-degrees):
  feature(id, lat, lon, tags)            traffic lights, crossings, stop signs, cameras, level crossings, toll booths
  feature_box                            R*Tree over features
  way(id, tags, nodes, coords)           roads features stand on and that form crossroads, with the tags the app reads
  way_box                                R*Tree over ways
  meta(key, value)                       schema, country, osm_timestamp, bounds

`tags` is a JSON object. `nodes` and `coords` are blobs of zigzag varints: node IDs as deltas, and
latitude/longitude micro-degrees as deltas (lat, lon, lat, lon…), starting from zero.

Usage: build_roaddata.py input.osm.pbf output.sqlite COUNTRY_ID
"""
import json
import sqlite3
import sys
import time

import osmium

SCHEMA_VERSION = 1
# Same as OverpassQueryBuilder.featureRoadPattern in the app (roads a feature can stand on).
ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "living_street", "service", "road", "busway"}
# Same as OSMRoadFeatureTagging.filter(for:) in the app.
FEATURES = {("highway", "traffic_signals"), ("highway", "crossing"), ("highway", "stop"),
            ("highway", "speed_camera"), ("railway", "level_crossing"), ("barrier", "toll_booth")}
WAY_KEYS = {"highway", "oneway", "junction", "name", "ref"}


def is_road(highway):
    return highway is not None and (highway[:-5] if highway.endswith("_link") else highway) in ROADS


def kept_way_tags(tags):
    return {t.k: t.v for t in tags if t.k in WAY_KEYS or "lanes" in t.k or "maxspeed" in t.k}


def zigzag_varints(values):
    out = bytearray()
    previous = 0
    for value in values:
        delta = value - previous
        previous = value
        number = (delta << 1) ^ (delta >> 63)
        while True:
            byte = number & 0x7F
            number >>= 7
            if number:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                break
    return bytes(out)


def zigzag_coordinates(points):
    out = bytearray()
    previous_lat = previous_lon = 0
    for lat, lon in points:
        for delta in (lat - previous_lat, lon - previous_lon):
            number = (delta << 1) ^ (delta >> 63)
            while True:
                byte = number & 0x7F
                number >>= 7
                if number:
                    out.append(byte | 0x80)
                else:
                    out.append(byte)
                    break
        previous_lat, previous_lon = lat, lon
    return bytes(out)


class Collector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.features = []
        self.ways = []

    def node(self, n):
        if not n.location.valid():
            return
        tags = n.tags
        if any(tags.get(key) == value for key, value in FEATURES):
            self.features.append((n.id, round(n.location.lat * 1e6), round(n.location.lon * 1e6),
                                  json.dumps({t.k: t.v for t in tags}, ensure_ascii=False, separators=(",", ":"))))

    def way(self, w):
        if not is_road(w.tags.get("highway")):
            return
        nodes, points = [], []
        for node in w.nodes:
            if not node.location.valid():
                return
            nodes.append(node.ref)
            points.append((round(node.location.lat * 1e6), round(node.location.lon * 1e6)))
        if len(nodes) < 2:
            return
        self.ways.append((w.id, json.dumps(kept_way_tags(w.tags), ensure_ascii=False, separators=(",", ":")), nodes, points))


def write(path, collector, country, osm_timestamp):
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA page_size = 4096;
        CREATE TABLE feature(id INTEGER PRIMARY KEY, lat INTEGER NOT NULL, lon INTEGER NOT NULL, tags TEXT NOT NULL);
        CREATE VIRTUAL TABLE feature_box USING rtree_i32(id, min_lat, max_lat, min_lon, max_lon);
        CREATE TABLE way(id INTEGER PRIMARY KEY, tags TEXT NOT NULL, nodes BLOB NOT NULL, coords BLOB NOT NULL);
        CREATE VIRTUAL TABLE way_box USING rtree_i32(id, min_lat, max_lat, min_lon, max_lon);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    db.executemany("INSERT INTO feature VALUES (?,?,?,?)", collector.features)
    db.executemany("INSERT INTO feature_box VALUES (?,?,?,?,?)", ((f[0], f[1], f[1], f[2], f[2]) for f in collector.features))
    south = west = 10 ** 9
    north = east = -(10 ** 9)
    way_rows, box_rows = [], []
    for way_id, tags, nodes, points in collector.ways:
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        south, north = min(south, min(lats)), max(north, max(lats))
        west, east = min(west, min(lons)), max(east, max(lons))
        way_rows.append((way_id, tags, zigzag_varints(nodes), zigzag_coordinates(points)))
        box_rows.append((way_id, min(lats), max(lats), min(lons), max(lons)))
    db.executemany("INSERT INTO way VALUES (?,?,?,?)", way_rows)
    db.executemany("INSERT INTO way_box VALUES (?,?,?,?,?)", box_rows)
    db.executemany("INSERT INTO meta VALUES (?,?)", [
        ("schema", str(SCHEMA_VERSION)), ("country", country), ("osm_timestamp", osm_timestamp),
        ("bounds", f"{south},{west},{north},{east}"),
        ("features", str(len(collector.features))), ("ways", str(len(way_rows))),
    ])
    db.commit()
    db.execute("VACUUM")
    db.close()


def main(source, target, country):
    start = time.time()
    header = osmium.io.Reader(source, osmium.osm.osm_entity_bits.NOTHING).header()
    collector = Collector()
    collector.apply_file(source, locations=True, idx="flex_mem")
    write(target, collector, country, header.get("osmosis_replication_timestamp", ""))
    print(f"{country}: {len(collector.features)} features, {len(collector.ways)} roads, {time.time() - start:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
