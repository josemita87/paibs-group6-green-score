"""Check two independent pilot reviews and report their agreement (pipeline step 4).

Reads two full-JSON Label Studio exports of ``data/annotation_pilot.json``, joins
them on ``data.pair_id`` and reports agreement as it stood before any discussion.
Both exports must be complete: every pair needs exactly one submitted annotation
with one label and a nonempty reason. Nothing is dropped silently and no final
label is written; adjudication is a human decision recorded separately.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / 'data/annotation_pilot.json'
FORM = ROOT / 'docs/annotation_form.xml'
DUPLICATE_MARK = 'possible duplicate'


def form_fields(form_path=FORM):
    """Decision control, reason control and allowed labels, read from the review form."""
    form = ET.parse(form_path).getroot()
    choices, reason = form.find('Choices'), form.find('TextArea')
    return choices.get('name'), reason.get('name'), tuple(c.get('value') for c in choices.iter('Choice'))


def load_tasks(path=TASKS):
    """Pilot task data keyed by pair id, in the order presented to reviewers."""
    return {task['data']['pair_id']: task['data'] for task in json.loads(Path(path).read_text())}


def parse_review(export, tasks, decision_name, reason_name, labels):
    """Return ``({pair_id: {'label', 'reason'}}, errors)`` for one reviewer's export."""
    if not isinstance(export, list) or not all(isinstance(item, dict) for item in export):
        return {}, ['export is not a list of tasks; use the full JSON export']
    reviews, errors = {}, []
    for index, item in enumerate(export, start=1):
        data = item.get('data')
        pair_id = data.get('pair_id') if isinstance(data, dict) else None
        if pair_id is None or 'annotations' not in item:
            errors.append(f'task {index}: no data.pair_id or annotations; '
                          'use the full JSON export, not JSON_MIN or CSV')
            continue
        if pair_id not in tasks:
            errors.append(f'{pair_id}: not a pilot pair')
            continue
        if pair_id in reviews or any(error.startswith(f'{pair_id}:') for error in errors):
            errors.append(f'{pair_id}: appears more than once')
            continue
        if any(data.get(key) != value for key, value in tasks[pair_id].items()):
            errors.append(f'{pair_id}: task data differ from the pilot task file')
            continue
        submitted = [a for a in item['annotations'] or [] if not a.get('was_cancelled')]
        if len(submitted) != 1:
            errors.append(f'{pair_id}: {len(submitted)} submitted annotations, expected 1')
            continue
        results = submitted[0].get('result') or []
        chosen = [choice for result in results if result.get('from_name') == decision_name
                  for choice in (result.get('value') or {}).get('choices') or []]
        texts = [text for result in results if result.get('from_name') == reason_name
                 for text in (result.get('value') or {}).get('text') or []]
        reason = ' '.join(text.strip() for text in texts if isinstance(text, str) and text.strip())
        if len(chosen) != 1 or chosen[0] not in labels:
            errors.append(f'{pair_id}: expected exactly one label from {list(labels)}, got {chosen}')
        elif not reason:
            errors.append(f'{pair_id}: empty reason')
        else:
            reviews[pair_id] = {'label': chosen[0], 'reason': reason}
    reported = {error.split(': ')[0] for error in errors}
    errors.extend(f'{pair_id}: missing from the export (unreviewed tasks are not exported by default)'
                  for pair_id in tasks if pair_id not in reviews and pair_id not in reported)
    return reviews, errors


def cohen_kappa(pairs, labels):
    """Chance-corrected agreement for two raters; None when it is undefined."""
    total = len(pairs)
    if not total:
        return None
    observed = sum(first == second for first, second in pairs) / total
    first_counts = Counter(first for first, _ in pairs)
    second_counts = Counter(second for _, second in pairs)
    expected = sum(first_counts[label] * second_counts[label] for label in labels) / total ** 2
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def agreement(first, second, tasks, labels, reviewers=('first', 'second')):
    """Agreement report for two complete reviews of the same pairs."""
    pairs = [(first[pair_id]['label'], second[pair_id]['label']) for pair_id in tasks]
    counts = Counter(pairs)
    families = Counter(data['family'] for data in tasks.values())
    identical_by_family = Counter(tasks[pair_id]['family'] for pair_id in tasks
                                  if first[pair_id]['label'] == second[pair_id]['label'])
    kappa = cohen_kappa(pairs, labels)
    duplicates = []
    for pair_id, data in tasks.items():
        flagged = [name for name, review in zip(reviewers, (first[pair_id], second[pair_id]))
                   if DUPLICATE_MARK in review['reason'].lower()]
        if flagged:
            duplicates.append({'pair_id': pair_id, 'flagged_by': flagged,
                               'original_group_id': data['original_group_id'],
                               'candidate_group_id': data['candidate_group_id']})
    return {
        'reviewers': list(reviewers),
        'catalog_content_sha256': sorted({data['catalog_content_sha256'] for data in tasks.values()}),
        'pairs': len(pairs),
        'identical_decisions': sum(a == b for a, b in pairs),
        'cohen_kappa': None if kappa is None else round(kappa, 4),
        'label_table': {
            'rows': reviewers[0], 'columns': reviewers[1],
            'counts': {a: {b: counts[(a, b)] for b in labels} for a in labels},
        },
        'identical_by_family': {family: {'identical': identical_by_family[family], 'pairs': size}
                                for family, size in sorted(families.items())},
        'identical_reason_texts': sum(first[p]['reason'].lower() == second[p]['reason'].lower()
                                      for p in tasks),
        'disagreements': [
            {'pair_id': pair_id, 'family': tasks[pair_id]['family'],
             reviewers[0]: first[pair_id], reviewers[1]: second[pair_id]}
            for pair_id in tasks if first[pair_id]['label'] != second[pair_id]['label']],
        'possible_duplicates': duplicates,
        'note': ('Agreement before discussion on the calibration pilot. It measures reviewer '
                 'consistency on a deliberately diverse sample; it is not a model result and '
                 'does not decide final labels.'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path, help='Full JSON export of the first reviewer')
    parser.add_argument('second', type=Path, help='Full JSON export of the second reviewer')
    parser.add_argument('--report', type=Path, help='Also write the report to this file')
    args = parser.parse_args(argv)
    reviewers = (args.first.stem, args.second.stem)
    if reviewers[0] == reviewers[1]:
        raise SystemExit('Name each export after its reviewer; the two file names must differ')
    decision_name, reason_name, labels = form_fields()
    tasks = load_tasks()
    reviews, problems = [], []
    for name, path in zip(reviewers, (args.first, args.second)):
        review, errors = parse_review(json.loads(path.read_text()), tasks,
                                      decision_name, reason_name, labels)
        reviews.append(review)
        problems.extend(f'{name}: {error}' for error in errors)
    if problems:
        raise SystemExit('Reviews are incomplete or invalid; agreement not computed:\n  '
                         + '\n  '.join(problems))
    report = json.dumps(agreement(*reviews, tasks, labels, reviewers), indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(report + '\n')
    print(report)


if __name__ == '__main__':
    main(sys.argv[1:])
