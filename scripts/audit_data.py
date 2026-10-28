"""Verify snapshot integrity and report raw coverage without extra dependencies."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUTRIENTS = ('proteins', 'sugars', 'salt')


def present(value):
    return value is not None and value != '' and value != [] and value != {}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def nutrients_100g(row):
    """Count explicit nonnegative source values, including zero; never infer them."""
    return {item['name'] for item in row.get('nutriments') or []
            if item.get('name') in NUTRIENTS and number(item.get('100g'))
            and item['100g'] >= 0}


def verify(raw, manifest):
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('Snapshot checksum differs from manifest')
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) != manifest['sample_rows']:
        raise ValueError('Row count differs from manifest')
    expected = set(manifest['selected_fields']) | {'_source_row'}
    if any(set(row) != expected for row in rows):
        raise ValueError('Record fields differ from manifest')
    if len({row['_source_row'] for row in rows}) != len(rows):
        raise ValueError('Duplicate source rows')
    return rows


def audit(catalog=False):
    stem = 'catalog' if catalog else 'off_sample'
    manifest_name = 'catalog_manifest.json' if catalog else 'manifest.json'
    manifest = json.loads((ROOT / 'data' / manifest_name).read_text())
    rows = verify(gzip.decompress((ROOT / 'data' / f'{stem}.jsonl.gz').read_bytes()), manifest)
    if catalog:
        historical = json.loads((ROOT / 'data/manifest.json').read_text())
        projected = [{field: row[field] for field in historical['selected_fields'] + ['_source_row']}
                     for row in rows]
        raw = ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'
                      for row in projected).encode()
        verify(raw, historical)
        if manifest['historical_sha256'] != historical['sha256']:
            raise ValueError('Catalog historical checksum differs from manifest')

    fields = ('product_name', 'ingredients_text', 'categories_tags',
              'environmental_score_score', 'nutriments', 'quantity',
              'product_quantity', 'product_quantity_unit', 'nutrition_data_per')
    report = {
        'snapshot': stem,
        'snapshot_integrity': 'ok',
        'rows': len(rows),
        'nonempty_field_counts': {field: sum(present(row.get(field)) for row in rows)
                                  for field in fields},
    }
    if catalog:
        counts = Counter(nutrient for row in rows for nutrient in nutrients_100g(row))
        all_nutrients = [row for row in rows if set(NUTRIENTS) <= nutrients_100g(row)]
        report.update({
            'nonnegative_numeric_100g_counts': {key: counts[key] for key in NUTRIENTS},
            'all_three_nutrients_100g': len(all_nutrients),
            'all_three_nutrients_and_numeric_export_score': sum(
                number(row.get('environmental_score_score')) for row in all_nutrients),
            'product_quantity_units': dict(sorted(Counter(
                row.get('product_quantity_unit') or '(missing)' for row in rows).items())),
            'nutrition_data_per': dict(sorted(Counter(
                row.get('nutrition_data_per') or '(missing)' for row in rows).items())),
            'duplicate_nonempty_codes': sum(count - 1 for count in Counter(
                row['code'] for row in rows if row.get('code')).values()),
        })
    report['note'] = (
        'Raw coverage only, not validated eligibility. The source key "100g" is preserved; '
        'mass/volume basis, units, prepared values and score context still need normalization. '
        'Prices and stock are not included. The clustered sample is not representative of OFF.'
    )
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', action='store_true', help='Audit the expanded catalog')
    print(json.dumps(audit(parser.parse_args().catalog), indent=2))
