"""Checks for the comparable catalog rules (pipeline step 3)."""
import json
from pathlib import Path
import unittest

from basket.comparable import (
    FAMILIES, assign_family, build_record, clean_text, environmental_score, finalize,
    group_key, normalize_key, nutrients_per_100,
)

ROOT = Path(__file__).resolve().parents[1]


def raw_row(**overrides):
    row = {
        'code': '1', '_source_row': 1,
        'product_name': [{'lang': 'main', 'text': 'Yaourt nature'}, {'lang': 'fr', 'text': 'Yaourt nature'}],
        'brands': 'Ferme',
        'categories_tags': ['en:dairies', 'en:yogurts'],
        'ingredients_text': [{'lang': 'main', 'text': '<span class="allergen">Lait</span> entier, ferments'}],
        'lang': 'fr', 'labels_tags': ['en:organic'], 'ingredients_analysis_tags': ['en:vegetarian'],
        'allergens_tags': ['en:milk'], 'traces_tags': [],
        'product_quantity': '500', 'product_quantity_unit': 'g', 'nutrition_data_per': '100g',
        'nutriments': [
            {'name': 'proteins', '100g': 3.5, 'unit': 'g'},
            {'name': 'sugars', '100g': 4.0, 'unit': 'g'},
            {'name': 'salt', '100g': 0.1, 'value': 100.0, 'unit': 'mg'},
            {'name': 'energy-kcal', '100g': 60.0, 'unit': 'kcal'},
        ],
        'environmental_score_data': json.dumps({
            'status': 'known', 'scores': {'fr': 70, 'world': 65}, 'grades': {'fr': 'b'},
            'grade': 'b', 'agribalyse': {'version': '3.2'}, 'missing_key_data': 1}),
        'last_modified_t': 1,
    }
    row.update(overrides)
    return row


class TextChecks(unittest.TestCase):
    def test_clean_text_removes_markup_and_keeps_words(self):
        self.assertEqual(clean_text('<span class="allergen">Wheat</span> flour, malt d\'_orge_ &amp; eau'),
                         "Wheat flour, malt d'orge & eau")
        self.assertIsNone(clean_text(''))
        self.assertIsNone(clean_text('<br/>'))

    def test_normalize_key_folds_accents_case_and_keeps_non_latin_scripts(self):
        self.assertEqual(normalize_key('  Invitation à la Ferme! '), 'invitation a la ferme')
        self.assertEqual(normalize_key('Голубцы Мясновъ'), 'голубцы мясновъ')
        self.assertNotEqual(normalize_key('Голубцы'), normalize_key('Κεφαλογραβιέρα'))
        self.assertEqual(normalize_key('???'), '')

    def test_group_key_falls_back_to_code_without_usable_name(self):
        self.assertEqual(group_key('9', 'Yaourt Nature', 'Ferme'), 'yaourt nature|ferme')
        self.assertEqual(group_key('9', 'Yaourt nature', None), 'yaourt nature|')
        self.assertEqual(group_key('9', '???', 'Ferme'), 'code:9')
        self.assertEqual(group_key('9', None, 'Ferme'), 'code:9')


class NutrientChecks(unittest.TestCase):
    def test_values_come_from_100g_key_already_in_grams(self):
        values, implausible = nutrients_per_100([
            {'name': 'salt', '100g': 0.3575, 'value': 357.5, 'unit': 'mg'},
            {'name': 'proteins', '100g': 12, 'unit': ''},
            {'name': 'sugars', '100g': None},
            {'name': 'fiber', '100g': float('nan')},
            {'name': 'nova-group', '100g': 4},
        ])
        self.assertEqual(values['salt_g_per_100'], 0.3575)
        self.assertEqual(values['proteins_g_per_100'], 12.0)
        self.assertIsNone(values['sugars_g_per_100'])
        self.assertIsNone(values['fiber_g_per_100'])
        self.assertEqual(implausible, [])

    def test_implausible_values_become_missing_and_are_recorded(self):
        values, implausible = nutrients_per_100([
            {'name': 'salt', '100g': 857.0}, {'name': 'proteins', '100g': -1},
            {'name': 'energy-kcal', '100g': 901}, {'name': 'sugars', '100g': 100.0},
        ])
        self.assertIsNone(values['salt_g_per_100'])
        self.assertIsNone(values['proteins_g_per_100'])
        self.assertIsNone(values['energy_kcal_per_100'])
        self.assertEqual(values['sugars_g_per_100'], 100.0)
        self.assertEqual(sorted(implausible), ['energy-kcal', 'proteins', 'salt'])


class ScoreChecks(unittest.TestCase):
    def test_fixed_context_and_unknown_status(self):
        score = environmental_score(raw_row()['environmental_score_data'])
        self.assertEqual((score['environmental_score'], score['environmental_score_world'],
                          score['environmental_grade'], score['agribalyse_version'],
                          score['environmental_missing_key_data']), (70.0, 65.0, 'b', '3.2', True))
        unknown = environmental_score(json.dumps({'status': 'unknown', 'grade': 'd'}))
        self.assertIsNone(unknown['environmental_score'])
        self.assertIsNone(unknown['environmental_grade'])
        self.assertIsNone(environmental_score(None)['environmental_score'])


class RecordChecks(unittest.TestCase):
    def test_complete_record_is_eligible_with_cleaned_text(self):
        record = finalize([build_record(raw_row())], min_eligible=1)[0]
        self.assertTrue(record['eligible'])
        self.assertEqual(record['exclusion_reasons'], [])
        self.assertEqual(record['ingredients_text'], 'Lait entier, ferments')
        self.assertEqual(record['comparison_unit'], 'g')
        self.assertEqual(record['product_quantity'], 500.0)
        self.assertEqual(record['family'], 'yogurts')
        self.assertEqual(record['environmental_score_context'], 'fr')
        self.assertEqual((record['group_id'], record['group_size']), (1, 1))
        self.assertEqual(len(json.loads(record['names_json'])), 2)

    def test_every_missing_piece_is_an_explicit_reason(self):
        record = build_record(raw_row(
            product_name=[], ingredients_text=None, product_quantity_unit=None,
            nutriments=[{'name': 'salt', '100g': 500}], environmental_score_data=None,
            categories_tags=['en:cheeses']))
        self.assertEqual(record['exclusion_reasons'], [
            'missing_name', 'missing_ingredients', 'unknown_comparison_unit',
            'missing_nutrient:proteins', 'missing_nutrient:sugars', 'implausible_nutrient:salt',
            'missing_environmental_score', 'not_in_selected_family'])
        self.assertIsNone(record['salt_g_per_100'])
        self.assertIsNone(record['family'])
        self.assertEqual(record['group_key'], 'code:1')

    def test_unit_is_not_inferred_from_nutrition_data_per(self):
        record = build_record(raw_row(product_quantity_unit=None, nutrition_data_per='100g'))
        self.assertIsNone(record['comparison_unit'])
        self.assertIn('unknown_comparison_unit', record['exclusion_reasons'])
        volume = build_record(raw_row(product_quantity_unit='ml'))
        self.assertEqual(volume['comparison_unit'], 'ml')
        self.assertIsNone(build_record(raw_row(product_quantity_unit='oz'))['comparison_unit'])

    def test_family_assignment_and_minimum(self):
        self.assertEqual(assign_family(['en:milk-substitutes']), 'plant_based_milk_alternatives')
        self.assertEqual(assign_family(['en:breakfast-cereals', 'en:cereals']), 'breakfast_cereals')
        self.assertIsNone(assign_family(['en:cheeses']))
        self.assertIsNone(assign_family(None))
        records = finalize([build_record(raw_row(code=str(i))) for i in range(3)], min_eligible=5)
        self.assertTrue(all(r['exclusion_reasons'] == ['family_below_minimum'] for r in records))
        self.assertFalse(any(r['eligible'] for r in records))
        self.assertEqual({r['group_id'] for r in records}, {1})
        self.assertEqual(records[0]['group_size'], 3)

    def test_variants_share_group_regardless_of_quantity_and_accents(self):
        records = finalize([
            build_record(raw_row(code='a', brands='Invitation à la Ferme', product_quantity='500')),
            build_record(raw_row(code='b', brands='Invitation a la ferme', product_quantity='1000')),
            build_record(raw_row(code='c', brands='Other')),
        ], min_eligible=1)
        self.assertEqual(records[0]['group_id'], records[1]['group_id'])
        self.assertNotEqual(records[0]['group_id'], records[2]['group_id'])


class CommittedOutputChecks(unittest.TestCase):
    def test_manifest_matches_raw_source_and_selected_families(self):
        manifest = json.loads((ROOT / 'data/catalog_parquet_manifest.json').read_text())
        raw = json.loads((ROOT / 'data/catalog_manifest.json').read_text())
        report = json.loads((ROOT / 'data/catalog_report.json').read_text())
        self.assertEqual(manifest['source_sha256'], raw['sha256'])
        self.assertEqual(manifest['selected_families'], {k: list(v) for k, v in FAMILIES.items()})
        self.assertEqual(manifest['eligible'], report['eligible'])
        self.assertEqual(sum(report['eligible_by_family'].values()), report['eligible'])
        for family, summary in report['selected_families'].items():
            self.assertGreaterEqual(summary['eligible_members'], report['min_eligible_per_family'], family)


if __name__ == '__main__':
    unittest.main()
