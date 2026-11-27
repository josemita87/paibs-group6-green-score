"""Check the untrained baselines and the committed baseline report."""
from collections import Counter
import json
from statistics import mean
import unittest

import pyarrow.parquet as pq

from basket.baselines import (
    BASELINES, Baselines, category_rules, cosine, document_frequencies, ngrams,
    nutrient_distance, percentile, product_text, random_control, rank_of, roc_auc, tfidf_vector,
)
from scripts.build_catalog import MANIFEST, PARQUET
from scripts.build_pairs import OUTPUT as PAIRS, PARTITIONS
from scripts.run_baselines import OUTPUT, SEED, TOP_K, build_report, pilot_pairs


def product(code, group_id, name, family='yogurts', unit='g', proteins=4.0, sugars=5.0, salt=0.1):
    return {'code': code, 'group_id': group_id, 'name': name, 'brands': 'Brand A', 'lang': 'en',
            'ingredients_text': 'milk, ferments', 'family': family, 'comparison_unit': unit,
            'proteins_g_per_100': proteins, 'sugars_g_per_100': sugars, 'salt_g_per_100': salt,
            'eligible': True}


class TextBaselineChecks(unittest.TestCase):
    def test_ngrams_pad_the_text_and_keep_short_strings_whole(self):
        self.assertEqual(sum(ngrams('abcdef').values()), 5)
        self.assertEqual(list(ngrams('ab')), [' ab '])
        self.assertEqual(ngrams(''), Counter())

    def test_product_text_joins_the_normalized_name_and_ingredients(self):
        self.assertEqual(product_text({'name': 'Yaourt Nature!', 'ingredients_text': 'Lait'}),
                         'yaourt nature lait')
        self.assertEqual(product_text({'name': None, 'ingredients_text': None}), '')

    def test_identical_text_scores_one_and_unrelated_text_scores_near_zero(self):
        frequencies, documents = document_frequencies(['plain yogurt', 'crunchy oat cereal'])
        vectors = [tfidf_vector(text, frequencies, documents)
                   for text in ('plain yogurt', 'plain yogurt', 'crunchy oat cereal')]
        self.assertAlmostEqual(cosine(vectors[0], vectors[1]), 1.0)
        self.assertLess(cosine(vectors[0], vectors[2]), 0.1)

    def test_a_text_outside_the_fit_corpus_still_gets_a_unit_vector(self):
        frequencies, documents = document_frequencies(['plain yogurt'])
        vector = tfidf_vector('unseen drink', frequencies, documents)
        self.assertAlmostEqual(cosine(vector, vector), 1.0)
        self.assertEqual(tfidf_vector('', {}, 0), {})


class RuleBaselineChecks(unittest.TestCase):
    def test_another_family_or_comparison_unit_scores_zero(self):
        original = product('1', 1, 'Plain yogurt')
        self.assertEqual(category_rules(original, product('2', 2, 'Oat cereal', family='breakfast_cereals')), 0.0)
        self.assertEqual(category_rules(original, product('3', 3, 'Soy drink', unit='ml')), 0.0)

    def test_equal_nutrients_score_one_and_distance_is_capped(self):
        original = product('1', 1, 'Plain yogurt')
        self.assertEqual(category_rules(original, product('2', 2, 'Other plain yogurt')), 1.0)
        far = product('3', 3, 'Sugar bomb', proteins=0.0, sugars=90.0, salt=5.0)
        self.assertGreater(nutrient_distance(original, far), 0.95)
        opposite = product('4', 4, 'Impossible', proteins=-4.0, sugars=-5.0, salt=-0.1)
        self.assertEqual(nutrient_distance(original, opposite), 1.0)

    def test_a_missing_nutrient_counts_as_the_largest_distance(self):
        original = product('1', 1, 'Plain yogurt')
        self.assertAlmostEqual(nutrient_distance(original, product('2', 2, 'No salt', salt=None)),
                               1 / 3)

    def test_the_random_control_is_seeded_and_bounded(self):
        first, second = product('1', 1, 'A'), product('2', 2, 'B')
        value = random_control(first, second, SEED)
        self.assertEqual(value, random_control(first, second, SEED))
        self.assertNotEqual(value, random_control(first, second, 'other seed'))
        self.assertTrue(0.0 <= value < 1.0)


class RankingChecks(unittest.TestCase):
    def test_ranking_orders_by_score_and_breaks_ties_by_barcode(self):
        products = {1: product('300', 1, 'Plain yogurt'), 2: product('100', 2, 'Plain yogurt'),
                    3: product('200', 3, 'Strawberry yogurt', sugars=20.0)}
        baselines = Baselines(products, [1, 2, 3], SEED)
        ranking = baselines.rank('category_rules', 1, [2, 3])
        self.assertEqual([group for group, _ in ranking], [2, 3])
        self.assertEqual(rank_of(ranking, 3), 2)
        self.assertEqual(baselines.score('tfidf_char', 1, 2), 1.0)

    def test_percentile_is_one_at_the_top_and_zero_at_the_bottom(self):
        self.assertEqual(percentile(1, 10), 1.0)
        self.assertEqual(percentile(10, 10), 0.0)
        self.assertEqual(percentile(1, 1), 1.0)

    def test_auc_counts_ties_as_half(self):
        self.assertEqual(roc_auc([1.0], [0.0]), 1.0)
        self.assertEqual(roc_auc([0.0], [0.0]), 0.5)
        self.assertEqual(roc_auc([0.0], [1.0]), 0.0)


class CommittedReportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = pq.read_table(PARQUET).to_pylist()
        cls.digest = json.loads(MANIFEST.read_text())['content_sha256']
        cls.partitions = json.loads(PARTITIONS.read_text())
        cls.pairs = json.loads(PAIRS.read_text())
        cls.report = json.loads(OUTPUT.read_text())
        cls.unit_of = {group: unit['unit_id'] for unit in cls.partitions['units']
                       for group in unit['group_ids']}
        cls.partition_of = {group: unit['partition'] for unit in cls.partitions['units']
                            for group in unit['group_ids']}

    def test_rebuild_is_reproducible_independent_of_row_order(self):
        self.assertEqual(build_report(self.rows[::-1], self.digest, self.pairs, self.partitions),
                         self.report)

    def test_every_sampled_and_pilot_pair_is_ranked_once(self):
        ranked = [row['pair_id'] for row in self.report['rankings']]
        expected = ([task['data']['pair_id'] for task in self.pairs['tasks']]
                    + [data['pair_id'] for data, _ in pilot_pairs()])
        self.assertEqual(sorted(ranked), sorted(expected))
        self.assertEqual(len(ranked), self.report['pairs_ranked'])

    def test_each_rank_sits_inside_its_pool(self):
        for row in self.report['rankings']:
            for baseline in BASELINES:
                self.assertGreaterEqual(row[baseline]['rank'], 1)
                self.assertLessEqual(row[baseline]['rank'], row['pool'])
                self.assertTrue(0.0 <= row[baseline]['percentile'] <= 1.0)

    def test_the_pool_holds_one_family_and_partition_and_omits_the_own_unit(self):
        tasks = {task['data']['pair_id']: task['data'] for task in self.pairs['tasks']}
        for row in self.report['rankings']:
            if row['partition'] == 'calibration':
                continue
            data = tasks[row['pair_id']]
            available = [group for group, partition in self.partition_of.items()
                         if partition == row['partition']
                         and self.unit_of[group] != self.unit_of[data['original_group_id']]]
            families = {r['group_id']: r['family'] for r in self.rows if r['eligible']}
            self.assertEqual(row['pool'], sum(families[group] == row['family']
                                              for group in available))

    def test_text_similarity_separates_lookalike_pairs_from_unrelated_ones(self):
        by_strategy = self.report['by_strategy']
        self.assertGreater(by_strategy['lookalike']['tfidf_char']['mean_percentile'],
                           by_strategy['family_random']['tfidf_char']['mean_percentile'])
        self.assertGreater(by_strategy['all']['tfidf_char']['mean_percentile'],
                           by_strategy['all']['random_control']['mean_percentile'])

    def test_the_random_control_stays_near_the_middle_of_its_pool(self):
        percentiles = [row['random_control']['percentile'] for row in self.report['rankings']]
        self.assertAlmostEqual(mean(percentiles), 0.5, delta=0.1)

    def test_the_label_section_names_its_source_and_counts_every_pilot_pair(self):
        labels = self.report['pilot_labels']
        self.assertIn('model-drafted', labels['label_source'])
        self.assertEqual(sum(labels['counts'].values()), len(pilot_pairs()))
        for baseline in BASELINES:
            self.assertEqual(set(labels[baseline]) - {'auc_acceptable_over_unacceptable'},
                             set(labels['counts']))

    def test_the_report_names_the_inputs_it_was_built_from(self):
        self.assertEqual(self.report['catalog_content_sha256'], self.digest)
        self.assertEqual(self.report['pairs_version'], self.pairs['version'])
        self.assertEqual(self.report['partitions_version'], self.partitions['version'])
        self.assertFalse(self.report['parameters']['trained_on_labels'])
        self.assertEqual(self.report['parameters']['top_k'], TOP_K)
        self.assertNotIn('not_implemented', self.report)


if __name__ == '__main__':
    unittest.main()
