"""Check pair sampling rules and the committed annotation pairs."""
from collections import Counter
import json
import unittest

import pyarrow.parquet as pq

from basket.pairs import (
    BUDGETS, LOOKALIKE_MIN_JACCARD, MAX_PAIRS_PER_GROUP, STRATEGIES, build_pairs, jaccard,
    representatives, select, strategy_of,
)
from scripts.build_annotation_pilot import CONTEXTS
from scripts.build_catalog import MANIFEST, PARQUET
from scripts.build_pairs import OUTPUT, PARTITIONS


def product(code, group_id, name, brands='Brand A'):
    return {'code': code, 'group_id': group_id, 'name': name, 'brands': brands, 'lang': 'en',
            'ingredients_text': 'milk', 'family': 'yogurts', 'eligible': True}


class SamplingRuleChecks(unittest.TestCase):
    def test_representatives_keep_the_lowest_eligible_barcode_per_group(self):
        rows = [product('30', 1, 'Late'), product('10', 1, 'Early'), product('20', 2, 'Other')]
        rows.append(dict(product('05', 1, 'Excluded'), eligible=False))
        self.assertEqual({group: row['code'] for group, row in representatives(rows).items()},
                         {1: '10', 2: '20'})

    def test_jaccard_measures_shared_name_tokens(self):
        self.assertEqual(jaccard({'a', 'b'}, {'a', 'b'}), 1.0)
        self.assertEqual(jaccard({'a', 'b'}, {'b', 'c'}), 1 / 3)
        self.assertEqual(jaccard(set(), set()), 0.0)

    def test_name_overlap_decides_the_strategy_before_the_brand(self):
        self.assertEqual(strategy_of(LOOKALIKE_MIN_JACCARD, False), 'lookalike')
        self.assertEqual(strategy_of(LOOKALIKE_MIN_JACCARD, True), 'lookalike')
        self.assertEqual(strategy_of(0.1, True), 'brand_variant')
        self.assertEqual(strategy_of(0.1, False), 'family_random')

    def test_selection_is_deterministic_and_caps_how_often_a_group_is_used(self):
        products = {index: product(f'{index:03d}', index, f'Yogurt flavor {index}')
                    for index in range(1, 13)}
        units = {index: index for index in products}
        first, quotas = select(list(products), products, units, 'train', 'yogurts', 12)
        self.assertEqual(sum(quotas.values()), 12)
        self.assertEqual(first, select(list(products)[::-1], products, units,
                                       'train', 'yogurts', 12)[0])
        used = Counter(group for _, _, pair, _, _ in first for group in pair)
        self.assertLessEqual(max(used.values()), MAX_PAIRS_PER_GROUP)
        self.assertNotEqual(first, select(list(products), products, units,
                                          'train', 'yogurts', 12, seed='other')[0])

    def test_groups_of_one_split_unit_are_never_paired(self):
        products = {index: product(f'{index:03d}', index, 'Plain yogurt') for index in range(1, 5)}
        self.assertEqual(select(list(products), products, {1: 1, 2: 1, 3: 1, 4: 1},
                                'train', 'yogurts', 6)[0], [])


class CommittedPairChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = pq.read_table(PARQUET).to_pylist()
        cls.digest = json.loads(MANIFEST.read_text())['content_sha256']
        cls.partitions = json.loads(PARTITIONS.read_text())
        cls.report = json.loads(OUTPUT.read_text())
        cls.partition_of = {group: unit['partition'] for unit in cls.partitions['units']
                            for group in unit['group_ids']}
        cls.unit_of = {group: unit['unit_id'] for unit in cls.partitions['units']
                       for group in unit['group_ids']}

    def test_rebuild_is_reproducible_independent_of_row_order(self):
        self.assertEqual(build_pairs(self.rows[::-1], self.partitions, CONTEXTS, self.digest),
                         self.report)

    def test_both_sides_sit_in_one_partition_and_different_units(self):
        for task in self.report['tasks']:
            data = task['data']
            groups = (data['original_group_id'], data['candidate_group_id'])
            self.assertEqual({self.partition_of[group] for group in groups}, {data['partition']})
            self.assertNotEqual(*[self.unit_of[group] for group in groups])
            self.assertIn(data['partition'], BUDGETS)

    def test_no_calibration_or_ineligible_group_is_used(self):
        eligible = {row['group_id']: row['family'] for row in self.rows if row['eligible']}
        for task in self.report['tasks']:
            data = task['data']
            for role in ('original', 'candidate'):
                group = data[f'{role}_group_id']
                self.assertEqual(eligible[group], data['family'])
                self.assertNotEqual(self.partition_of[group], 'calibration')

    def test_pair_ids_are_unique_and_name_the_two_barcodes(self):
        identifiers = [task['data']['pair_id'] for task in self.report['tasks']]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for task in self.report['tasks']:
            data = task['data']
            self.assertEqual(data['pair_id'], f"{self.report['version']}/{data['partition']}/"
                                              f"{data['family']}/{data['original_code']}/"
                                              f"{data['candidate_code']}")
            self.assertLess(data['original_code'], data['candidate_code'])

    def test_every_task_carries_the_review_form_fields_and_no_label(self):
        for task in self.report['tasks']:
            self.assertEqual(set(task), {'data'})
            for field in ('context', 'original_name', 'original_ingredients_text',
                          'candidate_name', 'candidate_ingredients_text'):
                self.assertTrue(task['data'][field])
            self.assertEqual(task['data']['catalog_content_sha256'], self.digest)
            self.assertEqual(task['data']['comparison_unit'],
                             CONTEXTS[task['data']['family']][0])

    def test_counts_and_budgets_match_the_tasks(self):
        self.assertEqual(self.report['pairs_total'], len(self.report['tasks']))
        self.assertEqual(self.report['partitions_version'], self.partitions['version'])
        for family, partitions in self.report['counts'].items():
            for partition, counts in partitions.items():
                tasks = [task['data'] for task in self.report['tasks']
                         if task['data']['family'] == family
                         and task['data']['partition'] == partition]
                self.assertEqual(counts['pairs'], len(tasks))
                self.assertLessEqual(counts['pairs'], BUDGETS[partition])
                taken = Counter(task['strategy'] for task in tasks)
                for strategy in STRATEGIES:
                    self.assertEqual(counts[strategy], taken[strategy])

    def test_every_strategy_holds_the_similarity_it_claims(self):
        for task in self.report['tasks']:
            data = task['data']
            self.assertEqual(strategy_of(data['name_jaccard'], data['shared_brand']),
                             data['strategy'])


if __name__ == '__main__':
    unittest.main()
