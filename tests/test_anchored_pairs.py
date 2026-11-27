"""Check format evidence, anchored pair selection and the committed anchored pairs."""
from collections import Counter
import json
import unittest
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

from basket.anchored import (
    ANCHORS, CANDIDATES_PER_ANCHOR, MAX_USES_PER_CANDIDATE, STRATEGIES, build_anchored_pairs,
    choose, triplet_ceiling,
)
from basket.formats import coconut_percent, format_evidence
from basket.pairs import representatives
from scripts.build_anchored_pairs import OUTPUT, ROOT, earlier_tasks
from scripts.build_annotation_pilot import CONTEXTS
from scripts.build_catalog import MANIFEST, PARQUET
from scripts.build_pairs import PARTITIONS
from scripts.review_agreement import load_tasks


def row(family, name, ingredients='', brands=None):
    return {'family': family, 'name': name, 'ingredients_text': ingredients, 'brands': brands}


class FormatEvidenceChecks(unittest.TestCase):
    def test_yogurt_drinks_are_flagged_by_name_or_brand(self):
        self.assertEqual(format_evidence(row('yogurts', 'Yaourt à boire sucré')),
                         ['drink_or_pouch_name'])
        self.assertEqual(format_evidence(row('yogurts', 'Goût Fraise', brands='Yop, Yoplait')),
                         ['drink_brand'])
        self.assertEqual(format_evidence(row('yogurts', 'Yaourt nature', brands='Danone')), [])

    def test_cooking_coconut_milk_is_flagged_and_coconut_drinks_are_not(self):
        cooking = row('plant_based_milk_alternatives', 'Lait de coco', 'Extrait de coco 85%, eau.')
        self.assertEqual(format_evidence(cooking),
                         ['coconut_25_percent_or_more', 'coconut_milk_name'])
        drink = row('plant_based_milk_alternatives', 'Coconut Original',
                    'eau, lait de coco (5,3%) (crème de noix de coco, eau), riz (3,3%)')
        self.assertEqual(format_evidence(drink), [])
        self.assertEqual(format_evidence(row('plant_based_milk_alternatives', 'Crème de soja')),
                         ['cream_cooking_or_powder_name'])

    def test_coconut_percent_reads_the_figure_after_the_ingredient(self):
        self.assertEqual(coconut_percent('Kokosnussextrakt 70%, Wasser'), 70)
        self.assertEqual(coconut_percent('Eau, riz 14%, lait de coco 6%, sel'), 6)
        self.assertIsNone(coconut_percent('Water, soya beans 9%'))
        self.assertIsNone(coconut_percent(None))

    def test_porridge_and_bars_are_flagged_among_cereals_only(self):
        self.assertEqual(format_evidence(row('breakfast_cereals', 'Porridge avoine chocolat')),
                         ['porridge_or_flour_name'])
        self.assertEqual(format_evidence(row('breakfast_cereals', 'Barres de céréales')),
                         ['bar_or_snack_name'])
        self.assertEqual(format_evidence(row('breakfast_cereals', 'All Bran Flakes')), [])
        self.assertEqual(format_evidence(row('breakfast_cereals', 'Son de blé')),
                         ['bran_or_germ_name'])
        self.assertEqual(format_evidence(row('yogurts', 'Porridge')), [])
        self.assertEqual(format_evidence(row('other_family', 'Yaourt à boire')), [])


class SelectionChecks(unittest.TestCase):
    def setUp(self):
        self.products = {group_id: {'code': f'{group_id:04d}'} for group_id in range(1, 31)}
        self.unit_of = {group_id: f'unit-{group_id}' for group_id in self.products}
        self.pool = sorted(self.products)

    def select(self, flagged, anchors=8, taken=(), unit_of=None):
        return choose(self.pool, set(flagged), self.products, unit_of or self.unit_of,
                      'train', 'yogurts', anchors, taken)

    def test_anchors_are_unflagged_and_never_serve_as_candidates(self):
        flagged = range(1, 11)
        chosen, selected = self.select(flagged)
        self.assertEqual(len(chosen), 8)
        self.assertFalse(set(chosen) & set(flagged))
        self.assertFalse({candidate for _, candidate, _ in selected} & set(chosen))
        self.assertEqual((chosen, selected), self.select(flagged))
        for anchor in chosen:
            drawn = Counter(strategy for a, _, strategy in selected if a == anchor)
            self.assertEqual(drawn, CANDIDATES_PER_ANCHOR)
        for _, candidate, strategy in selected:
            self.assertEqual(candidate in set(flagged), strategy == 'other_format')

    def test_a_scarce_strategy_is_spread_over_the_anchors_within_the_cap(self):
        chosen, selected = self.select([1, 2])
        other = [(anchor, candidate) for anchor, candidate, strategy in selected
                 if strategy == 'other_format']
        self.assertEqual(len(other), 2 * MAX_USES_PER_CANDIDATE)
        self.assertEqual(len({anchor for anchor, _ in other}), 6)   # one each before any second
        self.assertEqual(max(Counter(candidate for _, candidate, _ in selected).values()),
                         MAX_USES_PER_CANDIDATE)

    def test_pairs_inside_one_unit_or_taken_by_another_set_are_skipped(self):
        chosen, selected = self.select([1, 2], anchors=2)
        anchor = chosen[0]
        same_unit = {**self.unit_of, 1: self.unit_of[anchor]}
        _, without_unit = self.select([1, 2], anchors=2, unit_of=same_unit)
        self.assertNotIn((anchor, 1), [(a, c) for a, c, _ in without_unit])
        self.assertIn((anchor, 2), [(a, c) for a, c, _ in without_unit])
        _, without_taken = self.select([1, 2], anchors=2, taken=[(2, anchor)])
        self.assertNotIn((anchor, 2), [(a, c) for a, c, _ in without_taken])
        self.assertTrue(selected)

    def test_triplet_ceiling_splits_each_anchor_evenly(self):
        self.assertEqual(triplet_ceiling([4, 3, 2, 1, 0]), 4 + 2 + 1)


class CommittedAnchoredPairChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = pq.read_table(PARQUET).to_pylist()
        cls.digest = json.loads(MANIFEST.read_text())['content_sha256']
        cls.partitions = json.loads(PARTITIONS.read_text())
        cls.report = json.loads(OUTPUT.read_text())
        cls.data = [task['data'] for task in cls.report['tasks']]
        cls.products = representatives(cls.rows)
        cls.unit_of = {group: unit['unit_id'] for unit in cls.partitions['units']
                       for group in unit['group_ids']}
        cls.partition_of = {group: unit['partition'] for unit in cls.partitions['units']
                            for group in unit['group_ids']}

    def test_rebuild_is_reproducible_independent_of_row_order(self):
        self.assertEqual(build_anchored_pairs(self.rows[::-1], self.partitions, CONTEXTS,
                                              self.digest, earlier_tasks()), self.report)

    def test_each_pair_stays_in_one_partition_family_and_unit_and_joins_two_split_units(self):
        for data in self.data:
            unit, context = CONTEXTS[data['family']]
            self.assertEqual((data['comparison_unit'], data['context']), (unit, context))
            self.assertIn(data['partition'], ANCHORS)
            for side in ('original', 'candidate'):
                product = self.products[data[f'{side}_group_id']]
                self.assertTrue(product['eligible'])
                self.assertEqual((product['family'], product['comparison_unit']),
                                 (data['family'], unit))
                self.assertEqual(self.partition_of[product['group_id']], data['partition'])
                for field in ('code', 'name', 'brands', 'lang', 'ingredients_text'):
                    self.assertEqual(data[f'{side}_{field}'], product[field])
            self.assertNotEqual(self.unit_of[data['original_group_id']],
                                self.unit_of[data['candidate_group_id']])

    def test_strategy_follows_the_format_evidence_and_anchors_have_none(self):
        anchors = {data['original_group_id'] for data in self.data}
        candidates = {data['candidate_group_id'] for data in self.data}
        self.assertFalse(anchors & candidates)
        for data in self.data:
            self.assertIn(data['strategy'], STRATEGIES)
            self.assertEqual(format_evidence(self.products[data['original_group_id']]), [])
            evidence = format_evidence(self.products[data['candidate_group_id']])
            self.assertEqual(data['candidate_format_evidence'], evidence)
            self.assertEqual(bool(evidence), data['strategy'] == 'other_format')

    def test_pair_ids_are_unique_and_no_group_pair_repeats_the_earlier_set(self):
        ids = [data['pair_id'] for data in self.data]
        self.assertEqual(len(ids), len(set(ids)))
        for data in self.data:
            self.assertEqual(data['pair_id'], f"anchored-pairs-v1/{data['partition']}/"
                             f"{data['family']}/{data['original_code']}/{data['candidate_code']}")
        pairs = [frozenset((data['original_group_id'], data['candidate_group_id']))
                 for data in self.data]
        self.assertEqual(len(pairs), len(set(pairs)))
        earlier = {frozenset((task['data']['original_group_id'],
                              task['data']['candidate_group_id'])) for task in earlier_tasks()}
        self.assertFalse(set(pairs) & earlier)
        self.assertEqual(self.report['parameters']['excluded_earlier_pairs'], len(earlier))

    def test_counts_caps_shortfalls_and_ceiling_match_the_tasks(self):
        uses = Counter((data['partition'], data['candidate_group_id']) for data in self.data)
        self.assertLessEqual(max(uses.values()), MAX_USES_PER_CANDIDATE)
        ceiling = 0
        for family, counts in self.report['counts'].items():
            for partition, count in counts.items():
                chosen = [data for data in self.data
                          if (data['family'], data['partition']) == (family, partition)]
                per_anchor = Counter(data['original_group_id'] for data in chosen)
                self.assertEqual(count['pairs'], len(chosen))
                self.assertEqual(count['anchors'], ANCHORS[partition])
                self.assertLessEqual(len(per_anchor), count['anchors'])
                for strategy in STRATEGIES:
                    drawn = sum(data['strategy'] == strategy for data in chosen)
                    self.assertEqual(count[strategy], drawn)
                    requested = count['anchors'] * CANDIDATES_PER_ANCHOR[strategy]
                    key = f'{family}|{partition}|{strategy}'
                    self.assertEqual(key in self.report['shortfalls'], drawn < requested)
                self.assertEqual(count['triplet_ceiling'], triplet_ceiling(per_anchor.values()))
                ceiling += count['triplet_ceiling']
        self.assertEqual(self.report['triplet_ceiling'], ceiling)
        self.assertEqual(self.report['pairs_total'], len(self.data))
        self.assertEqual(self.report['catalog_content_sha256'], self.digest)
        self.assertEqual(self.report['partitions_version'], self.partitions['version'])

    def test_tasks_fit_the_review_form_carry_no_label_and_load_for_the_agreement_check(self):
        form = ET.parse(ROOT / 'docs/annotation_form.xml')
        fields = {text.get('value')[1:] for text in form.iter('Text')}
        for task in self.report['tasks']:
            self.assertEqual(set(task), {'data'})
            self.assertTrue(all(task['data'][field] for field in fields))
            self.assertFalse({'label', 'decision', 'annotations'} & set(task['data']))
        self.assertEqual(len(load_tasks(OUTPUT)), self.report['pairs_total'])


if __name__ == '__main__':
    unittest.main()
