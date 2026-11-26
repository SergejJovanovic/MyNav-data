"""Copies an OSM extract with road, place and signpost names in Serbian Latin script.

Valhalla takes street names for its turn instructions from `name`, `destination…` and similar tags. In Serbia
these are mostly Cyrillic, so the app would say "Turn left onto Краља Александра". The mapped `name:sr-Latn`
is used where it exists; other Cyrillic values are transliterated.

Usage: latinize_names.py input.osm.pbf output.osm.pbf
"""
import re
import sys
import time

import osmium

from serbian import has_cyrillic, to_latin

NAME_KEYS = {
    "name", "alt_name", "official_name", "short_name", "loc_name",
    "destination", "destination:forward", "destination:backward",
    "destination:street", "destination:street:forward", "destination:street:backward",
    "junction:name", "exit_to",
}
# Language variants ("name:sr", "destination:lang:sr"): Valhalla joins them to the instruction text
# ("Kralja Aleksandra/Краља Александра"), so the routing data keeps the Latin main name only.
LANGUAGE_VARIANT = re.compile(
    r"^((name|alt_name|official_name|short_name|loc_name|old_name):[a-z]{2,3}(-[A-Za-z]{2,4})?"
    r"|destination(:street)?:lang:.+)$"
)


def without_repeats(value):
    """"Beograd / Beograd;Zrenjanin / Zrenjanin" → "Beograd;Zrenjanin": bilingual signs ("Београд / Beograd")
    say the same thing twice once transliterated."""
    items = []
    for item in value.split(";"):
        parts = [part.strip() for part in item.split("/")]
        unique = [part for index, part in enumerate(parts) if part and part.lower() not in (p.lower() for p in parts[:index])]
        items.append(" / ".join(unique) if len(unique) < len(parts) else item)
    return ";".join(items)


def latin_tags(tags):
    """The tags with Latin names and without language variants, or `None` when nothing changes."""
    changed = False
    result = {}
    for tag in tags:
        if LANGUAGE_VARIANT.match(tag.k):
            changed = True
            continue
        value = tag.v
        if tag.k in NAME_KEYS and has_cyrillic(value):
            value = tags.get("name:sr-Latn") if tag.k == "name" and "name:sr-Latn" in tags else to_latin(value)
            value = without_repeats(value)
            changed = True
        result[tag.k] = value
    return result if changed else None


class Latinizer(osmium.SimpleHandler):
    def __init__(self, writer):
        super().__init__()
        self.writer = writer
        self.changed = 0

    def _write(self, obj, add):
        tags = latin_tags(obj.tags)
        if tags is None:
            add(obj)
        else:
            self.changed += 1
            add(obj.replace(tags=tags))

    def node(self, n):
        self._write(n, self.writer.add_node)

    def way(self, w):
        self._write(w, self.writer.add_way)

    def relation(self, r):
        self._write(r, self.writer.add_relation)


def main(source, target):
    start = time.time()
    writer = osmium.SimpleWriter(target, overwrite=True)
    handler = Latinizer(writer)
    handler.apply_file(source)
    writer.close()
    print(f"latinized {handler.changed} objects in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
