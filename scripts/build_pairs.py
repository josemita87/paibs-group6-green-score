"""Build the unlabeled annotation pairs of each frozen partition (pipeline step 4).

Reads the comparable catalog and ``data/partitions.json`` and writes
``data/pairs.json``: Label Studio tasks in the step-4 form, sampled inside one
partition and one family at a time. It writes no label.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.pairs import BUDGETS, STRATEGIES, build_pairs  # noqa: E402
from scripts.build_annotation_pilot import CONTEXTS  # noqa: E402
from scripts.build_catalog import MANIFEST, PARQUET, content_sha256  # noqa: E402
from scripts.fetch_data import write_atomic  # noqa: E402
from scripts.freeze_partitions import OUTPUT as PARTITIONS  # noqa: E402

OUTPUT = ROOT / 'data/pairs.json'


def load_inputs():
    """Catalog rows, their digest and the frozen partitions, checked against each other."""
    rows = pq.read_table(PARQUET).to_pylist()
    digest = content_sha256(rows)
    if digest != json.loads(MANIFEST.read_text())['content_sha256']:
        raise SystemExit('Catalog contents differ from the comparable catalog manifest')
    partitions = json.loads(PARTITIONS.read_text())
    if partitions['catalog_content_sha256'] != digest:
        raise SystemExit('Partitions were frozen from a different catalog')
    return rows, digest, partitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Compare without writing')
    args = parser.parse_args()
    rows, digest, partitions = load_inputs()
    report = build_pairs(rows, partitions, CONTEXTS, digest)
    payload = (json.dumps(report, ensure_ascii=False, indent=1) + '\n').encode()
    if args.verify:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit('Pairs differ from the expected build')
    else:
        write_atomic(OUTPUT, payload)
    partition_counts = Counter(task['data']['partition'] for task in report['tasks'])
    strategy_counts = Counter(task['data']['strategy'] for task in report['tasks'])
    print(f'{report["pairs_total"]} pairs: '
          + ', '.join(f'{partition_counts[partition]} {partition}' for partition in sorted(BUDGETS))
          + '; ' + ', '.join(f'{strategy_counts[s]} {s}' for s in STRATEGIES))
    if report['shortfalls']:
        print(f'{len(report["shortfalls"])} family/partition/strategy quotas not filled')


if __name__ == '__main__':
    main()
