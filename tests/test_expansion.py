"""Checks for the family-targeted catalog expansion (return to step 2 for step 4)."""
import gzip
import hashlib
import json
from pathlib import Path
import unittest

from basket.comparable import FAMILIES
from scripts.expand_catalog import SCAN_FIELDS, candidate_family, choose_wave, eligible_group_key

ROOT = Path(__file__).resolve().parents[1]
EXPANSION = ROOT / 'data/catalog_expansion.jsonl.gz'
EXPANSION_MANIFEST = ROOT / 'data/catalog_expansion_manifest.json'


def row(**overrides):
    base = {'categories_tags': ['en:dairies', 'en:yogurts'], 'product_quantity_unit': 'g',
            'environmental_score_score': 55}
    base.update(overrides)
    return base


class CandidateRuleChecks(unittest.TestCase):
    def test_requires_family_unit_and_numeric_score(self):
        self.assertEqual(candidate_family(row()), 'yogurts')
        self.assertEqual(candidate_family(row(categories_tags=['en:milk-substitutes'],
                                             product_quantity_unit='ml')), 'plant_based_milk_alternatives')
        self.assertIsNone(candidate_family(row(categories_tags=['en:cheeses'])))
        self.assertIsNone(candidate_family(row(product_quantity_unit=None)))
        self.assertIsNone(candidate_family(row(product_quantity_unit='oz')))
        self.assertIsNone(candidate_family(row(environmental_score_score=None)))
        self.assertIsNone(candidate_family(row(environmental_score_score=float('nan'))))
        self.assertIsNone(candidate_family(row(environmental_score_score=True)))

    def test_scan_fields_cover_the_candidate_rule_only(self):
        self.assertEqual(SCAN_FIELDS, ['categories_tags', 'product_quantity_unit', 'environmental_score_score'])

    def test_eligibility_comes_from_comparable_rules(self):
        incomplete = row(code='1', product_name=[{'lang': 'main', 'text': 'Yogurt'}], brands='B',
                         ingredients_text=None, nutriments=[], environmental_score_data=None)
        self.assertIsNone(eligible_group_key(incomplete))
        complete = dict(incomplete, ingredients_text=[{'lang': 'main', 'text': 'Milk'}],
                        nutriments=[{'name': n, '100g': 1.0} for n in ('proteins', 'sugars', 'salt')],
                        environmental_score_data=json.dumps({'status': 'known', 'scores': {'fr': 55, 'world': 55}}))
        self.assertEqual(eligible_group_key(complete), 'yogurt|b')


class WaveChoiceChecks(unittest.TestCase):
    scan = {
        1: {'yogurts': [0, 1, 2, 3], 'breakfast_cereals': [4]},
        2: {'plant_based_milk_alternatives': [0, 1], 'breakfast_cereals': [2]},
        3: {'yogurts': [0]},
        4: {'breakfast_cereals': [0, 1, 2]},
        5: {},
    }

    def test_prefers_groups_dense_in_families_still_below_target(self):
        needed = {'yogurts': 0, 'breakfast_cereals': 50, 'plant_based_milk_alternatives': 80}
        self.assertEqual(choose_wave(self.scan, {1, 2, 3, 4, 5}, needed, wave_size=2), [2, 4])
        self.assertEqual(choose_wave(self.scan, {1, 2, 3, 4, 5}, needed, wave_size=10), [2, 4, 1])
        self.assertEqual(choose_wave(self.scan, {1, 3, 5}, needed, wave_size=10), [1])
        self.assertEqual(choose_wave(self.scan, {3, 5}, needed, wave_size=10), [])

    def test_ties_break_by_row_group_index_and_read_groups_are_excluded(self):
        needed = {'yogurts': 10, 'breakfast_cereals': 0, 'plant_based_milk_alternatives': 0}
        scan = {7: {'yogurts': [0]}, 2: {'yogurts': [0]}, 9: {'yogurts': [0, 1]}}
        self.assertEqual(choose_wave(scan, {7, 2, 9}, needed, wave_size=3), [9, 2, 7])
        self.assertEqual(choose_wave(scan, {7, 2}, needed, wave_size=3), [2, 7])


@unittest.skipUnless(EXPANSION.exists() and EXPANSION_MANIFEST.exists(), 'expansion not acquired')
class CommittedExpansionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(EXPANSION_MANIFEST.read_text())
        raw = gzip.decompress(EXPANSION.read_bytes())
        cls.sha256 = hashlib.sha256(raw).hexdigest()
        cls.rows = [json.loads(line) for line in raw.splitlines()]
        cls.base = json.loads((ROOT / 'data/catalog_manifest.json').read_text())

    def test_provenance_matches_pinned_source_and_fields(self):
        self.assertEqual(self.manifest['revision'], self.base['revision'])
        self.assertEqual(self.manifest['download_url'], self.base['download_url'])
        self.assertEqual(self.manifest['selected_fields'], self.base['selected_fields'])
        self.assertEqual(self.manifest['sha256'], self.sha256)
        self.assertEqual(self.manifest['sample_rows'], len(self.rows))
        self.assertEqual(self.manifest['selection']['families'],
                         {family: list(tags) for family, tags in FAMILIES.items()})
        self.assertLessEqual(len(self.manifest['read']['row_groups_read']),
                             self.manifest['read']['max_row_groups'])

    def test_rows_are_candidates_with_full_fields_and_no_overlap(self):
        expected = set(self.base['selected_fields']) | {'_source_row'}
        self.assertTrue(all(set(r) == expected for r in self.rows))
        self.assertTrue(all(candidate_family(r) for r in self.rows))
        codes = [r['code'] for r in self.rows]
        self.assertEqual(len(codes), len(set(codes)))
        source_rows = [r['_source_row'] for r in self.rows]
        self.assertEqual(source_rows, sorted(source_rows))
        self.assertEqual(len(source_rows), len(set(source_rows)))
        base_codes = {json.loads(line)['code']
                      for line in gzip.open(ROOT / 'data/catalog.jsonl.gz', 'rt')}
        self.assertFalse(base_codes & set(codes))
        self.assertEqual(sorted(self.manifest['selection']['excluded_row_groups']),
                         sorted(self.base['row_groups']))
        self.assertFalse(set(self.manifest['read']['row_groups_read']) & set(self.base['row_groups']))

    def test_historical_manifests_are_untouched(self):
        historical = json.loads((ROOT / 'data/manifest.json').read_text())
        self.assertEqual(historical['sha256'], '3449e2da9d6739f1b5385ef2b3db903fc2014ec0e49be2ca9e719b6f3167edc3')
        self.assertEqual(self.base['sha256'], 'bed73b68cbbc3a003300d1cc98d7a1c7df5fd559e1e83a52c6e8dd50adc566da')


if __name__ == '__main__':
    unittest.main()
