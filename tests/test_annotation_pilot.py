"""Check calibration reservation, provenance, reviewer fields and reproducibility."""
from collections import Counter
import json
import unittest
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

from scripts.build_annotation_pilot import (
    CONTEXTS, MANIFEST, OUTPUT, PAIRS_PER_FAMILY, PARQUET, ROOT, build_tasks, reserve_groups,
)


class AnnotationPilotChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = json.loads(OUTPUT.read_text())
        cls.rows = pq.read_table(PARQUET, columns=[
            'code', 'group_id', 'eligible', 'family', 'comparison_unit',
            'name', 'ingredients_text', 'brands', 'lang',
        ]).to_pylist()
        cls.digest = json.loads(MANIFEST.read_text())['content_sha256']

    def test_rebuild_is_reproducible_independent_of_row_order(self):
        self.assertEqual(build_tasks(self.rows[::-1], self.digest), self.tasks)

    def test_tasks_match_eligible_catalog_rows_and_reserve_disjoint_groups(self):
        by_code = {r['code']: r for r in self.rows}
        used, ids, families = set(), set(), Counter()
        for task in self.tasks:
            self.assertEqual(set(task), {'data'})
            d = task['data']
            unit, context = CONTEXTS[d['family']]
            self.assertEqual((d['comparison_unit'], d['context']), (unit, context))
            self.assertEqual(d['catalog_content_sha256'], self.digest)
            self.assertNotIn(d['pair_id'], ids)
            ids.add(d['pair_id'])
            families[d['family']] += 1
            for side in ('original', 'candidate'):
                row = by_code[d[f'{side}_code']]
                self.assertTrue(row['eligible'])
                self.assertEqual((row['family'], row['comparison_unit']), (d['family'], unit))
                for field in ('group_id', 'name', 'ingredients_text', 'lang', 'brands'):
                    self.assertEqual(d[f'{side}_{field}'], row[field])
                self.assertNotIn(row['group_id'], used)
                used.add(row['group_id'])
        self.assertEqual(dict(families), dict.fromkeys(CONTEXTS, PAIRS_PER_FAMILY))

    def test_insufficient_distinct_groups_fails(self):
        row = next(r for r in self.rows if r['eligible'])
        with self.assertRaisesRegex(ValueError, 'distinct eligible groups'):
            reserve_groups([row, dict(row, code='other')], row['family'], row['comparison_unit'], 2)

    def test_form_uses_blind_fields_and_requires_decision_and_reason(self):
        form = ET.parse(ROOT / 'docs/annotation_form.xml')
        fields = {t.get('value')[1:] for t in form.iter('Text')}
        self.assertEqual(fields, {'context', 'original_name', 'original_ingredients_text',
                                  'candidate_name', 'candidate_ingredients_text'})
        for task in self.tasks:
            self.assertTrue(all(task['data'][f] for f in fields))
        self.assertEqual({c.get('value') for c in form.iter('Choice')},
                         {'acceptable', 'unacceptable', 'ambiguous'})
        for tag in ('Choices', 'TextArea'):
            self.assertEqual(form.find(tag).get('required'), 'true')
            self.assertEqual(form.find(tag).get('toName'), 'candidate')
