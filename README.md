# MyNav offline data

Offline routing and address search packages for the [MyNav](https://github.com/SergejJovanovic/MyNav) iOS app, built from OpenStreetMap data once a month by GitHub Actions and published as [releases](../../releases).

The app reads the newest manifest from
`https://github.com/SergejJovanovic/MyNav-data/releases/latest/download/manifest.json`.

## Packages per country

| File | Contents | Serbia (approx.) |
|---|---|---|
| `routing-<ID>.tar.xz` | [Valhalla](https://github.com/valhalla/valhalla) tile extract for [valhalla-mobile](https://github.com/Rallista/valhalla-mobile). Names are in Serbian Latin script, so turn instructions read "Bulevar oslobođenja", not "Булевар ослобођења". | 68 MB download, 225 MB installed |
| `addresses-<ID>.sqlite.xz` | SQLite address search database (see below): 2.5 million addresses, 120,000 streets | 26 MB download, 111 MB installed |
| `roaddata-<ID>.sqlite.xz` | Road data the app otherwise asks Overpass for (see below): 4,158 traffic lights, 39,867 crossings, stop signs, cameras, level crossings, toll booths and 400,000 roads with lane and speed-limit tags | 37.5 MB download, 98 MB installed |

Packages are xz-compressed, which Apple's Compression framework (LZMA) unpacks on the phone.

`manifest.json` lists every file with its download URL, size, installed size and SHA-256, the OSM data timestamp and the Valhalla version the tiles were built with (they must match the engine in the app).

### Address database (schema 1)

Coordinates are integer micro-degrees.

```sql
street(id, name, name_original, city, lat, lon) -- one row per street per town, Latin display name
street_fts(name, city)                          -- FTS5 over normalised name and town, rowid = street.id
address(street_id, housenumber, lat, lon)       -- indexed by (street_id, housenumber)
meta(key, value)                                -- schema, country, osm_timestamp, counts
```

Search text is normalised the same way in the app and in `tools/serbian.py`: Cyrillic transliterated to Latin, lower case, diacritics removed (`đ` → `dj`), punctuation as spaces. "zmaj jovina 5 novi sad" thus matches "Змај Јовина 5". Few addresses carry `addr:city`, so each street gets the town it lies in: `addr:city` where mapped, otherwise the nearest place (cities reach further than villages).

### Road data (schema 1)

```sql
feature(id, lat, lon, tags)      -- OSM nodes: traffic_signals, crossing, stop, speed_camera, level_crossing, toll_booth; tags as JSON
feature_box                      -- R*Tree (rtree_i32) over features
way(id, tags, nodes, coords)     -- roads (motorway…service, busway); highway, oneway, junction, name, ref, *lanes*, *maxspeed* tags as JSON
way_box                          -- R*Tree (rtree_i32) over ways
meta(key, value)                 -- schema, country, osm_timestamp, bounds (south,west,north,east in micro-degrees), counts
```

`nodes` holds the way's node IDs and `coords` its points (latitude, longitude in micro-degrees, alternating), each as zigzag varints of the difference to the previous value, starting from zero. The app answers its road-data requests from this file the way Overpass would, so traffic lights, crossings, crossroads, lane guidance, speed limits and the wrong-way warning work without a server.

## Building locally

Needs Docker, Python 3.10+ and xz.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHON=.venv/bin/python tools/build_country.sh RS europe/serbia Serbia out/
.venv/bin/python tools/build_manifest.py out data-local SergejJovanovic/MyNav-data
.venv/bin/python -m unittest discover -s tests
```

`PBF=/path/to/serbia-latest.osm.pbf` uses an extract already on disk. Countries are listed in `countries.json` with their [Geofabrik](https://download.geofabrik.de) path; add a line to add a country.

## Licence

The data packages are derived from OpenStreetMap and are available under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/): © OpenStreetMap contributors. Any app showing them must credit OpenStreetMap.
