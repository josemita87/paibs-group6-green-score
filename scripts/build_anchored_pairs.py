"""Build the anchored annotation pairs of each frozen partition (pipeline step 4).

Reads the comparable catalog, ``data/partitions.json`` and the earlier pair set
``data/pairs.json`` and writes ``data/anchored_pairs.json``: Label Studio tasks in
the step-4 form in which each anchor product meets several candidates, so that
labels can form triplets. It writes no label.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.anchored import ANCHORS, STRATEGIES, build_anchored_pairs  # noqa: E402
from scripts.build_annotation_pilot import CONTEXTS  # noqa: E402
from scripts.build_pairs import OUTPUT as EARLIER_PAIRS, load_inputs  # noqa: E402
from scripts.fetch_data import write_atomic  # noqa: E402

OUTPUT = ROOT / 'data/anchored_pairs.json'


def earlier_tasks():
    """Tasks of ``pairs-v1``, whose group pairs are not drawn again."""
    return json.loads(EARLIER_PAIRS.read_text())['tasks']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Compare without writing')
    args = parser.parse_args()
    rows, digest, partitions = load_inputs()
    report = build_anchored_pairs(rows, partitions, CONTEXTS, digest, earlier_tasks())
    payload = (json.dumps(report, ensure_ascii=False, indent=1) + '\n').encode()
    if args.verify:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit('Anchored pairs differ from the expected build')
    else:
        write_atomic(OUTPUT, payload)
    partition_counts = Counter(task['data']['partition'] for task in report['tasks'])
    strategy_counts = Counter(task['data']['strategy'] for task in report['tasks'])
    print(f'{report["pairs_total"]} pairs around {report["anchors_total"]} anchors: '
          + ', '.join(f'{partition_counts[partition]} {partition}' for partition in sorted(ANCHORS))
          + '; ' + ', '.join(f'{strategy_counts[s]} {s}' for s in STRATEGIES)
          + f'; triplet ceiling {report["triplet_ceiling"]}')
    if report['shortfalls']:
        print(f'{len(report["shortfalls"])} family/partition quotas not filled')


if __name__ == '__main__':
    main()
