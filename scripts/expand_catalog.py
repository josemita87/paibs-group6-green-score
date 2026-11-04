"""Expand the raw catalog within the selected families from the pinned OFF revision.

Two phases against the same ``food.parquet`` revision as ``data/catalog.jsonl.gz``:

1. Scan three light columns of every row group to locate *candidates*: rows whose
   categories place them in a selected family, with a recorded ``g``/``ml`` product
   unit and a numeric exported environmental score (necessary, not sufficient,
   conditions for eligibility).
2. Read the full selected field set for the row groups richest in candidates of the
   families still below the target, in deterministic waves, until each family has
   the target number of distinct eligible product groups or the budget is spent.

Only candidate rows are kept. The historical row groups are skipped and codes that
already exist in ``data/catalog.jsonl.gz`` are dropped. Both phases cache per row
group under ``data/cache`` and can be resumed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.comparable import COMPARISON_UNITS, FAMILIES, assign_family, build_record, finite_number  # noqa: E402
from scripts.fetch_data import EXTRA_FIELDS, cache_namespace, encode_rows, write_atomic  # noqa: E402

SCAN_FIELDS = ['categories_tags', 'product_quantity_unit', 'environmental_score_score']
TARGET_GROUPS_PER_FAMILY = 100
MAX_ROW_GROUPS_READ = 200
WAVE_SIZE = 8
SCAN_CHUNK = 16
THREADS = 6

OUTPUT = ROOT / 'data/catalog_expansion.jsonl.gz'
MANIFEST = ROOT / 'data/catalog_expansion_manifest.json'


def candidate_family(row):
    """Family id when the row meets the necessary conditions, else None."""
    family = assign_family(row.get('categories_tags'))
    if family and row.get('product_quantity_unit') in COMPARISON_UNITS \
            and finite_number(row.get('environmental_score_score')):
        return family
    return None


def eligible_group_key(row):
    """Group key when the comparable rules find no product-level exclusion, else None."""
    record = build_record(row)
    return record['group_key'] if not record['exclusion_reasons'] else None


def choose_wave(scan, unread, needed, wave_size=WAVE_SIZE):
    """Unread groups with most candidates in families still below target; ties by index."""
    scored = []
    for group in unread:
        score = sum(len(scan[group].get(family, [])) for family, gap in needed.items() if gap > 0)
        if score > 0:
            scored.append((-score, group))
    return [group for _, group in sorted(scored)[:wave_size]]


class Source:
    def __init__(self, manifest):
        import fsspec
        import pyarrow.parquet as pq

        self.manifest = manifest
        self._fsspec = fsspec
        self._pq = pq
        with self._open() as handle:
            parquet = pq.ParquetFile(handle, pre_buffer=False)
            self.metadata = parquet.metadata
            self.schema_names = parquet.schema_arrow.names
        if self.metadata.num_rows != manifest['population_rows']:
            raise ValueError('Source population differs from the pinned manifest')
        self.starts, offset = [], 0
        for group in range(self.metadata.num_row_groups):
            self.starts.append(offset)
            offset += self.metadata.row_group(group).num_rows

    def _open(self):
        return self._fsspec.open(self.manifest['download_url'], mode='rb',
                                 block_size=4 * 1024 * 1024, cache_type='none', timeout=120)

    def read(self, groups, columns):
        with self._open() as handle:
            parquet = self._pq.ParquetFile(handle, metadata=self.metadata, pre_buffer=True)
            return parquet.read_row_groups(groups, columns=columns).to_pylist()

    def compressed_bytes(self, groups, columns):
        total = 0
        for group in groups:
            row_group = self.metadata.row_group(group)
            for index in range(row_group.num_columns):
                column = row_group.column(index)
                if column.path_in_schema.split('.')[0] in columns:
                    total += column.total_compressed_size
        return total


def scan_groups(source, cache_dir):
    """Per row group: family -> row offsets of candidates. Cached per chunk."""
    scan_dir = cache_dir / 'scan'
    scan_dir.mkdir(parents=True, exist_ok=True)
    count = source.metadata.num_row_groups
    chunks = [list(range(start, min(start + SCAN_CHUNK, count))) for start in range(0, count, SCAN_CHUNK)]

    def scan_chunk(chunk):
        cache = scan_dir / f'chunk-{chunk[0]:05d}.json'
        if cache.exists():
            return json.loads(cache.read_text())
        rows = source.read(chunk, SCAN_FIELDS)
        result, position = {}, 0
        for group in chunk:
            size = source.metadata.row_group(group).num_rows
            found = {}
            for offset, row in enumerate(rows[position:position + size]):
                family = candidate_family(row)
                if family:
                    found.setdefault(family, []).append(offset)
            result[str(group)] = found
            position += size
        if position != len(rows):
            raise ValueError(f'Row count mismatch while scanning chunk {chunk[0]}')
        write_atomic(cache, json.dumps(result).encode())
        return result

    scan = {}
    with ThreadPoolExecutor(THREADS) as pool:
        for index, result in enumerate(pool.map(scan_chunk, chunks), start=1):
            scan.update({int(group): found for group, found in result.items()})
            if index % 20 == 0 or index == len(chunks):
                print(f'Scanned {min(index * SCAN_CHUNK, count)}/{count} row groups', flush=True)
    return scan


def read_candidates(source, cache_dir, fields, group, expected_offsets):
    cache = cache_dir / 'read' / f'group-{group:05d}.jsonl'
    if cache.exists():
        rows = [json.loads(line) for line in cache.read_bytes().splitlines()]
    else:
        cache.parent.mkdir(parents=True, exist_ok=True)
        batch = source.read([group], fields)
        rows = []
        for offset, row in enumerate(batch):
            if candidate_family(row):
                row['_source_row'] = source.starts[group] + offset
                rows.append(row)
        write_atomic(cache, encode_rows(rows))
    offsets = sorted(row['_source_row'] - source.starts[group] for row in rows)
    if offsets != sorted(expected_offsets):
        raise ValueError(f'Candidates read for group {group} differ from the scan')
    return rows


def existing_coverage():
    rows = [json.loads(line) for line in gzip.open(ROOT / 'data/catalog.jsonl.gz', 'rt')]
    groups = {family: set() for family in FAMILIES}
    for row in rows:
        family = candidate_family(row)
        key = eligible_group_key(row) if family else None
        if key:
            groups[family].add(key)
    return {row['code'] for row in rows}, groups


def expand(target=TARGET_GROUPS_PER_FAMILY, max_groups=MAX_ROW_GROUPS_READ):
    base = json.loads((ROOT / 'data/catalog_manifest.json').read_text())
    fields = base['selected_fields']
    if fields != json.loads((ROOT / 'data/manifest.json').read_text())['selected_fields'] + EXTRA_FIELDS:
        raise ValueError('Catalog manifest fields differ from the acquisition field list')
    source = Source(base)
    missing = set(fields) - set(source.schema_names)
    if missing:
        raise ValueError(f'Source schema is missing fields: {sorted(missing)}')
    cache_dir = ROOT / 'data/cache' / (cache_namespace(base['revision'], fields) + '-expansion')

    scan = scan_groups(source, cache_dir)
    known_codes, groups = existing_coverage()
    before = {family: len(keys) for family, keys in groups.items()}
    print('Existing distinct eligible groups:', before, flush=True)

    historical = set(base['row_groups'])
    unread = {group for group, found in scan.items() if found and group not in historical}
    read_order, waves, rows, skipped = [], [], [], 0
    stop_reason = 'target_reached'
    while True:
        needed = {family: target - len(keys) for family, keys in groups.items()}
        if all(gap <= 0 for gap in needed.values()):
            break
        if len(read_order) >= max_groups:
            stop_reason = 'row_group_budget_exhausted'
            break
        wave = choose_wave(scan, unread, needed)[:max_groups - len(read_order)]
        if not wave:
            stop_reason = 'no_remaining_candidates'
            break
        with ThreadPoolExecutor(min(THREADS, len(wave))) as pool:
            batches = list(pool.map(
                lambda group: read_candidates(source, cache_dir, fields, group,
                                              [o for offsets in scan[group].values() for o in offsets]),
                wave))
        added = 0
        for group, batch in zip(wave, batches):
            unread.discard(group)
            read_order.append(group)
            for row in batch:
                if row['code'] in known_codes:
                    skipped += 1
                    continue
                known_codes.add(row['code'])
                rows.append(row)
                added += 1
                key = eligible_group_key(row)
                if key:
                    groups[candidate_family(row)].add(key)
        waves.append({'row_groups': wave, 'rows_added': added,
                      'distinct_eligible_groups': {f: len(k) for f, k in groups.items()}})
        print(f'Wave {len(waves)}: read {len(read_order)} groups, {len(rows)} rows, '
              f'groups {waves[-1]["distinct_eligible_groups"]}', flush=True)

    rows.sort(key=lambda row: row['_source_row'])
    raw = encode_rows(rows)
    manifest = {
        'dataset': base['dataset'],
        'source_url': base['source_url'],
        'download_url': base['download_url'],
        'revision': base['revision'],
        'retrieved_utc': datetime.now(timezone.utc).isoformat(),
        'population_rows': base['population_rows'],
        'selected_fields': fields,
        'selection': {
            'families': {family: list(tags) for family, tags in FAMILIES.items()},
            'product_quantity_unit': list(COMPARISON_UNITS),
            'environmental_score_score': 'finite number',
            'excluded_row_groups': sorted(historical),
            'codes_already_in_catalog_skipped': skipped,
        },
        'scan': {
            'fields': SCAN_FIELDS,
            'row_groups_scanned': source.metadata.num_row_groups,
            'row_groups_with_candidates': len([g for g, found in scan.items() if found]),
            'candidates_by_family': {family: sum(len(found.get(family, [])) for found in scan.values())
                                     for family in FAMILIES},
            'approximate_compressed_bytes': source.compressed_bytes(range(source.metadata.num_row_groups), SCAN_FIELDS),
        },
        'read': {
            'target_distinct_eligible_groups_per_family': target,
            'max_row_groups': max_groups,
            'wave_size': WAVE_SIZE,
            'stop_reason': stop_reason,
            'row_groups_read': read_order,
            'waves': waves,
            'distinct_eligible_groups_before': before,
            'distinct_eligible_groups_after': {f: len(k) for f, k in groups.items()},
            'approximate_compressed_bytes': source.compressed_bytes(read_order, fields),
        },
        'sample_rows': len(rows),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'license': base['license'],
        'note': ('Candidate rows only; raw source values without cleaning or eligibility '
                 'filtering. Candidate conditions are necessary, not sufficient, for '
                 'eligibility, which basket/comparable.py decides.'),
    }
    write_atomic(OUTPUT, gzip.compress(raw, mtime=0))
    write_atomic(MANIFEST, (json.dumps(manifest, indent=2) + '\n').encode())
    print(f'Saved {len(rows)} rows to {OUTPUT.relative_to(ROOT)}; stop reason: {stop_reason}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=int, default=TARGET_GROUPS_PER_FAMILY,
                        help='Distinct eligible product groups wanted per family')
    parser.add_argument('--max-row-groups', type=int, default=MAX_ROW_GROUPS_READ,
                        help='Download budget: full-field row groups to read at most')
    args = parser.parse_args()
    expand(args.target, args.max_row_groups)
