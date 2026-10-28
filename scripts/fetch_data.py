"""Reproduce the historical OFF sample or fetch its expanded raw catalog."""
import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRA_FIELDS = [
    'nutriments', 'nutrition_data_per', 'no_nutrition_data',
    'quantity', 'product_quantity', 'product_quantity_unit',
    'serving_size', 'serving_quantity', 'allergens_tags', 'traces_tags',
    'ingredients_analysis_tags', 'data_quality_errors_tags',
    'data_quality_warnings_tags', 'obsolete', 'last_modified_t',
]


def encode_rows(rows):
    return ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'
                   for row in rows).encode()


def cache_namespace(revision, fields):
    """Never reuse old caches with a different source revision or field set."""
    field_hash = hashlib.sha256(json.dumps(fields).encode()).hexdigest()[:16]
    return f'{revision}-{field_hash}'


def write_atomic(path, payload):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(payload)
    temporary.replace(path)


def fetch(catalog=False):
    import fsspec
    import pyarrow.parquet as pq

    source = json.loads((ROOT / 'data/manifest.json').read_text())
    fields = source['selected_fields'] + (EXTRA_FIELDS if catalog else [])
    cache_dir = ROOT / 'data/cache' / cache_namespace(source['revision'], fields)
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with fsspec.open(source['download_url'], mode='rb', block_size=1024 * 1024,
                     cache_type='readahead', timeout=120) as handle:
        parquet = pq.ParquetFile(handle, pre_buffer=False)
        missing = set(fields) - set(parquet.schema_arrow.names)
        if missing:
            raise ValueError(f'Source schema is missing fields: {sorted(missing)}')
        if parquet.metadata.num_rows != source['population_rows']:
            raise ValueError('Source population differs from the pinned manifest')
        starts, offset = [], 0
        for group in range(parquet.num_row_groups):
            starts.append(offset)
            offset += parquet.metadata.row_group(group).num_rows
        for group in source['row_groups']:
            cache = cache_dir / f'group-{group}.jsonl'
            if cache.exists():
                batch = [json.loads(line) for line in cache.read_bytes().splitlines()]
            else:
                batch = parquet.read_row_group(group, columns=fields).to_pylist()
                for index, row in enumerate(batch):
                    row['_source_row'] = starts[group] + index
                write_atomic(cache, encode_rows(batch))
            if len(batch) != parquet.metadata.row_group(group).num_rows:
                raise ValueError(f'Incomplete cache: {cache}')
            for index, row in enumerate(batch):
                if set(row) != set(fields) | {'_source_row'}:
                    raise ValueError(f'Unexpected cached fields: {cache}')
                if row['_source_row'] != starts[group] + index:
                    raise ValueError(f'Unexpected source row: {cache}')
            rows.extend(batch)
            print(f'Group {group}: {len(rows)} rows', flush=True)

    if len(rows) != source['sample_rows']:
        raise ValueError('Sample size differs from the historical manifest')
    # Compare all original fields, not just barcodes, before publishing new files.
    historical = [{field: row[field] for field in source['selected_fields'] + ['_source_row']}
                  for row in rows]
    if hashlib.sha256(encode_rows(historical)).hexdigest() != source['sha256']:
        raise ValueError('Downloaded historical fields differ from the pinned sample')

    raw = encode_rows(rows)
    if catalog:
        manifest = {
            **source,
            'retrieved_utc': datetime.now(timezone.utc).isoformat(),
            'selected_fields': fields,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'historical_sha256': source['sha256'],
            'note': 'Raw source values; no cleaning, unit conversion or eligibility filtering.',
        }
        data_path = ROOT / 'data/catalog.jsonl.gz'
        manifest_path = ROOT / 'data/catalog_manifest.json'
        write_atomic(data_path, gzip.compress(raw, mtime=0))
        write_atomic(manifest_path, (json.dumps(manifest, indent=2) + '\n').encode())
    else:
        data_path = ROOT / 'data/off_sample.jsonl.gz'
        write_atomic(data_path, gzip.compress(raw, mtime=0))
    print(f'Saved {len(rows)} rows to {data_path.relative_to(ROOT)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', action='store_true', help='Fetch expanded fields into a separate catalog')
    fetch(parser.parse_args().catalog)
