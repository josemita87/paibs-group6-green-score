"""Checks for basket input definition and validation (pipeline step 1)."""
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from basket.catalog import Catalog, main_name, product_ref
from basket.models import (
    Basket, BasketInputError, BasketItem, ItemRequest, NutritionalConstraints, Preferences,
    ProductRef, Unit, build_basket, to_canonical,
)

APP_PATH = Path(__file__).resolve().parents[1] / 'app/streamlit_app.py'
KNOWN_MASS_CODE = '0083791520018'      # recorded in g with raw nutrients and score
KNOWN_VOLUME_CODE = '0083741150012'    # recorded in ml
KNOWN_UNITLESS_CODE = '0083737157124'  # no product_quantity_unit in the source


def ref(code='1', catalog_unit=None, **overrides) -> ProductRef:
    fields = dict(code=code, name=f'Product {code}', brands=None, catalog_unit=catalog_unit,
                  nutrient_100g_available={'proteins': False, 'sugars': False, 'salt': False},
                  environmental_score_available=False)
    return ProductRef(**{**fields, **overrides})


class FakeCatalog:
    revision = 'test-revision'
    sha256 = 'test-sha256'

    def __init__(self, *products):
        self._products = {product.code: product for product in products}

    def get(self, code):
        return self._products.get(code)


class UnitChecks(unittest.TestCase):
    def test_only_exact_decimal_multiples_of_catalog_units(self):
        self.assertEqual(to_canonical(1.5, Unit.KILOGRAM), (1500.0, 'g'))
        self.assertEqual(to_canonical(0.33, Unit.LITRE), (330.0, 'ml'))
        self.assertEqual(to_canonical(250, Unit.GRAM), (250, 'g'))
        self.assertEqual({u.value for u in Unit}, {'g', 'kg', 'ml', 'l'})
        with self.assertRaises(ValueError):
            Unit('oz')


class BasketItemChecks(unittest.TestCase):
    def test_quantity_must_be_positive_and_finite(self):
        for quantity in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValidationError):
                BasketItem(product=ref(), quantity=quantity, unit=Unit.GRAM)
        item = BasketItem(product=ref(), quantity=0.5, unit=Unit.KILOGRAM)
        self.assertEqual((item.canonical_quantity, item.canonical_unit), (500.0, 'g'))

    def test_unit_compatibility_is_checked_only_against_recorded_basis(self):
        with self.assertRaisesRegex(ValidationError, 'recorded in g'):
            BasketItem(product=ref(catalog_unit='g'), quantity=1, unit=Unit.LITRE)
        with self.assertRaisesRegex(ValidationError, 'recorded in ml'):
            BasketItem(product=ref(catalog_unit='ml'), quantity=1, unit=Unit.GRAM)
        verified = BasketItem(product=ref(catalog_unit='ml'), quantity=1, unit=Unit.LITRE)
        self.assertEqual(verified.unit_basis, 'verified')
        unknown = BasketItem(product=ref(catalog_unit=None), quantity=1, unit=Unit.LITRE)
        self.assertEqual(unknown.unit_basis, 'unverified')
        self.assertIsNone(unknown.product.catalog_unit)

    def test_locked_default_and_frozen(self):
        item = BasketItem(product=ref(), quantity=1, unit=Unit.GRAM)
        self.assertFalse(item.locked)
        with self.assertRaises(ValidationError):
            item.locked = True


class BasketChecks(unittest.TestCase):
    def test_build_reports_every_problem_with_item_index(self):
        catalog = FakeCatalog(ref('1', 'g'))
        requests = [ItemRequest(code='1', quantity=0, unit=Unit.GRAM),
                    ItemRequest(code='missing', quantity=1, unit=Unit.GRAM),
                    ItemRequest(code='1', quantity=100, unit=Unit.MILLILITRE)]
        with self.assertRaises(BasketInputError) as context:
            build_basket(catalog, requests, max_substitutions=1)
        errors = context.exception.errors
        self.assertEqual(len(errors), 3)
        self.assertIn("item 1: quantity: Input should be greater than 0", errors)
        self.assertIn("item 2: unknown barcode 'missing' in the pinned catalog", errors)
        self.assertRegex(errors[2], r'^item 3: .*recorded in g')

    def test_basket_level_rules(self):
        catalog = FakeCatalog(ref('1'), ref('2'))
        valid = [ItemRequest(code='1', quantity=1, unit=Unit.GRAM, locked=True),
                 ItemRequest(code='2', quantity=1, unit=Unit.GRAM)]
        with self.assertRaisesRegex(BasketInputError, 'at least 1 item'):
            build_basket(catalog, [], max_substitutions=1)
        with self.assertRaisesRegex(BasketInputError, 'max_substitutions'):
            build_basket(catalog, valid, max_substitutions=-1)
        with self.assertRaisesRegex(BasketInputError, 'duplicated: 1'):
            build_basket(catalog, valid + valid[:1], max_substitutions=1)
        basket = build_basket(catalog, valid, max_substitutions=5)
        self.assertEqual(basket.substitutable_positions, 1)
        self.assertEqual(basket.effective_max_substitutions, 1)
        self.assertEqual(basket.max_substitutions, 5)
        self.assertEqual(basket.catalog_revision, 'test-revision')

    def test_preferences_and_constraints_are_declared_not_checked(self):
        with self.assertRaises(ValidationError):
            Preferences(dietary=['vegan', 'vegan'])
        with self.assertRaises(ValidationError):
            Preferences(dietary=['keto'])
        with self.assertRaises(ValidationError):
            NutritionalConstraints(max_total_salt_g=-1)
        constraints = NutritionalConstraints(min_total_proteins_g=30)
        self.assertEqual(constraints.declared(), {'min_total_proteins_g': 30})
        self.assertEqual(constraints.enforcement, 'declared_not_checked')
        self.assertEqual(Preferences(dietary=['vegan']).enforcement, 'declared_not_checked')

    def test_serialized_basket_round_trips(self):
        catalog = FakeCatalog(ref('1', 'ml'))
        basket = build_basket(catalog, [ItemRequest(code='1', quantity=1, unit=Unit.LITRE)], 2,
                              Preferences(dietary=['vegan']),
                              NutritionalConstraints(max_total_sugars_g=50))
        payload = json.loads(basket.model_dump_json())
        self.assertEqual(payload['items'][0]['canonical_quantity'], 1000.0)
        self.assertEqual(payload['items'][0]['unit_basis'], 'verified')
        self.assertEqual(payload['constraints']['enforcement'], 'declared_not_checked')
        self.assertEqual(Basket.model_validate(payload), basket)


class CatalogChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog.load()

    def test_loads_verified_snapshot(self):
        self.assertEqual(len(self.catalog), 12288)
        self.assertEqual(self.catalog.revision, '89cfb571db20b1f1b246f27cab71837fc96225b1')

    def test_barcode_lookup_reports_raw_evidence_without_inference(self):
        mass = self.catalog.get(f' {KNOWN_MASS_CODE} ')
        self.assertEqual((mass.catalog_unit, mass.environmental_score_available), ('g', True))
        self.assertTrue(all(mass.nutrient_100g_available.values()))
        self.assertEqual(self.catalog.get(KNOWN_VOLUME_CODE).catalog_unit, 'ml')
        unitless = self.catalog.get(KNOWN_UNITLESS_CODE)
        self.assertIsNone(unitless.catalog_unit)
        self.assertFalse(unitless.environmental_score_available)
        self.assertIsNone(self.catalog.get('0000000000000'))
        self.assertIsNone(self.catalog.get(''))

    def test_search_matches_names_brands_and_codes(self):
        results = self.catalog.search('yogurt', limit=5)
        self.assertEqual(len(results), 5)
        self.assertTrue(all('yogurt' in (r.name or '').lower() or 'yogurt' in (r.brands or '').lower()
                            for r in results))
        self.assertEqual([r.code for r in self.catalog.search(KNOWN_MASS_CODE)][:1], [KNOWN_MASS_CODE])
        self.assertEqual(self.catalog.search('   '), [])
        self.assertEqual(self.catalog.search('zzzz-no-such-product'), [])

    def test_name_helpers_keep_source_text(self):
        row = {'code': '9', 'product_name': [{'lang': 'fr', 'text': 'Yaourt'}, {'lang': 'main', 'text': 'Yogurt'}],
               'product_quantity_unit': 'oz', 'nutriments': None}
        self.assertEqual(main_name(row), 'Yogurt')
        self.assertIsNone(main_name({'product_name': []}))
        unsupported = product_ref(row)
        self.assertIsNone(unsupported.catalog_unit)
        self.assertEqual(unsupported.nutrient_100g_available,
                         {'proteins': False, 'sugars': False, 'salt': False})

    def test_real_basket_build(self):
        requests = [ItemRequest(code=KNOWN_MASS_CODE, quantity=0.2, unit=Unit.KILOGRAM),
                    ItemRequest(code=KNOWN_VOLUME_CODE, quantity=500, unit=Unit.MILLILITRE, locked=True),
                    ItemRequest(code=KNOWN_UNITLESS_CODE, quantity=250, unit=Unit.GRAM)]
        basket = build_basket(self.catalog, requests, max_substitutions=3)
        self.assertEqual([item.unit_basis for item in basket.items],
                         ['verified', 'verified', 'unverified'])
        self.assertEqual(basket.effective_max_substitutions, 2)
        self.assertEqual(basket.catalog_sha256, self.catalog.sha256)


class StreamlitFlowChecks(unittest.TestCase):
    """Headless run of the Streamlit input screen."""

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:  # pragma: no cover - streamlit is an app dependency
            raise unittest.SkipTest('streamlit not installed')
        cls.AppTest = AppTest

    def start(self):
        app = self.AppTest.from_file(str(APP_PATH), default_timeout=60)
        app.run()
        self.assertFalse(app.exception)
        app.radio[0].set_value('Enter barcode').run()
        return app

    def test_unknown_barcode_is_reported(self):
        app = self.start()
        app.text_input(key='barcode').input('0000000000000').run()
        self.assertTrue(any('Unknown barcode' in e.value for e in app.error))
        self.assertEqual(app.session_state['entries'], [])

    def test_invalid_quantity_and_incompatible_unit_are_rejected(self):
        app = self.start()
        app.text_input(key='barcode').input(KNOWN_MASS_CODE).run()
        app.number_input[0].set_value(0.0)
        app.button[0].click().run()
        self.assertTrue(any('greater than 0' in e.value for e in app.error))
        app.number_input[0].set_value(100.0)
        app.selectbox[0].select('ml')
        app.button[0].click().run()
        self.assertTrue(any('recorded in g' in e.value for e in app.error))
        self.assertEqual(app.session_state['entries'], [])

    def test_valid_item_builds_structured_basket(self):
        app = self.start()
        app.text_input(key='barcode').input(KNOWN_UNITLESS_CODE).run()
        app.number_input[0].set_value(250.0)
        app.button[0].click().run()
        self.assertEqual(len(app.session_state['entries']), 1)
        build = next(b for b in app.button if b.label == 'Build basket')
        build.click().run()
        self.assertTrue(any('Basket is valid' in s.value for s in app.success))
        self.assertTrue(any('could not be verified' in w.value for w in app.warning))
        payloads = [json.loads(j.value) for j in app.json]
        payload = next(p for p in payloads if isinstance(p, dict) and 'schema_version' in p)
        self.assertEqual(payload['items'][0]['product']['code'], KNOWN_UNITLESS_CODE)
        self.assertEqual(payload['items'][0]['unit_basis'], 'unverified')
        self.assertEqual(payload['constraints']['enforcement'], 'declared_not_checked')


if __name__ == '__main__':
    unittest.main()
