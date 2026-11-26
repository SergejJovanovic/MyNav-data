# MyNav offline data

Offline routing and address search packages for the [MyNav](https://github.com/SergejJovanovic/MyNav) iOS app, built from OpenStreetMap data once a month by GitHub Actions and published as [releases](../../releases).

The app reads the newest manifest from
`https://github.com/SergejJovanovic/MyNav-data/releases/latest/download/manifest.json`.

## Packages per country

| File | Contents | Serbia (approx.) |
|---|---|---|
| `routing-<ID>.tar.zst` | [Valhalla](https://github.com/valhalla/valhalla) tile extract for [valhalla-mobile](https://github.com/Rallista/valhalla-mobile). Names are in Serbian Latin script, so turn instructions read "Bulevar oslobođenja", not "Булевар ослобођења". | 82 MB download, 225 MB installed |
| `addresses-<ID>.sqlite.zst` | SQLite address search database (see below): 2.5 million addresses, 120,000 streets | 39 MB download, 111 MB installed |

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

## Building locally

Needs Docker, Python 3.10+ and zstd.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHON=.venv/bin/python tools/build_country.sh RS europe/serbia Serbia out/
.venv/bin/python tools/build_manifest.py out data-local SergejJovanovic/MyNav-data
.venv/bin/python -m unittest discover -s tests
```

`PBF=/path/to/serbia-latest.osm.pbf` uses an extract already on disk. Countries are listed in `countries.json` with their [Geofabrik](https://download.geofabrik.de) path; add a line to add a country.

## Licence

The data packages are derived from OpenStreetMap and are available under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/): © OpenStreetMap contributors. Any app showing them must credit OpenStreetMap.
