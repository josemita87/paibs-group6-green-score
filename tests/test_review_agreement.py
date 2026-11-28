"""Checks for the pilot review validation and agreement report (pipeline step 4).

Every export here is synthetic and built in memory from the unlabeled pilot tasks,
except the two committed label files, which a model drafted. No independent human
reviewer's decision is stored in the repository.
"""
from collections import Counter
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.review_agreement import (
    ROOT, agreement, cohen_kappa, declared_model, form_fields, load_tasks, main, parse_review,
    source_of,
)

PAIRS = ROOT / 'data/pairs.json'
MODEL_PILOT_REVIEW = ROOT / 'data/pilot_review_model.json'
MODEL_PAIRS_REVIEW = ROOT / 'data/pairs_review_model.json'
REVIEW_RECORD = ROOT / 'data/pairs_review_record.json'

DECISION, REASON, LABELS = form_fields()
TASKS = load_tasks()
PAIR_IDS = list(TASKS)


def annotation(label, reason='Both are spoonable.', cancelled=False):
    """One annotation in the shape of a full JSON Label Studio export."""
    return {
        'id': 1, 'completed_by': 1, 'was_cancelled': cancelled,
        'result': [
            {'from_name': DECISION, 'to_name': 'candidate', 'type': 'choices',
             'value': {'choices': [label]}},
            {'from_name': REASON, 'to_name': 'candidate', 'type': 'textarea',
             'value': {'text': [reason]}},
        ],
    }


def export(labels=None, reasons=None):
    """A complete synthetic export; ``labels`` and ``reasons`` override by pair id."""
    labels, reasons = labels or {}, reasons or {}
    return [{'id': index, 'data': dict(TASKS[pair_id], extra_field_added_by_tool=1),
             'annotations': [annotation(labels.get(pair_id, 'acceptable'),
                                        reasons.get(pair_id, 'Both are spoonable.'))]}
            for index, pair_id in enumerate(PAIR_IDS, start=1)]


def parse(items):
    return parse_review(items, TASKS, DECISION, REASON, LABELS)


class FormChecks(unittest.TestCase):
    def test_controls_and_labels_come_from_the_review_form(self):
        self.assertEqual((DECISION, REASON), ('decision', 'reason'))
        self.assertEqual(LABELS, ('acceptable', 'unacceptable', 'ambiguous'))
        self.assertEqual(len(PAIR_IDS), 36)


class ParseChecks(unittest.TestCase):
    def test_complete_export_parses_every_pair(self):
        reviews, errors = parse(export({PAIR_IDS[0]: 'ambiguous'}, {PAIR_IDS[0]: '  Unclear format. '}))
        self.assertEqual(errors, [])
        self.assertEqual(list(reviews), PAIR_IDS)
        self.assertEqual(reviews[PAIR_IDS[0]], {'label': 'ambiguous', 'reason': 'Unclear format.'})

    def test_each_incomplete_or_invalid_task_is_reported(self):
        items = export()
        items[0]['annotations'] = []                                   # never reviewed
        items[1]['annotations'] = [annotation('acceptable', cancelled=True)]   # skipped
        items[2]['annotations'].append(annotation('ambiguous'))         # two submissions
        items[3]['annotations'] = [annotation('acceptable', reason='   ')]
        items[4]['annotations'] = [annotation('maybe')]
        items[5]['annotations'][0]['result'][0]['value']['choices'] = ['acceptable', 'ambiguous']
        items[6]['data'] = dict(items[6]['data'], candidate_name='Edited after export')
        items[7]['data'] = dict(items[7]['data'], pair_id='pilot-v1/unknown/1/2')
        items.append(dict(items[8]))                                    # duplicate
        del items[9]                                                    # absent from the export
        reviews, errors = parse(items)
        expected = {
            PAIR_IDS[0]: '0 submitted annotations', PAIR_IDS[1]: '0 submitted annotations',
            PAIR_IDS[2]: '2 submitted annotations', PAIR_IDS[3]: 'empty reason',
            PAIR_IDS[4]: 'expected exactly one label', PAIR_IDS[5]: 'expected exactly one label',
            PAIR_IDS[6]: 'task data differ', PAIR_IDS[7]: 'missing from the export',
            PAIR_IDS[8]: 'appears more than once', PAIR_IDS[9]: 'missing from the export',
            'pilot-v1/unknown/1/2': 'not a pair of the task file',
        }
        for pair_id, message in expected.items():
            self.assertTrue(any(e.startswith(f'{pair_id}: ') and message in e for e in errors),
                            (pair_id, message, errors))
        self.assertEqual(len(errors), len(expected))
        self.assertFalse(set(PAIR_IDS[:8]) & set(reviews))

    def test_other_export_formats_are_rejected(self):
        json_min = [{'pair_id': PAIR_IDS[0], 'decision': 'acceptable', 'reason': 'x'}]
        reviews, errors = parse(json_min)
        self.assertEqual(reviews, {})
        self.assertIn('full JSON export', errors[0])
        self.assertIn('full JSON export', parse({'tasks': []})[1][0])


class AgreementChecks(unittest.TestCase):
    def test_kappa_matches_hand_computed_value_and_undefined_case(self):
        pairs = [('a', 'a')] * 20 + [('a', 'b')] * 5 + [('b', 'a')] * 10 + [('b', 'b')] * 15
        self.assertAlmostEqual(cohen_kappa(pairs, ('a', 'b')), 0.4)   # observed 0.7, expected 0.5
        self.assertEqual(cohen_kappa([('a', 'a'), ('b', 'b')], ('a', 'b')), 1.0)
        self.assertIsNone(cohen_kappa([('a', 'a')] * 3, ('a', 'b')))
        self.assertIsNone(cohen_kappa([], ('a', 'b')))

    def test_report_counts_table_disagreements_and_duplicate_flags(self):
        first, _ = parse(export({PAIR_IDS[0]: 'unacceptable', PAIR_IDS[1]: 'ambiguous'},
                                {PAIR_IDS[2]: 'Possible duplicate: same pack, other size.'}))
        second, _ = parse(export({PAIR_IDS[0]: 'unacceptable', PAIR_IDS[3]: 'ambiguous'}))
        report = agreement(first, second, TASKS, LABELS, ('ana', 'ben'))
        self.assertEqual((report['pairs'], report['identical_decisions']), (36, 34))
        table = report['label_table']['counts']
        self.assertEqual(table['unacceptable']['unacceptable'], 1)
        self.assertEqual(table['ambiguous']['acceptable'], 1)
        self.assertEqual(table['acceptable']['ambiguous'], 1)
        self.assertEqual(table['acceptable']['acceptable'], 33)
        self.assertEqual(sum(sum(row.values()) for row in table.values()), 36)
        self.assertEqual([d['pair_id'] for d in report['disagreements']], [PAIR_IDS[1], PAIR_IDS[3]])
        self.assertEqual(report['disagreements'][0]['ana']['label'], 'ambiguous')
        self.assertEqual(report['disagreements'][0]['ben']['label'], 'acceptable')
        self.assertEqual(sum(f['pairs'] for f in report['identical_by_family'].values()), 36)
        self.assertEqual(sum(f['identical'] for f in report['identical_by_family'].values()), 34)
        self.assertEqual(report['possible_duplicates'], [{
            'pair_id': PAIR_IDS[2], 'flagged_by': ['ana'],
            'original_group_id': TASKS[PAIR_IDS[2]]['original_group_id'],
            'candidate_group_id': TASKS[PAIR_IDS[2]]['candidate_group_id']}])
        self.assertEqual(report['identical_reason_texts'], 35)
        # Each reviewer: 34 acceptable, 1 unacceptable, 1 ambiguous -> expected (34*34 + 1 + 1) / 36^2.
        expected = 1158 / 1296
        self.assertAlmostEqual(report['cohen_kappa'], round((34 / 36 - expected) / (1 - expected), 4))


class CommandChecks(unittest.TestCase):
    def run_main(self, first, second, names=('ana.json', 'ben.json'), extra=()):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in names]
            for path, items in zip(paths, (first, second)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(items))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main([str(path) for path in paths] + list(extra))
            return json.loads(output.getvalue())

    def test_command_reports_agreement_for_two_complete_reviews(self):
        report = self.run_main(export(), export({PAIR_IDS[0]: 'ambiguous'}))
        self.assertEqual(report['reviewers'], ['ana', 'ben'])
        self.assertEqual(report['identical_decisions'], 35)

    def test_command_refuses_incomplete_reviews_and_reused_names(self):
        with self.assertRaises(SystemExit) as context:
            self.run_main(export(), export()[:-1])
        message = str(context.exception)
        self.assertIn('agreement not computed', message)
        self.assertIn(f'ben: {PAIR_IDS[-1]}: missing from the export', message)
        with self.assertRaisesRegex(SystemExit, 'file names must differ'):
            self.run_main(export(), export(), names=('a/x.json', 'b/x.json'))

    def test_command_checks_the_sampled_pairs_with_another_task_file(self):
        tasks = load_tasks(PAIRS)
        self.assertEqual(len(tasks), 300)
        first = [{'data': data, 'annotations': [annotation('acceptable')]}
                 for data in tasks.values()]
        changed = next(iter(tasks))
        second = [{'data': data, 'annotations': [annotation(
            'ambiguous' if pair_id == changed else 'acceptable')]}
            for pair_id, data in tasks.items()]
        report = self.run_main(first, second, extra=['--tasks', str(PAIRS)])
        self.assertEqual((report['pairs'], report['identical_decisions']), (300, 299))
        partition, strategy = tasks[changed]['partition'], tasks[changed]['strategy']
        by_partition = report['identical_by_partition']
        self.assertEqual({name: value['pairs'] for name, value in by_partition.items()},
                         {'test': 60, 'train': 180, 'validation': 60})
        self.assertEqual(by_partition[partition]['identical'], by_partition[partition]['pairs'] - 1)
        by_strategy = report['identical_by_strategy']
        self.assertEqual(sum(value['pairs'] for value in by_strategy.values()), 300)
        self.assertEqual(by_strategy[strategy]['identical'], by_strategy[strategy]['pairs'] - 1)
        # A pilot export is refused against the sampled pairs.
        with self.assertRaisesRegex(SystemExit, 'not a pair of the task file'):
            self.run_main(export(), export(), extra=['--tasks', str(PAIRS)])

    def test_pilot_report_has_no_partition_or_strategy_section(self):
        report = self.run_main(export(), export())
        self.assertNotIn('identical_by_partition', report)
        self.assertNotIn('identical_by_strategy', report)
        self.assertEqual(report['reviewers_declared_as_model'], [])
        self.assertIn('cannot prove who annotated', report['note'])


class SourceChecks(unittest.TestCase):
    def test_a_declared_model_annotation_is_recognized(self):
        person = {'data': {}, 'annotations': [annotation('acceptable')]}
        self.assertFalse(declared_model(person))
        self.assertFalse(declared_model(dict(person, meta={'annotator': 'ana'})))
        self.assertTrue(declared_model(dict(person, meta={'annotator_type': 'AI'})))
        self.assertTrue(declared_model(dict(person, meta={'human_reviewed': False})))
        by_model = dict(annotation('acceptable'), completed_by={'type': 'ai_model'})
        self.assertTrue(declared_model({'data': {}, 'annotations': [by_model]}))
        not_human = dict(annotation('acceptable'), completed_by={'is_human_review': False})
        self.assertTrue(declared_model({'data': {}, 'annotations': [not_human]}))

    def test_export_sources_are_counted(self):
        self.assertEqual(source_of(export()), {'tasks_declaring_a_model': 0,
                                               'declared_source': 'not declared as a model'})
        committed = json.loads(MODEL_PILOT_REVIEW.read_text())
        self.assertEqual(source_of(committed), {'tasks_declaring_a_model': 36,
                                                'declared_source': 'model'})
        self.assertEqual(source_of({'not': 'a list'})['tasks_declaring_a_model'], 0)

    def test_the_report_names_a_model_reviewer(self):
        committed = json.loads(MODEL_PILOT_REVIEW.read_text())
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / 'ana.json', Path(directory) / 'model.json']
            paths[0].write_text(json.dumps(export()))
            paths[1].write_text(json.dumps(committed))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main([str(path) for path in paths])
        report = json.loads(output.getvalue())
        self.assertEqual(report['reviewers_declared_as_model'], ['model'])
        self.assertEqual(report['sources']['model']['tasks_declaring_a_model'], 36)
        self.assertIn('not agreement between two people', report['note'])


class SampledPairDraftChecks(unittest.TestCase):
    """The 300 model-drafted labels of ``pairs-v1`` and the record of their review."""

    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(REVIEW_RECORD.read_text())
        cls.tasks = load_tasks(PAIRS)
        cls.items = json.loads(MODEL_PAIRS_REVIEW.read_text())
        cls.reviews, cls.errors = parse_review(cls.items, cls.tasks, DECISION, REASON, LABELS)

    def test_the_draft_labels_every_sampled_pair_once(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(list(self.reviews), list(self.tasks))
        self.assertEqual(len(self.reviews), 300)

    def test_the_draft_still_declares_a_model_on_every_task(self):
        self.assertEqual(source_of(self.items), {'tasks_declaring_a_model': 300,
                                                 'declared_source': 'model'})
        draft = self.record['draft']
        self.assertEqual({item['meta']['annotator'] for item in self.items},
                         {draft['declared_annotator']})
        self.assertEqual({item['meta']['annotator_type'] for item in self.items},
                         {draft['declared_annotator_type']})

    def test_the_record_points_at_these_exact_labels(self):
        self.assertEqual(self.record['labels_file'], 'data/pairs_review_model.json')
        self.assertEqual(self.record['labels_sha256'],
                         hashlib.sha256(MODEL_PAIRS_REVIEW.read_bytes()).hexdigest())
        self.assertEqual(self.record['tasks_version'],
                         json.loads(PAIRS.read_text())['version'])
        self.assertIn('not independent human labels', self.record['label_status'])
        self.assertTrue(self.record['review']['reviewer_saw_the_draft_labels'])

    def test_the_recorded_counts_match_the_labels(self):
        by_label, by_partition, by_original = Counter(), {}, {}
        for pair_id, review in self.reviews.items():
            task = self.tasks[pair_id]
            by_label[review['label']] += 1
            by_partition.setdefault(task['partition'], Counter())[review['label']] += 1
            by_original.setdefault((task['partition'], task['original_group_id']),
                                   Counter())[review['label']] += 1
        triplets = Counter()
        for (partition, _), labels in by_original.items():
            triplets[partition] += labels['acceptable'] * labels['unacceptable']
        counts = self.record['counts']
        self.assertEqual(counts['pairs'], len(self.reviews))
        self.assertEqual(counts['by_label'], {label: by_label[label] for label in sorted(LABELS)})
        self.assertEqual(counts['by_partition'],
                         {partition: {label: found[label] for label in sorted(LABELS)}
                          for partition, found in by_partition.items()})
        self.assertEqual(counts['triplets_possible'],
                         {partition: triplets[partition] for partition in by_partition})


if __name__ == '__main__':
    unittest.main()
