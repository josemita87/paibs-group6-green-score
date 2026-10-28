"""Regression checks for raw acquisition and coverage semantics."""
import hashlib
import unittest

from scripts.audit_data import nutrients_100g, present, verify
from scripts.fetch_data import cache_namespace, encode_rows


class DataChecks(unittest.TestCase):
    def test_cache_is_scoped_to_revision_and_fields(self):
        original = cache_namespace('revision-a', ['code'])
        self.assertNotEqual(original, cache_namespace('revision-b', ['code']))
        self.assertNotEqual(original, cache_namespace('revision-a', ['code', 'nutriments']))

    def test_missing_nutrients_are_not_zero(self):
        row = {'nutriments': [
            {'name': 'sugars', '100g': 0},
            {'name': 'salt', '100g': None, 'serving': 1},
            {'name': 'proteins', '100g': -1},
        ]}
        self.assertEqual(nutrients_100g(row), {'sugars'})
        self.assertEqual(nutrients_100g({'nutriments': None}), set())
        self.assertTrue(present(0))
        self.assertFalse(present(None))

    def test_nonfinite_and_boolean_nutrients_are_excluded(self):
        row = {'nutriments': [{'name': name, '100g': value} for name, value in
                              zip(('proteins', 'salt', 'sugars'), (float('inf'), float('nan'), True))]}
        self.assertEqual(nutrients_100g(row), set())

    def test_verify_detects_corruption_missing_fields_and_duplicate_rows(self):
        rows = [{'code': '0001', '_source_row': 9}]
        raw = encode_rows(rows)
        manifest = {'sha256': hashlib.sha256(raw).hexdigest(),
                    'sample_rows': 1, 'selected_fields': ['code']}
        self.assertEqual(verify(raw, manifest), rows)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify(raw + b' ', manifest)
        with self.assertRaisesRegex(ValueError, 'count'):
            verify(raw, {**manifest, 'sample_rows': 2})
        with self.assertRaisesRegex(ValueError, 'fields'):
            verify(raw, {**manifest, 'selected_fields': ['code', 'nutriments']})
        duplicate = encode_rows(rows * 2)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            verify(duplicate, {**manifest, 'sha256': hashlib.sha256(duplicate).hexdigest(),
                               'sample_rows': 2})


if __name__ == '__main__':
    unittest.main()
