"""检查演练资料的读取契约和关联锚点。"""
import csv
from pathlib import Path
import unittest

INPUTS = Path(__file__).resolve().parent.parent / "samples"

HEADERS = {'families': ('family', 'priority', 'joined', 'worker_site', 'caregiver', 'latest_start'), 'children': ('child', 'family', 'class', 'pickup_allowed'), 'shifts': ('option', 'family', 'day', 'start', 'end', 'state'), 'rooms': ('room', 'centre', 'class', 'day', 'start', 'end', 'seats', 'staff_group', 'staff_limit'), 'travel': ('place_a', 'place_b', 'minutes'), 'offers': ('offer', 'family', 'child', 'room', 'state', 'asof'), 'changes': ('change', 'kind', 'room', 'start', 'end', 'seats', 'notice')}
REFERENCES = [('offers', 'child', 'children', 'child'), ('offers', 'room', 'rooms', 'room'), ('changes', 'room', 'rooms', 'room'), ('shifts', 'family', 'families', 'family')]
EXAMPLES = [['offers', 'offer', 'O2', 4], ['shifts', 'option', 'X', 2], ['changes', 'room', 'P4', 1]]


class SampleInputContract(unittest.TestCase):
    def read(self, table):
        with (INPUTS / f"{table}.csv").open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            self.assertEqual(tuple(reader.fieldnames), HEADERS[table])
            rows = list(reader)
        self.assertTrue(rows, table)
        for row in rows:
            self.assertNotIn(None, row, table)
            self.assertNotIn(None, row.values(), table)
        return rows

    def test_csv_readable_with_documented_columns(self):
        for table in HEADERS:
            with self.subTest(table=table):
                self.read(table)

    def test_cross_source_example_references(self):
        for source, source_field, target, target_field in REFERENCES:
            with self.subTest(source=source, field=source_field, target=target):
                available = {row[target_field] for row in self.read(target)}
                actual = {value for row in self.read(source)
                          for value in row[source_field].split("|") if value}
                self.assertTrue(actual)
                self.assertEqual(actual - available, set())

    def test_example_revisions_and_overlaps_are_present(self):
        for table, field, example, expected in EXAMPLES:
            with self.subTest(table=table, field=field, example=example):
                found = sum((row[field] == example if "|" in example else example in row[field].split("|")) for row in self.read(table))
                self.assertEqual(found, expected)


if __name__ == "__main__":
    unittest.main()
