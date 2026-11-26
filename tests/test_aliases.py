"""Check alias linking rules on synthetic groups and the committed report."""
import json
import unittest

import pyarrow.parquet as pq

from scripts.inspect_aliases import (
    MANIFEST, MERGE_SIGNALS, OUTPUT, PARQUET, PILOT, brand_tokens, build_report, find_links,
    group_profiles, merge_clusters,
)

LONG = 'lait entier pasteurise, sucre 8 %, ferments lactiques, arome naturel'


def row(group_id, name, brands, ingredients='court', family='yogurts', eligible=True):
    return {'code': f'{group_id:04d}', 'group_id': group_id, 'eligible': eligible,
            'family': family, 'name': name, 'brands': brands, 'ingredients_text': ingredients}


def links_for(rows):
    return find_links(group_profiles(rows))


class LinkChecks(unittest.TestCase):
    def test_brand_strings_split_into_normalized_tokens(self):
        self.assertEqual(brand_tokens('Danone, Danonino'), {'danone', 'danonino'})
        self.assertEqual(brand_tokens('Nestlé,NESTLE'), {'nestle'})
        self.assertEqual(brand_tokens(None), set())

    def test_same_name_links_only_with_a_shared_brand(self):
        links, other_brand, _ = links_for([
            row(1, 'Danonino', 'Danone'), row(2, 'Danonino', 'Danone, Danonino'),
            row(3, 'Lait de coco', 'Aroy-D'), row(4, 'Lait de coco', 'Suree'),
            row(5, 'Lait de coco', None)])
        self.assertEqual(links, {(1, 2): {'same_name_shared_brand'}})
        self.assertEqual(other_brand, 3)

    def test_identical_ingredients_merge_with_shared_brand_and_go_to_review_otherwise(self):
        links, _, _ = links_for([
            row(1, 'Vanille', 'Nestlé', LONG), row(2, 'Dessert lacté', 'Nestlé, La Laitière', LONG),
            row(3, 'Autre marque', 'Vrai', LONG),
            row(4, 'Nature', 'Malo', 'lait, ferments'), row(5, 'Brassé', 'Malo', 'lait, ferments')])
        self.assertEqual(links, {(1, 2): {'same_ingredients_shared_brand'},
                                 (1, 3): {'same_ingredients_other_brand'},
                                 (2, 3): {'same_ingredients_other_brand'}})
        self.assertEqual(merge_clusters(links), [[1, 2]])

    def test_similar_names_need_a_shared_brand_and_the_threshold(self):
        links, _, histogram = links_for([
            row(1, 'Yaourt entier saveur citron', 'Malo'),
            row(2, 'Yaourt entier saveur citron bio', 'Malo'),     # 4 of 5 tokens
            row(3, 'Yaourt entier saveur coco', 'Malo'),           # 3 of 5 with group 1
            row(4, 'Yaourt entier saveur citron bio', 'Vrai')])
        self.assertEqual(links, {(1, 2): {'similar_name_shared_brand'}})
        self.assertEqual(histogram, {'0.5': 1, '0.6': 1, '0.8': 1})

    def test_links_stay_within_a_family_and_ignore_ineligible_rows(self):
        links, other_brand, _ = links_for([
            row(1, 'Avoine', 'Bjorg', LONG), row(2, 'Avoine', 'Bjorg', LONG, family='breakfast_cereals'),
            row(3, 'Avoine', 'Bjorg', LONG, eligible=False)])
        self.assertEqual((links, other_brand), ({}, 0))

    def test_clusters_are_transitive_over_merge_signals_only(self):
        clusters = merge_clusters({(1, 2): {'same_name_shared_brand'},
                                   (2, 3): {'similar_name_shared_brand'},
                                   (3, 4): {'same_ingredients_other_brand'},
                                   (5, 6): {'same_ingredients_shared_brand'}})
        self.assertEqual(clusters, [[1, 2, 3], [5, 6]])


class ReportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = pq.read_table(PARQUET).to_pylist()
        cls.digest = json.loads(MANIFEST.read_text())['content_sha256']
        cls.tasks = json.loads(PILOT.read_text())
        cls.report = json.loads(OUTPUT.read_text())

    def test_rebuild_is_reproducible_independent_of_row_order(self):
        self.assertEqual(build_report(self.rows[::-1], self.digest, self.tasks), self.report)

    def test_clusters_are_disjoint_single_family_and_counts_add_up(self):
        eligible = {r['group_id']: r['family'] for r in self.rows if r['eligible']}
        seen, units = set(), len(eligible)
        for cluster in self.report['alias_clusters']:
            ids = [product['group_id'] for product in cluster['products']]
            self.assertGreater(len(ids), 1)
            self.assertFalse(seen & set(ids))
            seen.update(ids)
            self.assertEqual({eligible[group_id] for group_id in ids}, {cluster['family']})
            self.assertTrue(set(cluster['signals']) & set(MERGE_SIGNALS))
            units -= len(ids) - 1
        self.assertEqual(self.report['eligible_groups'], len(eligible))
        self.assertEqual(self.report['proposed_split_units'], units)
        self.assertEqual(sum(f['eligible_groups'] for f in self.report['by_family'].values()),
                         len(eligible))

    def test_calibration_aliases_come_from_clusters_and_lie_outside_the_reservation(self):
        reserved = {task['data'][f'{side}_group_id'] for task in self.tasks
                    for side in ('original', 'candidate')}
        calibration = self.report['calibration']
        self.assertEqual(calibration['reserved_groups'], len(reserved))
        clusters = [{product['group_id'] for product in cluster['products']}
                    for cluster in self.report['alias_clusters']]
        expected = set().union(*(c for c in clusters if c & reserved)) - reserved
        self.assertEqual(set(calibration['alias_groups_to_exclude_with_them']), expected)
        self.assertEqual(calibration['pilot_pairs_whose_members_are_linked'], [])
