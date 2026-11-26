"""Prepare the step-4 calibration tasks from the versioned comparable catalog."""
import argparse
from collections import Counter
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.comparable import normalize_key
from scripts.build_catalog import MANIFEST, PARQUET, content_sha256
from scripts.fetch_data import write_atomic

OUTPUT = ROOT / 'data/annotation_pilot.json'
PAIRS_PER_FAMILY = 12
CONTEXTS = {
    'yogurts': ('g', 'Eat the yogurt with a spoon as part of breakfast.'),
    'breakfast_cereals': ('g', 'Serve the cereal in a bowl with cold milk.'),
    'plant_based_milk_alternatives': ('ml', 'Pour the drink over breakfast cereal.'),
}


def reserve_groups(rows, family, unit, count):
    """Choose one eligible barcode per group and balance language and brand exposure."""
    representatives = {}
    for row in sorted(rows, key=lambda r: r['code']):
        if row['eligible'] and row['family'] == family and row['comparison_unit'] == unit:
            representatives.setdefault(row['group_id'], row)
    if len(representatives) < count:
        raise ValueError(f'{family} needs {count} distinct eligible groups with unit {unit}')

    languages, brands = Counter(), Counter()
    pool = []
    for row in representatives.values():
        language = row['lang'] if row['lang'] in ('fr', 'en', 'de', 'it', 'es') else 'other'
        brand = normalize_key(row['brands'])
        tie = hashlib.sha256(f"calibration-v1/{row['code']}".encode()).digest()
        pool.append((language, brand, tie, row))
    selected = []
    while len(selected) < count:
        item = min(pool, key=lambda x: (languages[x[0]], brands[x[1]], x[2]))
        language, brand, _, row = item
        selected.append(row)
        languages[language] += 1
        brands[brand] += 1
        pool.remove(item)
    return selected


def pair_products(products):
    """Mix look-alike names with broader comparisons inside the calibration pool."""
    tokens = {p['code']: set(normalize_key(p['name']).split()) for p in products}

    def overlap(pair):
        a, b = (tokens[p['code']] for p in pair)
        return len(a & b) / max(1, len(a | b))

    remaining = products.copy()
    for _ in range(len(products) // 4):
        a, b = max(combinations(remaining, 2), key=overlap)
        remaining.remove(a)
        remaining.remove(b)
        yield a, b
    yield from zip(remaining[::2], remaining[1::2], strict=True)


def build_tasks(rows, catalog_hash):
    tasks = []
    reserved = set()
    # Reserve every calibration group before constructing any pairs.
    pools = {}
    for family, (unit, _) in CONTEXTS.items():
        available = [r for r in rows if r['group_id'] not in reserved]
        pools[family] = reserve_groups(available, family, unit, 2 * PAIRS_PER_FAMILY)
        reserved.update(p['group_id'] for p in pools[family])

    for family, products in pools.items():
        unit, context = CONTEXTS[family]
        for a, b in pair_products(products):
            data = {
                'pair_id': f"pilot-v1/{family}/{a['code']}/{b['code']}",
                'catalog_content_sha256': catalog_hash,
                'family': family, 'comparison_unit': unit, 'context': context,
            }
            for role, product in [('original', a), ('candidate', b)]:
                for field in ('code', 'group_id', 'name', 'brands', 'lang', 'ingredients_text'):
                    data[f'{role}_{field}'] = product[field]
            tasks.append({'data': data})
    # Mix families and selection strategies in the order presented to reviewers.
    return sorted(tasks, key=lambda task: hashlib.sha256(task['data']['pair_id'].encode()).digest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Compare without writing')
    args = parser.parse_args()
    rows = pq.read_table(PARQUET).to_pylist()
    digest = content_sha256(rows)
    if digest != json.loads(MANIFEST.read_text())['content_sha256']:
        raise SystemExit('Catalog contents differ from the comparable catalog manifest')
    tasks = build_tasks(rows, digest)
    payload = (json.dumps(tasks, ensure_ascii=False, indent=2) + '\n').encode()
    if args.verify:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit('Pilot tasks differ from the expected build')
    else:
        write_atomic(OUTPUT, payload)
    print(f'{len(tasks)} calibration pairs across {len(CONTEXTS)} families')


if __name__ == '__main__':
    main()
