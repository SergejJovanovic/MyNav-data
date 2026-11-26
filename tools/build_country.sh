#!/usr/bin/env bash
# Builds the offline packages of one country: Valhalla routing tiles and the address search database.
#
#   tools/build_country.sh RS europe/serbia Serbia out/
#
# Needs Docker, Python 3 with `osmium` (pip install -r requirements.txt) and zstd.
# Set PBF=/path/to/extract.osm.pbf to use an extract already on disk instead of downloading it.
set -euo pipefail

ID="$1"; GEOFABRIK="$2"; NAME="$3"; OUT="$(mkdir -p "$4" && cd "$4" && pwd)"
VALHALLA_IMAGE="${VALHALLA_IMAGE:-ghcr.io/valhalla/valhalla:3.9.2}"
PYTHON="${PYTHON:-python3}"
TOOLS="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT/$ID"

if [[ -z "${PBF:-}" ]]; then
  PBF="$WORK/source.osm.pbf"
  echo "== Downloading $GEOFABRIK"
  curl -sSfL -o "$PBF" "https://download.geofabrik.de/$GEOFABRIK-latest.osm.pbf"
  curl -sSfL -o "$PBF.md5" "https://download.geofabrik.de/$GEOFABRIK-latest.osm.pbf.md5"
  expected="$(cut -d' ' -f1 "$PBF.md5")"
  actual="$( (md5sum "$PBF" 2>/dev/null || md5 -r "$PBF") | cut -d' ' -f1)"
  [[ "$expected" == "$actual" ]] || { echo "Checksum mismatch for $GEOFABRIK" >&2; exit 1; }
fi

echo "== Latin names for routing"
"$PYTHON" "$TOOLS/latinize_names.py" "$PBF" "$WORK/latin.osm.pbf"

echo "== Valhalla tiles ($VALHALLA_IMAGE)"
mkdir -p "$WORK/valhalla"
docker run --rm -v "$WORK/valhalla:/data" -v "$WORK/latin.osm.pbf:/osm/source.osm.pbf:ro" "$VALHALLA_IMAGE" bash -c '
  set -e
  valhalla_build_config --mjolnir-tile-dir /data/tiles --mjolnir-tile-extract /data/tiles.tar --mjolnir-admin /data/admins.sqlite > /data/valhalla.json
  valhalla_build_admins -c /data/valhalla.json /osm/source.osm.pbf > /dev/null
  valhalla_build_tiles -c /data/valhalla.json /osm/source.osm.pbf > /dev/null
  valhalla_build_extract -c /data/valhalla.json > /dev/null
  chmod -R a+rw /data'
routing_installed=$(stat -c %s "$WORK/valhalla/tiles.tar" 2>/dev/null || stat -f %z "$WORK/valhalla/tiles.tar")
zstd -q -19 -T0 -f "$WORK/valhalla/tiles.tar" -o "$OUT/$ID/routing-$ID.tar.zst"

echo "== Address database"
"$PYTHON" "$TOOLS/build_addresses.py" "$PBF" "$WORK/addresses.sqlite" "$ID"
addresses_installed=$(stat -c %s "$WORK/addresses.sqlite" 2>/dev/null || stat -f %z "$WORK/addresses.sqlite")
zstd -q -19 -T0 -f "$WORK/addresses.sqlite" -o "$OUT/$ID/addresses-$ID.sqlite.zst"

osm_timestamp=$("$PYTHON" -c "import osmium,sys; print(osmium.io.Reader(sys.argv[1], osmium.osm.osm_entity_bits.NOTHING).header().get('osmosis_replication_timestamp', ''))" "$PBF")
valhalla_version="${VALHALLA_IMAGE##*:}"
cat > "$OUT/$ID/info.json" <<JSON
{
  "id": "$ID",
  "name": "$NAME",
  "osmTimestamp": "$osm_timestamp",
  "files": [
    { "kind": "routing", "name": "routing-$ID.tar.zst", "installedBytes": $routing_installed, "valhallaVersion": "$valhalla_version" },
    { "kind": "addresses", "name": "addresses-$ID.sqlite.zst", "installedBytes": $addresses_installed, "addressSchema": 1 }
  ]
}
JSON
echo "== $NAME done"
ls -l "$OUT/$ID"
