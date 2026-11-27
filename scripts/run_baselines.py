"""Rank every annotation pair with the untrained baselines (pipeline step 6).

Reads the comparable catalog, the frozen partitions, the annotation pairs and the
model-drafted pilot labels, then writes ``data/baseline_report.json``: where each
baseline places the recorded candidate among the other groups of its family and
partition, how the baselines compare per sampling strategy, how far the informative
baselines agree, and how they score the 36 labeled pilot pairs.

The frozen-encoder baseline reads the embeddings stored by
``scripts/encode_frozen.py``; this script does not load the encoder. The run uses
no human label, because none exists. It trains nothing.
"""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
import json
from pathlib import Path
from statistics import mean, median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.baselines import BASELINES, NGRAM, Baselines, percentile, rank_of, roc_auc  # noqa: E402
from basket.pairs import representatives  # noqa: E402
from scripts.build_pairs import OUTPUT as PAIRS, load_inputs  # noqa: E402
from scripts.encode_frozen import MANIFEST as EMBEDDINGS_MANIFEST, load_embeddings  # noqa: E402
from scripts.fetch_data import write_atomic  # noqa: E402

OUTPUT = ROOT / 'data/baseline_report.json'
PILOT_LABELS = ROOT / 'data/pilot_review_model.json'
VERSION = 'baselines-v2'   # v1 plus the frozen-encoder baseline; v1 numbers are unchanged
SEED = 'basket-optimizer-baselines-v1'
TOP_K = 10
INFORMATIVE = tuple(baseline for baseline in BASELINES if baseline != 'random_control')
LABELS = ('acceptable', 'ambiguous', 'unacceptable')


def pilot_pairs(path=PILOT_LABELS):
    """Model-drafted pilot pairs as ``(data, label)``, in file order."""
    pairs = []
    for task in json.loads(Path(path).read_text()):
        chosen = [choice for annotation in task['annotations'] if not annotation['was_cancelled']
                  for result in annotation['result'] if result['from_name'] == 'decision'
                  for choice in result['value']['choices']]
        if len(chosen) != 1 or chosen[0] not in LABELS:
            raise SystemExit(f"{task['data']['pair_id']}: expected one label from {list(LABELS)}")
        pairs.append((task['data'], chosen[0]))
    return pairs


def rank_pair(baselines, data, pool, partition):
    """Rank the candidate of one pair under every baseline."""
    original, candidate = data['original_group_id'], data['candidate_group_id']
    row = {'pair_id': data['pair_id'], 'partition': partition, 'family': data['family'],
           'strategy': data.get('strategy', 'pilot'),
           'languages': 'same' if data['original_lang'] == data['candidate_lang'] else 'different',
           'pool': len(pool)}
    tops = {}
    for baseline in BASELINES:
        ranking = baselines.rank(baseline, original, pool)
        rank = rank_of(ranking, candidate)
        row[baseline] = {'score': baselines.score(baseline, original, candidate),
                         'rank': rank, 'percentile': percentile(rank, len(pool))}
        tops[baseline] = {group_id for group_id, _ in ranking[:TOP_K]}
    return row, tops


def summarize(rows, key):
    """Per-baseline rank statistics for each value of ``key`` and for every row."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
        grouped['all'].append(row)
    summary = {}
    for name in sorted(grouped):
        chosen = grouped[name]
        summary[name] = {'pairs': len(chosen)}
        for baseline in BASELINES:
            ranks = [row[baseline]['rank'] for row in chosen]
            summary[name][baseline] = {
                'mean_percentile': round(mean(row[baseline]['percentile'] for row in chosen), 4),
                'median_rank': median(ranks),
                f'recall_at_{TOP_K}': round(sum(rank <= TOP_K for rank in ranks) / len(ranks), 4),
            }
    return summary


def label_scores(rows, pairs):
    """Score statistics and separation of the model-drafted pilot labels."""
    labels = {data['pair_id']: label for data, label in pairs}
    by_label = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for baseline in BASELINES:
            by_label[labels[row['pair_id']]][baseline].append(row[baseline]['score'])
    report = {'label_source': 'model-drafted, not human (data/pilot_review_model.json)',
              'counts': {label: len(by_label[label][BASELINES[0]]) for label in LABELS
                         if label in by_label}}
    for baseline in BASELINES:
        report[baseline] = {label: {'mean': round(mean(by_label[label][baseline]), 4),
                                    'median': round(median(by_label[label][baseline]), 4)}
                            for label in LABELS if label in by_label}
        if by_label['acceptable'] and by_label['unacceptable']:
            report[baseline]['auc_acceptable_over_unacceptable'] = roc_auc(
                by_label['acceptable'][baseline], by_label['unacceptable'][baseline])
    report['warning'] = (
        f"{report['counts'].get('unacceptable', 0)} unacceptable and "
        f"{report['counts'].get('ambiguous', 0)} ambiguous labels, all drafted by a model. "
        'These numbers describe this sample only and do not establish baseline quality.')
    return report


def build_report(rows, digest, pairs_report, partitions):
    """Rank every pair of the pair file and the pilot, then summarize."""
    products = representatives(rows)
    embeddings = load_embeddings(products, digest)
    encoder = json.loads(EMBEDDINGS_MANIFEST.read_text())
    units = {group_id: (unit['unit_id'], unit['partition'])
             for unit in partitions['units'] for group_id in unit['group_ids']}
    train = [group_id for group_id, (_, partition) in units.items() if partition == 'train']
    baselines = Baselines(products, train, SEED, embeddings)

    pools = {}
    for group_id, row in products.items():
        pools.setdefault((row['family'], units[group_id][1]), []).append(group_id)

    labeled = pilot_pairs()
    tasks = ([(task['data'], task['data']['partition']) for task in pairs_report['tasks']]
             + [(data, 'calibration') for data, _ in labeled])
    rows_out, overlaps = [], defaultdict(list)
    for data, partition in tasks:
        own_unit = units[data['original_group_id']][0]
        pool = [group_id for group_id in sorted(pools[(data['family'], partition)])
                if units[group_id][0] != own_unit]
        row, tops = rank_pair(baselines, data, pool, partition)
        rows_out.append(row)
        for first, second in combinations(INFORMATIVE, 2):
            overlaps[f'{first}|{second}'].append(len(tops[first] & tops[second]) / TOP_K)
    rows_out.sort(key=lambda row: row['pair_id'])

    sampled = [row for row in rows_out if row['partition'] != 'calibration']
    pilot_rows = [row for row in rows_out if row['partition'] == 'calibration']
    return {
        'version': VERSION,
        'catalog_content_sha256': digest,
        'pairs_version': pairs_report['version'],
        'partitions_version': partitions['version'],
        'parameters': {
            'seed': SEED,
            'baselines': list(BASELINES),
            'char_ngram': NGRAM,
            'tfidf_fit_corpus': f'{len(train)} train groups, document frequencies only',
            'pool_rule': ('every eligible group of the same family and partition, '
                          "except the groups of the original's split unit"),
            'tie_break': 'lowest barcode first',
            'top_k': TOP_K,
            'trained_on_labels': False,
        },
        'frozen_encoder': {
            'embeddings_version': encoder['version'],
            'embeddings_sha256': encoder['file_sha256'],
            'model': encoder['model'],
            'model_revision': encoder['model_revision'],
            'weights_updated': encoder['weights_updated'],
            'max_seq_length': encoder['max_seq_length'],
            'texts_truncated': encoder['texts_truncated'],
            'score': 'cosine of the stored int16 unit vectors, computed with integer sums',
        },
        'pool_sizes': {f'{family}|{partition}': len(members)
                       for (family, partition), members in sorted(pools.items())},
        'pairs_ranked': len(rows_out),
        'by_strategy': summarize(sampled, 'strategy'),
        'by_partition': summarize(sampled, 'partition'),
        'by_languages': summarize(sampled, 'languages'),
        'pilot': summarize(pilot_rows, 'family'),
        'top_10_agreement': {
            'definition': f'mean share of the top {TOP_K} that two baselines share, per pair',
            **{name: round(mean(values), 4) for name, values in sorted(overlaps.items())},
        },
        'pilot_labels': label_scores(pilot_rows, labeled),
        'rankings': rows_out,
        'note': ('Rankings of untrained baselines over unlabeled pairs. A high percentile means '
                 'the baseline places the sampled candidate near the top of its pool, which '
                 'reflects the sampling strategy, not substitutability. The frozen encoder was '
                 'pretrained elsewhere and none of its weights were updated here. Nothing here '
                 'is a trained result and no human label exists.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Compare without writing')
    args = parser.parse_args()
    rows, digest, partitions = load_inputs()
    pairs_report = json.loads(PAIRS.read_text())
    if pairs_report['catalog_content_sha256'] != digest:
        raise SystemExit('Pairs were built from a different catalog')
    report = build_report(rows, digest, pairs_report, partitions)
    payload = (json.dumps(report, ensure_ascii=False, indent=1) + '\n').encode()
    if args.verify:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit('Baseline report differs from the expected build')
    else:
        write_atomic(OUTPUT, payload)
    strategies = Counter(row['strategy'] for row in report['rankings'])
    print(f'{report["pairs_ranked"]} pairs ranked ('
          + ', '.join(f'{count} {name}' for name, count in sorted(strategies.items())) + ')')
    for baseline in BASELINES:
        overall = report['by_strategy']['all'][baseline]
        print(f'  {baseline}: mean percentile {overall["mean_percentile"]}, '
              f'median rank {overall["median_rank"]}, '
              f'recall@{TOP_K} {overall[f"recall_at_{TOP_K}"]}')


if __name__ == '__main__':
    main()
