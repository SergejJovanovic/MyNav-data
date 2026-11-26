"""Writes manifest.json describing every country package of a release.

Usage: build_manifest.py OUTPUT_DIR RELEASE_TAG REPOSITORY   (e.g. out data-2026-11-26 SergejJovanovic/MyNav-data)
Each country directory OUTPUT_DIR/<ID> holds info.json (written by build_country.sh) and the packaged files.
"""
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(output_dir, tag, repository):
    root = pathlib.Path(output_dir)
    countries = []
    for info_path in sorted(root.glob("*/info.json")):
        info = json.loads(info_path.read_text())
        for entry in info["files"]:
            path = info_path.parent / entry["name"]
            entry["bytes"] = path.stat().st_size
            entry["sha256"] = sha256(path)
            entry["url"] = f"https://github.com/{repository}/releases/download/{tag}/{entry['name']}"
        countries.append(info)
    manifest = {
        "schema": SCHEMA_VERSION,
        "release": tag,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "countries": countries,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(*sys.argv[1:4])
