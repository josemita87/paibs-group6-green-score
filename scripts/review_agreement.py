"""Check two independent reviews of one task file and report their agreement (step 4).

Reads two full-JSON Label Studio exports of ``data/annotation_pilot.json`` or, with
``--tasks data/pairs.json``, of the sampled annotation pairs. It joins them on
``data.pair_id`` and reports agreement as it stood before any discussion. Both
exports must be complete: every pair needs exactly one submitted annotation with
one label and a nonempty reason. Nothing is dropped silently and no final label
is written; adjudication is a human decision recorded separately.

An export that declares a model as its annotator is still compared, but the report
names it and says that the figure is not agreement between two people.
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
    """Task data keyed by pair id, in file order.

    Accepts a list of tasks (the pilot) or an object holding them under ``tasks``
    (``data/pairs.json``).
    """
    content = json.loads(Path(path).read_text())
    tasks = content['tasks'] if isinstance(content, dict) else content
    return {task['data']['pair_id']: task['data'] for task in tasks}


def declared_model(item) -> bool:
    """Whether one exported task says a model, not a person, produced its annotation."""
    meta = item.get('meta') if isinstance(item.get('meta'), dict) else {}
    if str(meta.get('annotator_type', '')).lower() in ('ai', 'model', 'ai_model') \
            or meta.get('human_reviewed') is False:
        return True
    for annotation in item.get('annotations') or []:
        author = annotation.get('completed_by') if isinstance(annotation, dict) else None
        if isinstance(author, dict) and (author.get('is_human_review') is False
                                         or author.get('type') == 'ai_model'):
            return True
    return False


def source_of(export) -> dict:
    """What an export declares about who annotated it; absence of a declaration proves nothing."""
    items = [item for item in export if isinstance(item, dict)] if isinstance(export, list) else []
    model = sum(declared_model(item) for item in items)
    return {'tasks_declaring_a_model': model,
            'declared_source': 'model' if model else 'not declared as a model'}


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
            errors.append(f'{pair_id}: not a pair of the task file')
            continue
        if pair_id in reviews or any(error.startswith(f'{pair_id}:') for error in errors):
            errors.append(f'{pair_id}: appears more than once')
            continue
        if any(data.get(key) != value for key, value in tasks[pair_id].items()):
            errors.append(f'{pair_id}: task data differ from the task file')
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


def identical_by(field, first, second, tasks):
    """Identical decisions and pair counts per value of one task field."""
    sizes = Counter(data[field] for data in tasks.values())
    identical = Counter(tasks[pair_id][field] for pair_id in tasks
                        if first[pair_id]['label'] == second[pair_id]['label'])
    return {value: {'identical': identical[value], 'pairs': size}
            for value, size in sorted(sizes.items())}


def agreement(first, second, tasks, labels, reviewers=('first', 'second'), sources=None):
    """Agreement report for two complete reviews of the same pairs."""
    pairs = [(first[pair_id]['label'], second[pair_id]['label']) for pair_id in tasks]
    counts = Counter(pairs)
    kappa = cohen_kappa(pairs, labels)
    sources = sources or {}
    model_reviewers = [name for name in reviewers
                       if sources.get(name, {}).get('declared_source') == 'model']
    # The pilot has no partition or strategy; the sampled pairs record both.
    optional = {f'identical_by_{field}': identical_by(field, first, second, tasks)
                for field in ('partition', 'strategy')
                if all(field in data for data in tasks.values())}
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
        'sources': {name: sources[name] for name in reviewers if name in sources},
        'reviewers_declared_as_model': model_reviewers,
        'catalog_content_sha256': sorted({data['catalog_content_sha256'] for data in tasks.values()}),
        'pairs': len(pairs),
        'identical_decisions': sum(a == b for a, b in pairs),
        'cohen_kappa': None if kappa is None else round(kappa, 4),
        'label_table': {
            'rows': reviewers[0], 'columns': reviewers[1],
            'counts': {a: {b: counts[(a, b)] for b in labels} for a in labels},
        },
        'identical_by_family': identical_by('family', first, second, tasks),
        **optional,
        'identical_reason_texts': sum(first[p]['reason'].lower() == second[p]['reason'].lower()
                                      for p in tasks),
        'disagreements': [
            {'pair_id': pair_id, 'family': tasks[pair_id]['family'],
             reviewers[0]: first[pair_id], reviewers[1]: second[pair_id]}
            for pair_id in tasks if first[pair_id]['label'] != second[pair_id]['label']],
        'possible_duplicates': duplicates,
        'note': ('Agreement before discussion. It measures consistency between the two exports; '
                 'it is not a model result and does not decide final labels. '
                 + (f'{", ".join(model_reviewers)} declares a model as its annotator, so this is '
                    'not agreement between two people.' if model_reviewers else
                    'Neither export declares a model; the script cannot prove who annotated.')),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path, help='Full JSON export of the first reviewer')
    parser.add_argument('second', type=Path, help='Full JSON export of the second reviewer')
    parser.add_argument('--report', type=Path, help='Also write the report to this file')
    parser.add_argument('--tasks', type=Path, default=TASKS,
                        help='Task file the exports were made from (default: the pilot)')
    args = parser.parse_args(argv)
    reviewers = (args.first.stem, args.second.stem)
    if reviewers[0] == reviewers[1]:
        raise SystemExit('Name each export after its reviewer; the two file names must differ')
    decision_name, reason_name, labels = form_fields()
    tasks = load_tasks(args.tasks)
    reviews, problems, sources = [], [], {}
    for name, path in zip(reviewers, (args.first, args.second)):
        export = json.loads(path.read_text())
        review, errors = parse_review(export, tasks, decision_name, reason_name, labels)
        reviews.append(review)
        sources[name] = source_of(export)
        problems.extend(f'{name}: {error}' for error in errors)
    if problems:
        raise SystemExit('Reviews are incomplete or invalid; agreement not computed:\n  '
                         + '\n  '.join(problems))
    report = json.dumps(agreement(*reviews, tasks, labels, reviewers, sources),
                        indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(report + '\n')
    print(report)


if __name__ == '__main__':
    main(sys.argv[1:])
