"""Check exact embedding comparison, the stored embeddings and their use as a baseline.

None of these checks loads the encoder; they read the committed vectors only.
"""
import hashlib
import json
import unittest

import numpy as np
import pyarrow.parquet as pq

from basket.baselines import BASELINES, Baselines
from basket.embeddings import SCALE, StoredEmbeddings, encoder_text, quantize, texts_sha256
from basket.pairs import representatives
from scripts.build_catalog import MANIFEST as CATALOG_MANIFEST, PARQUET
from scripts.encode_frozen import MANIFEST, MODEL, OUTPUT, REVISION, load_embeddings
from scripts.run_baselines import INFORMATIVE, OUTPUT as REPORT, SEED


def product(code, name, ingredients='milk'):
    return {'code': code, 'name': name, 'ingredients_text': ingredients}


class ExactComparisonChecks(unittest.TestCase):
    def setUp(self):
        self.products = {7: product('300', 'A'), 8: product('100', 'B'), 9: product('200', 'C')}
        # Row order follows the barcode: group 8, then 9, then 7.
        self.matrix = quantize([[3.0, 4.0, 0.0], [0.0, 0.0, 2.0], [6.0, 8.0, 0.0]])

    def test_quantized_vectors_are_unit_length_int16(self):
        self.assertEqual(self.matrix.dtype, np.int16)
        self.assertEqual(self.matrix[1].tolist(), [0, 0, SCALE])
        self.assertEqual(self.matrix[0].tolist(), [round(0.6 * SCALE), round(0.8 * SCALE), 0])
        with self.assertRaises(ValueError):
            quantize([[0.0, 0.0, 0.0]])

    def test_cosine_follows_the_barcode_row_order(self):
        stored = StoredEmbeddings(self.products, self.matrix)
        self.assertEqual(stored.row_of, {8: 0, 9: 1, 7: 2})
        self.assertAlmostEqual(stored.cosine(8, 7), 1.0, places=12)      # same direction
        self.assertEqual(stored.cosine(8, 9), 0.0)      # orthogonal
        self.assertEqual(stored.cosine(8, 9), stored.cosine(9, 8))
        opposite = StoredEmbeddings(self.products, quantize([[1.0, 0, 0], [0, 1.0, 0], [-1.0, 0, 0]]))
        self.assertAlmostEqual(opposite.cosine(8, 7), -1.0, places=12)

    def test_wrong_shape_or_type_is_rejected(self):
        with self.assertRaises(ValueError):
            StoredEmbeddings(self.products, self.matrix[:2])
        with self.assertRaises(ValueError):
            StoredEmbeddings(self.products, self.matrix.astype(np.float32))

    def test_text_and_fingerprint_depend_on_name_ingredients_and_barcode(self):
        self.assertEqual(encoder_text(product('1', 'Soy drink', 'water, soy')), 'Soy drink. water, soy')
        self.assertEqual(encoder_text(product('1', None, None)), '.')
        changed = {**self.products, 9: product('200', 'C', 'oats')}
        self.assertNotEqual(texts_sha256(self.products), texts_sha256(changed))
        self.assertEqual(texts_sha256(self.products),
                         texts_sha256(dict(reversed(list(self.products.items())))))

    def test_the_baseline_needs_embeddings_and_rejects_unknown_names(self):
        rows = {group_id: dict(row, brands='', lang='en', family='yogurts', comparison_unit='g',
                               proteins_g_per_100=1.0, sugars_g_per_100=1.0, salt_g_per_100=0.1)
                for group_id, row in self.products.items()}
        with self.assertRaisesRegex(ValueError, 'stored embeddings'):
            Baselines(rows, rows, SEED).score('frozen_encoder', 7, 8)
        baselines = Baselines(rows, rows, SEED, StoredEmbeddings(rows, self.matrix))
        self.assertEqual([group for group, _ in baselines.rank('frozen_encoder', 8, [9, 7])], [7, 9])
        with self.assertRaisesRegex(ValueError, 'Unknown baseline'):
            baselines.score('fine_tuned', 7, 8)


class StoredEmbeddingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = pq.read_table(PARQUET).to_pylist()
        cls.digest = json.loads(CATALOG_MANIFEST.read_text())['content_sha256']
        cls.products = representatives(cls.rows)
        cls.manifest = json.loads(MANIFEST.read_text())
        cls.matrix = np.load(OUTPUT, allow_pickle=False)
        cls.report = json.loads(REPORT.read_text())

    def test_file_matches_its_manifest_and_the_pinned_model(self):
        self.assertEqual(hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                         self.manifest['file_sha256'])
        self.assertEqual((self.manifest['model'], self.manifest['model_revision']),
                         (MODEL, REVISION))
        self.assertFalse(self.manifest['weights_updated'])
        self.assertEqual(self.matrix.shape, (self.manifest['rows'], self.manifest['dimension']))
        self.assertEqual(self.matrix.dtype, np.int16)

    def test_one_unit_vector_per_eligible_group_from_the_current_texts(self):
        eligible = {row['group_id'] for row in self.rows if row['eligible']}
        self.assertEqual(self.matrix.shape[0], len(eligible))
        self.assertEqual(self.manifest['catalog_content_sha256'], self.digest)
        self.assertEqual(self.manifest['texts_sha256'], texts_sha256(self.products))
        lengths = np.linalg.norm(self.matrix.astype(np.float64), axis=1) / SCALE
        self.assertTrue(np.allclose(lengths, 1.0, atol=1e-3))

    def test_a_changed_text_is_refused(self):
        group_id = next(iter(self.products))
        changed = dict(self.products)
        changed[group_id] = dict(changed[group_id], name='Another product')
        with self.assertRaisesRegex(SystemExit, 'different catalog texts'):
            load_embeddings(changed, self.digest)
        with self.assertRaisesRegex(SystemExit, 'different catalog texts'):
            load_embeddings(self.products, 'another catalog')

    def test_the_report_ranks_every_pair_with_the_stored_vectors(self):
        stored = load_embeddings(self.products, self.digest)
        self.assertEqual(self.report['frozen_encoder']['embeddings_sha256'],
                         self.manifest['file_sha256'])
        self.assertEqual(self.report['frozen_encoder']['model_revision'], REVISION)
        self.assertIn('frozen_encoder', BASELINES)
        by_id = {}
        for task in json.loads((REPORT.parent / 'pairs.json').read_text())['tasks']:
            by_id[task['data']['pair_id']] = task['data']
        checked = 0
        for row in self.report['rankings']:
            self.assertTrue(-1.0 <= row['frozen_encoder']['score'] <= 1.0)
            if row['pair_id'] in by_id:
                data = by_id[row['pair_id']]
                self.assertEqual(row['frozen_encoder']['score'], round(stored.cosine(
                    data['original_group_id'], data['candidate_group_id']), 6))
                self.assertEqual(row['languages'], 'same' if data['original_lang']
                                 == data['candidate_lang'] else 'different')
                checked += 1
        self.assertEqual(checked, 300)

    def test_summaries_cover_the_language_split_and_every_baseline_pair(self):
        languages = self.report['by_languages']
        self.assertEqual(languages['same']['pairs'] + languages['different']['pairs'],
                         languages['all']['pairs'])
        agreement = self.report['top_10_agreement']
        self.assertEqual(len(INFORMATIVE), 3)
        self.assertEqual(len([key for key in agreement if '|' in key]), 3)
        strategies = self.report['by_strategy']
        self.assertGreater(strategies['lookalike']['frozen_encoder']['mean_percentile'],
                           strategies['family_random']['frozen_encoder']['mean_percentile'])


if __name__ == '__main__':
    unittest.main()
