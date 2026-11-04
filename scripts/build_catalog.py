"""Build the comparable catalog (pipeline step 3) from the verified raw snapshot.

Writes ``data/catalog.parquet``, ``data/catalog_report.json`` and
``data/catalog_parquet_manifest.json``. ``--verify`` rebuilds the records in memory
and checks that the committed manifest, report and Parquet file still match.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.comparable import (  # noqa: E402
    CANDIDATE_FAMILIES, FAMILIES, MIN_ELIGIBLE_PER_FAMILY, SCHEMA_VERSION, SCORE_CONTEXT,
    assign_family, build_record, finalize,
)
from scripts.audit_data import verify  # noqa: E402

PARQUET = ROOT / 'data/catalog.parquet'
REPORT = ROOT / 'data/catalog_report.json'
MANIFEST = ROOT / 'data/catalog_parquet_manifest.json'
SNAPSHOTS = {
    'catalog': ('data/catalog.jsonl.gz', 'data/catalog_manifest.json'),
    'expansion': ('data/catalog_expansion.jsonl.gz', 'data/catalog_expansion_manifest.json'),
}


def load_raw(root: Path = ROOT):
    """Verified rows from the base snapshot plus the family expansion when present.

    Rows carry ``_source_snapshot``; a code seen in an earlier snapshot is not repeated.
    """
    rows, sources, seen = [], {}, set()
    for name, (data_path, manifest_path) in SNAPSHOTS.items():
        if not (root / data_path).exists():
            continue
        manifest = json.loads((root / manifest_path).read_text())
        if sources and manifest['revision'] != sources['catalog']['revision']:
            raise ValueError(f'{name} snapshot revision differs from the base catalog')
        batch = verify(gzip.decompress((root / data_path).read_bytes()), manifest)
        duplicates = 0
        for row in batch:
            if row['code'] in seen:
                duplicates += 1
                continue
            seen.add(row['code'])
            row['_source_snapshot'] = name
            rows.append(row)
        sources[name] = {'path': data_path, 'revision': manifest['revision'],
                         'sha256': manifest['sha256'], 'rows': len(batch),
                         'duplicate_codes_dropped': duplicates}
    return rows, sources


def build_records(rows):
    return finalize([build_record(row) for row in rows])


def content_sha256(records) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False).encode())
        digest.update(b'\n')
    return digest.hexdigest()


def family_summary(records, rows, families):
    summary = {}
    for family in families:
        members = [r for r, row in zip(records, rows)
                   if assign_family(row.get('categories_tags'), {family: families[family]})]
        eligible_now = [r for r in members if not [x for x in r['exclusion_reasons']
                                                   if x not in ('not_in_selected_family',
                                                                'family_below_minimum')]]
        summary[family] = {
            'category_tags': list(families[family]),
            'raw_members': len(members),
            'complete_members': len(eligible_now),
            'eligible_members': sum(r['eligible'] for r in members),
            'eligible_groups': len({r['group_key'] for r in members if r['eligible']}),
            'eligible_by_source_snapshot': dict(sorted(Counter(
                r['source_snapshot'] for r in members if r['eligible']).items())),
            'complete_by_comparison_unit': dict(sorted(Counter(
                r['comparison_unit'] for r in eligible_now).items())),
            'complete_groups': len({r['group_key'] for r in eligible_now}),
            'agribalyse_versions_among_eligible': dict(sorted(Counter(
                r['agribalyse_version'] or '(missing)' for r in members if r['eligible']).items())),
            'top_exclusion_reasons': dict(Counter(
                x for r in members for x in r['exclusion_reasons']
                if x not in ('not_in_selected_family',)).most_common(6)),
        }
    return summary


def make_report(records, rows, sources):
    eligible = [r for r in records if r['eligible']]
    groups = Counter(r['group_key'] for r in records)
    multi = {key: size for key, size in groups.items() if size > 1}
    return {
        'schema_version': SCHEMA_VERSION,
        'rows': len(records),
        'rows_by_source_snapshot': {name: source['rows'] - source['duplicate_codes_dropped']
                                    for name, source in sources.items()},
        'eligible': len(eligible),
        'eligible_by_source_snapshot': dict(sorted(Counter(
            r['source_snapshot'] for r in eligible).items())),
        'eligible_by_family': dict(sorted(Counter(r['family'] for r in eligible).items())),
        'eligible_groups_by_family': {
            family: len({r['group_key'] for r in eligible if r['family'] == family})
            for family in sorted(FAMILIES)},
        'eligible_by_comparison_unit': dict(sorted(Counter(
            r['comparison_unit'] for r in eligible).items())),
        'eligible_groups': len({r['group_key'] for r in eligible}),
        'exclusion_reason_counts': dict(sorted(Counter(
            x for r in records for x in r['exclusion_reasons']).items())),
        'products_with_comparison_unit': dict(sorted(Counter(
            r['comparison_unit'] or '(unknown)' for r in records).items())),
        'implausible_nutrient_counts': dict(sorted(Counter(
            n for r in records for n in r['implausible_nutrients']).items())),
        'environmental_score': {
            'context': SCORE_CONTEXT,
            'known': sum(r['environmental_score'] is not None for r in records),
            'world_differs_from_context': sum(
                r['environmental_score'] is not None
                and r['environmental_score_world'] != r['environmental_score'] for r in records),
            'missing_key_data_among_known': sum(bool(r['environmental_missing_key_data'])
                                                for r in records if r['environmental_score'] is not None),
            'agribalyse_versions_among_eligible': dict(sorted(Counter(
                r['agribalyse_version'] or '(missing)' for r in eligible).items())),
        },
        'duplicate_groups': {
            'groups_with_multiple_products': len(multi),
            'products_in_such_groups': sum(multi.values()),
            'largest_group_size': max(multi.values(), default=1),
        },
        'selected_families': family_summary(records, rows, FAMILIES),
        'min_eligible_per_family': MIN_ELIGIBLE_PER_FAMILY,
        'candidate_families_not_selected': family_summary(records, rows, CANDIDATE_FAMILIES),
        'note': (
            'Eligibility requires a cleaned name and ingredients, a recorded g/ml unit, '
            'plausible per-100 proteins/sugars/salt, a known environmental score in the '
            f'"{SCORE_CONTEXT}" context and membership of a selected family with at least '
            f'{MIN_ELIGIBLE_PER_FAMILY} eligible products. Missing values remain missing. '
            'Score differences are an experimental index, not emissions. Products with the '
            'same normalized name and brand share a group regardless of quantity.'
        ),
    }


def write_outputs(records, report, sources):
    import pandas as pd

    frame = pd.DataFrame.from_records(records)
    frame.to_parquet(PARQUET, index=False)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    MANIFEST.write_text(json.dumps({
        'schema_version': SCHEMA_VERSION,
        'source_snapshot': sources['catalog']['path'],
        'source_sha256': sources['catalog']['sha256'],
        'source_revision': sources['catalog']['revision'],
        'source_snapshots': sources,
        'rows': len(records),
        'eligible': report['eligible'],
        'content_sha256': content_sha256(records),
        'columns': list(frame.columns),
        'selected_families': {k: list(v) for k, v in FAMILIES.items()},
        'min_eligible_per_family': MIN_ELIGIBLE_PER_FAMILY,
        'environmental_score_context': SCORE_CONTEXT,
        'note': 'content_sha256 covers the canonical JSON of every record, not the Parquet bytes.',
    }, indent=2) + '\n')


def verify_outputs(records, report, sources):
    import pandas as pd

    manifest = json.loads(MANIFEST.read_text())
    problems = []
    if manifest['source_sha256'] != sources['catalog']['sha256']:
        problems.append('manifest source checksum differs from raw manifest')
    if manifest.get('source_snapshots') != sources:
        problems.append('manifest source snapshots differ from the files present')
    if manifest['content_sha256'] != content_sha256(records):
        problems.append('rebuilt records differ from manifest content_sha256')
    if json.loads(REPORT.read_text()) != json.loads(json.dumps(report)):
        problems.append('rebuilt report differs from data/catalog_report.json')
    frame = pd.read_parquet(PARQUET)
    if len(frame) != len(records) or list(frame['code']) != [r['code'] for r in records]:
        problems.append('Parquet rows or codes differ from rebuilt records')
    if list(frame.columns) != manifest['columns']:
        problems.append('Parquet columns differ from manifest')
    if int(frame['eligible'].sum()) != report['eligible']:
        problems.append('Parquet eligible count differs from report')
    if problems:
        raise SystemExit('Comparable catalog verification failed: ' + '; '.join(problems))
    return len(frame)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true',
                        help='Rebuild in memory and compare with committed outputs')
    args = parser.parse_args()
    rows, sources = load_raw()
    records = build_records(rows)
    report = make_report(records, rows, sources)
    if args.verify:
        count = verify_outputs(records, report, sources)
        print(f'Comparable catalog verified: {count} rows, {report["eligible"]} eligible')
    else:
        write_outputs(records, report, sources)
        print(json.dumps({'rows': len(records), 'eligible': report['eligible'],
                          'eligible_by_family': report['eligible_by_family'],
                          'eligible_groups_by_family': report['eligible_groups_by_family']}, indent=2))
