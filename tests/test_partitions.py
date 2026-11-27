"""Check split-unit construction, assignment and the committed partitions."""
from collections import Counter
import json
import unittest

import pyarrow.parquet as pq

from scripts.freeze_partitions import (
    MANIFEST, OUTPUT, PARQUET, PARTITIONS, PILOT, SHARES, assign, build_partitions,
    group_partitions, split_units,
)
from scripts.inspect_aliases import find_links, group_profiles


class UnitChecks(unittest.TestCase):
    def test_units_cover_every_group_and_follow_links_transitively(self):
        units = split_units([1, 2, 3, 4, 5, 6], [(1, 2), (2, 5), (4, 6)])
        self.assertEqual(units, [[1, 2, 5], [3], [4, 6]])

    def test_assignment_is_deterministic_and_meets_the_shares(self):
        unit_ids = [f'{number:013d}' for number in range(200)]
        first = assign(unit_ids)
        self.assertEqual(first, assign(unit_ids[::-1]))
        self.assertEqual(Counter(first.values()), {'train': 140, 'validation': 30, 'test': 30})
        self.assertNotEqual(first, assign(unit_ids, seed='another seed'))

    def test_small_families_still_get_a_valid_assignment(self):
        self.assertEqual(assign([]), {})
        self.assertEqual(set(assign(['a', 'b']).values()), {'train'})


class CommittedPartitionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = pq.read_table(PARQUET).to_pylist()
        cls.digest = json.loads(MANIFEST.read_text())['content_sha256']
        cls.tasks = json.loads(PILOT.read_text())
        cls.report = json.loads(OUTPUT.read_text())
        cls.partition_of = group_partitions(cls.report)
        cls.eligible = {r['group_id']: r['family'] for r in cls.rows if r['eligible']}

    def test_rebuild_is_reproducible_independent_of_row_order(self):
        self.assertEqual(build_partitions(self.rows[::-1], self.digest, self.tasks), self.report)

    def test_every_eligible_group_is_in_exactly_one_single_family_unit(self):
        listed = [group_id for unit in self.report['units'] for group_id in unit['group_ids']]
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), set(self.eligible))
        self.assertEqual(len({unit['unit_id'] for unit in self.report['units']}),
                         len(self.report['units']))
        for unit in self.report['units']:
            self.assertIn(unit['partition'], PARTITIONS)
            self.assertEqual({self.eligible[g] for g in unit['group_ids']}, {unit['family']})

    def test_no_alias_link_crosses_partitions(self):
        links, _, _ = find_links(group_profiles(self.rows))
        self.assertTrue(links)
        for first, second in links:
            self.assertEqual(self.partition_of[first], self.partition_of[second])

    def test_calibration_holds_the_pilot_groups_and_nothing_else_does(self):
        reserved = {task['data'][f'{side}_group_id'] for task in self.tasks
                    for side in ('original', 'candidate')}
        for unit in self.report['units']:
            self.assertEqual(unit['partition'] == 'calibration',
                             bool(reserved & set(unit['group_ids'])))
        aliases = set(json.loads((OUTPUT.parent / 'alias_report.json').read_text())
                      ['calibration']['alias_groups_to_exclude_with_them'])
        self.assertTrue(aliases)
        self.assertEqual({self.partition_of[group_id] for group_id in aliases}, {'calibration'})

    def test_counts_match_the_units_and_the_shares_per_family(self):
        products = Counter(r['group_id'] for r in self.rows if r['eligible'])
        for family, counts in self.report['counts'].items():
            units = [unit for unit in self.report['units'] if unit['family'] == family]
            for partition in PARTITIONS:
                chosen = [unit for unit in units if unit['partition'] == partition]
                groups = [g for unit in chosen for g in unit['group_ids']]
                self.assertEqual(counts[partition], {
                    'units': len(chosen), 'groups': len(groups),
                    'products': sum(products[g] for g in groups)})
            development = len(units) - counts['calibration']['units']
            for partition, share in SHARES.items():
                self.assertEqual(counts[partition]['units'], round(share * development))
            self.assertGreater(counts['train']['units'], 0)
        self.assertEqual(self.report['units_total'], len(self.report['units']))
        self.assertEqual(self.report['catalog_content_sha256'], self.digest)
