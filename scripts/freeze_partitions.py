"""Freeze eligible product groups into calibration, train, validation and test partitions.

Groups joined by any alias link from ``scripts/inspect_aliases.py`` form one split
unit and always share a partition. Units holding a pilot calibration group go to
``calibration`` and stay out of model development. The remaining units of each
family are ordered by a seeded hash and sliced into test, validation and train.

This freezes product partitions only. It builds no pair or triplet and uses no label.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_catalog import MANIFEST, PARQUET, content_sha256  # noqa: E402
from scripts.fetch_data import write_atomic  # noqa: E402
from scripts.inspect_aliases import (  # noqa: E402
    MERGE_SIGNALS, MIN_INGREDIENT_CHARS, NAME_JACCARD, PILOT, REVIEW_SIGNALS, find_links,
    group_profiles, same_brand_pairs,
)

OUTPUT = ROOT / 'data/partitions.json'
VERSION = 'partitions-v1'
SEED = 'basket-optimizer-partitions-v1'
SHARES = {'test': 0.15, 'validation': 0.15}   # train takes the remaining units
PARTITIONS = ('calibration', 'train', 'validation', 'test')
EXPOSURE_JACCARD = 0.6


def split_units(group_ids, links):
    """Connected components over every link, singletons included, as sorted lists."""
    parent = {group_id: group_id for group_id in group_ids}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for first, second in links:
        parent[find(second)] = find(first)
    components = defaultdict(list)
    for group_id in parent:
        components[find(group_id)].append(group_id)
    return sorted(sorted(members) for members in components.values())


def assign(unit_ids, seed=SEED, shares=SHARES):
    """Map unit ids to test, validation or train by slicing a seeded hash order."""
    ordered = sorted(unit_ids, key=lambda unit_id: hashlib.sha256(
        f'{seed}|{unit_id}'.encode()).hexdigest())
    test = round(shares['test'] * len(ordered))
    validation = round(shares['validation'] * len(ordered))
    return {unit_id: 'test' if index < test else 'validation' if index < test + validation
            else 'train' for index, unit_id in enumerate(ordered)}


def build_partitions(rows, catalog_hash, pilot_tasks):
    profiles = group_profiles(rows)
    links, _, _ = find_links(profiles)
    lowest_code, products = {}, Counter()
    for row in rows:
        if row['eligible']:
            products[row['group_id']] += 1
            lowest_code[row['group_id']] = min(
                row['code'], lowest_code.get(row['group_id'], row['code']))
    reserved = {task['data'][f'{side}_group_id'] for task in pilot_tasks
                for side in ('original', 'candidate')}

    units = []
    for members in split_units(profiles, links):
        units.append({'unit_id': min(lowest_code[group_id] for group_id in members),
                      'family': profiles[members[0]]['family'],
                      'calibration': bool(reserved & set(members)), 'group_ids': members})
    for family in {unit['family'] for unit in units}:
        assigned = assign([unit['unit_id'] for unit in units
                           if unit['family'] == family and not unit['calibration']])
        for unit in units:
            if unit['family'] == family:
                unit['partition'] = ('calibration' if unit.pop('calibration')
                                     else assigned[unit['unit_id']])
    units.sort(key=lambda unit: (unit['family'], unit['unit_id']))
    unit_order = ('unit_id', 'family', 'partition', 'group_ids')
    units = [{key: unit[key] for key in unit_order} for unit in units]

    partition_of = {group_id: unit['partition'] for unit in units for group_id in unit['group_ids']}
    counts = {}
    for family in sorted({unit['family'] for unit in units}):
        counts[family] = {}
        for partition in PARTITIONS:
            chosen = [unit for unit in units
                      if unit['family'] == family and unit['partition'] == partition]
            groups = [group_id for unit in chosen for group_id in unit['group_ids']]
            counts[family][partition] = {'units': len(chosen), 'groups': len(groups),
                                         'products': sum(products[group_id] for group_id in groups)}

    # Same-brand groups with similar names that the rules leave in different units.
    similar, crossing = 0, Counter()
    for pair, similarity in same_brand_pairs(profiles):
        if similarity >= EXPOSURE_JACCARD and pair not in links:
            first, second = sorted(partition_of[group_id] for group_id in pair)
            similar += 1
            if first != second:
                crossing[f'{first}|{second}'] += 1

    return {
        'version': VERSION,
        'catalog_content_sha256': catalog_hash,
        'parameters': {
            'seed': SEED,
            'shares': dict(SHARES, train='remaining units'),
            'stratified_by': 'family',
            'unit_rule': 'eligible groups joined by any alias link share a unit',
            'link_signals': list(MERGE_SIGNALS + REVIEW_SIGNALS),
            'name_jaccard': NAME_JACCARD,
            'min_ingredient_chars': MIN_INGREDIENT_CHARS,
            'unit_id': 'lowest eligible barcode in the unit',
            'calibration_rule': 'units holding a pilot calibration group',
        },
        'eligible_groups': len(profiles),
        'units_total': len(units),
        'counts': counts,
        'similar_name_exposure': {
            'definition': (f'same-family groups sharing a brand entry with name-token Jaccard of at '
                           f'least {EXPOSURE_JACCARD} that no alias link joins'),
            'group_pairs': similar,
            'in_different_partitions': dict(sorted(crossing.items())),
        },
        'units': units,
        'note': ('Product partitions only: no pair or triplet has been built and no label is used. '
                 'The alias links behind the units have not been reviewed by a person. Changing a '
                 'rule, the seed or the catalog requires a new version before any pair is labeled.'),
    }


def group_partitions(report):
    """Map every eligible group id to its partition name."""
    return {group_id: unit['partition'] for unit in report['units'] for group_id in unit['group_ids']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Compare without writing')
    args = parser.parse_args()
    rows = pq.read_table(PARQUET).to_pylist()
    digest = content_sha256(rows)
    if digest != json.loads(MANIFEST.read_text())['content_sha256']:
        raise SystemExit('Catalog contents differ from the comparable catalog manifest')
    pilot_tasks = json.loads(PILOT.read_text())
    if {task['data']['catalog_content_sha256'] for task in pilot_tasks} != {digest}:
        raise SystemExit('Pilot tasks were built from a different catalog')
    report = build_partitions(rows, digest, pilot_tasks)
    payload = (json.dumps(report, ensure_ascii=False, indent=1) + '\n').encode()
    if args.verify:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit('Partitions differ from the expected build')
    else:
        write_atomic(OUTPUT, payload)
    totals = Counter(unit['partition'] for unit in report['units'])
    print(f'{report["units_total"]} units from {report["eligible_groups"]} eligible groups: '
          + ', '.join(f'{totals[partition]} {partition}' for partition in PARTITIONS))


if __name__ == '__main__':
    main()
