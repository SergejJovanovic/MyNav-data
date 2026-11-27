import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

from serbian import display_name, normalize, to_latin  # noqa: E402
import build_addresses  # noqa: E402
from latinize_names import latin_tags  # noqa: E402


class Tag:
    def __init__(self, k, v):
        self.k, self.v = k, v


class Tags(list):
    def __init__(self, mapping):
        super().__init__(Tag(k, v) for k, v in mapping.items())
        self.mapping = mapping

    def get(self, key, default=None):
        return self.mapping.get(key, default)

    def __contains__(self, key):
        return key in self.mapping


class LatinizeTests(unittest.TestCase):
    def test_routing_names_become_latin_without_language_variants(self):
        tags = Tags({"highway": "primary", "name": "Краља Александра", "name:sr": "Краља Александра",
                     "name:sr-Latn": "Kralja Aleksandra", "name:en": "King Alexander Street", "ref": "M7"})
        self.assertEqual(latin_tags(tags), {"highway": "primary", "name": "Kralja Aleksandra", "ref": "M7"})

    def test_destinations_are_transliterated_and_their_language_copies_dropped(self):
        tags = Tags({"highway": "motorway_link", "destination": "Београд;Зрењанин", "destination:lang:sr": "Београд;Зрењанин",
                     "destination:lang:sr-Latn": "Beograd;Zrenjanin"})
        self.assertEqual(latin_tags(tags), {"highway": "motorway_link", "destination": "Beograd;Zrenjanin"})

    def test_bilingual_signs_are_said_once(self):
        tags = Tags({"highway": "motorway_link", "destination": "Београд / Beograd;Зрењанин / Zrenjanin", "destination:ref": "A1/A1/A4"})
        self.assertEqual(latin_tags(tags)["destination"], "Beograd;Zrenjanin")
        self.assertEqual(latin_tags(tags)["destination:ref"], "A1/A1/A4")

    def test_untouched_objects_are_left_alone(self):
        self.assertIsNone(latin_tags(Tags({"highway": "residential", "name": "Zmaj Jovina"})))


class SerbianTests(unittest.TestCase):
    def test_transliterates_serbian_cyrillic(self):
        self.assertEqual(to_latin("Булевар ослобођења"), "Bulevar oslobođenja")
        self.assertEqual(to_latin("Џорџа Вашингтона"), "Džordža Vašingtona")
        self.assertEqual(to_latin("Љубљанска"), "Ljubljanska")
        self.assertEqual(to_latin("ЊЕГОШЕВА"), "NJEGOŠEVA")

    def test_latin_text_is_unchanged(self):
        self.assertEqual(to_latin("Zmaj Jovina 5"), "Zmaj Jovina 5")

    def test_normalisation_matches_both_scripts_and_plain_letters(self):
        key = "bulevar oslobodjenja"
        self.assertEqual(normalize("Булевар ослобођења"), key)
        self.assertEqual(normalize("Bulevar oslobođenja"), key)
        self.assertEqual(normalize("  BULEVAR   oslobodjenja, "), key)
        self.assertEqual(normalize("Ćirila i Metodija"), "cirila i metodija")

    def test_display_name_prefers_mapped_latin(self):
        self.assertEqual(display_name({"name": "Нови Сад", "name:sr-Latn": "Novi Sad"}), "Novi Sad")
        self.assertEqual(display_name({"name": "Чачак"}), "Čačak")
        self.assertIsNone(display_name({}))


class FakeCollector:
    def __init__(self, addresses, roads, places, place_aliases=None):
        self.addresses, self.roads, self.places = addresses, roads, places
        self.place_aliases = place_aliases or {}


class AddressDatabaseTests(unittest.TestCase):
    def build(self):
        collector = FakeCollector(
            addresses=[
                ("Змај Јовина", "5", "", 45.2560, 19.8450),
                ("Змај Јовина", "7", "", 45.2561, 19.8451),
                # Same street name in another town.
                ("Змај Јовина", "5", "", 44.8200, 20.4600),
                ("Главна", "1", "Футог", 45.2400, 19.7000),
                # Town typed in English; an unknown town is ignored.
                ("Кнеза Михаила", "10", "Belgrade", 44.8180, 20.4570),
                ("Кнеза Михаила", "12", "Nowhere", 44.8181, 20.4571),
            ],
            roads=[("Змај Јовина", "Zmaj Jovina", 45.2558, 19.8452)],
            places=[("Novi Sad", "city", 45.2550, 19.8450), ("Beograd", "city", 44.8180, 20.4580), ("Veternik", "village", 45.2560, 19.8300)],
            place_aliases={"novi sad": ("Novi Sad", 4.0), "beograd": ("Beograd", 4.0), "belgrade": ("Beograd", 4.0),
                           "futog": ("Futog", 1.0), "veternik": ("Veternik", 1.0)},
        )
        return build_addresses.build(collector, "RS", "2026-11-25T21:00:00Z")

    def test_streets_are_split_by_town_and_named_in_latin(self):
        streets, addresses = self.build()
        towns = sorted((row[1], row[3]) for row in streets)
        self.assertEqual(towns, [("Glavna", "Futog"), ("Kneza Mihaila", "Beograd"), ("Zmaj Jovina", "Beograd"), ("Zmaj Jovina", "Novi Sad")])
        self.assertEqual(len(addresses), 6)

    def test_a_city_wins_over_a_closer_village(self):
        streets, _ = self.build()
        novi_sad = [row for row in streets if row[3] == "Novi Sad"]
        self.assertEqual(len(novi_sad), 1)

    def test_database_finds_street_and_number(self):
        streets, addresses = self.build()
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/a.sqlite"
            build_addresses.write(path, streets, addresses, "RS", "2026-11-25T21:00:00Z")
            db = sqlite3.connect(path)
            rows = db.execute("""
                SELECT s.name, s.city, a.housenumber FROM street_fts f JOIN street s ON s.id = f.rowid
                JOIN address a ON a.street_id = s.id
                WHERE street_fts MATCH 'name : (zmaj jovina) AND city : (novi sad)' AND a.housenumber = '7'
            """).fetchall()
            self.assertEqual(rows, [("Zmaj Jovina", "Novi Sad", "7")])
            self.assertEqual(dict(db.execute("SELECT key, value FROM meta"))["addresses"], "6")
            prefix = db.execute("SELECT count(*) FROM street_fts WHERE street_fts MATCH 'name : zma*'").fetchone()[0]
            self.assertEqual(prefix, 2)


if __name__ == "__main__":
    unittest.main()


import build_roaddata  # noqa: E402


def read_varints(blob):
    values, number, shift = [], 0, 0
    for byte in blob:
        number |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            values.append((number >> 1) ^ -(number & 1))
            number, shift = 0, 0
    return values


class RoadDataTests(unittest.TestCase):
    def test_node_ids_round_trip_as_deltas(self):
        ids = [9_876_543_210, 9_876_543_215, 12, 9_876_543_300]
        deltas = read_varints(build_roaddata.zigzag_varints(ids))
        restored, total = [], 0
        for delta in deltas:
            total += delta
            restored.append(total)
        self.assertEqual(restored, ids)

    def test_coordinates_round_trip_as_interleaved_deltas(self):
        points = [(45255100, 19845100), (45255300, 19844900), (-33000000, -70000000)]
        deltas = read_varints(build_roaddata.zigzag_coordinates(points))
        restored, lat, lon = [], 0, 0
        for index in range(0, len(deltas), 2):
            lat += deltas[index]
            lon += deltas[index + 1]
            restored.append((lat, lon))
        self.assertEqual(restored, points)

    def test_only_tags_the_app_reads_are_kept(self):
        class Tag:
            def __init__(self, k, v):
                self.k, self.v = k, v
        tags = [Tag("highway", "primary"), Tag("maxspeed", "50"), Tag("turn:lanes:forward", "left|through"),
                Tag("bus:lanes", "|designated"), Tag("surface", "asphalt"), Tag("name", "Bulevar")]
        self.assertEqual(build_roaddata.kept_way_tags(tags),
                         {"highway": "primary", "maxspeed": "50", "turn:lanes:forward": "left|through", "bus:lanes": "|designated", "name": "Bulevar"})

    def test_roads_include_links_but_not_footways(self):
        self.assertTrue(build_roaddata.is_road("primary_link"))
        self.assertTrue(build_roaddata.is_road("service"))
        self.assertFalse(build_roaddata.is_road("footway"))
        self.assertFalse(build_roaddata.is_road(None))
