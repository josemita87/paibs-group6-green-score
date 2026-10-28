"""Verify the retained snapshot and report coverage without extra dependencies."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'data/manifest.json').read_text())
    raw = gzip.decompress((ROOT / 'data/off_sample.jsonl.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise SystemExit('ERROR: snapshot checksum differs from manifest')
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) != manifest['sample_rows']:
        raise SystemExit('ERROR: row count differs from manifest')
    fields = ('product_name', 'ingredients_text', 'categories_tags',
              'environmental_score_score', 'nutriments', 'quantity')
    coverage = {field: sum(row.get(field) is not None and row.get(field) != ''
                           and row.get(field) != [] and row.get(field) != {}
                           for row in rows) for field in fields}
    print(json.dumps({'snapshot_integrity': 'ok', 'rows': len(rows),
                      'nonempty_field_counts': coverage,
                      'note': 'Field presence is not verified quality or comparability. '
                              'Nutrition, prices and stock require additional data.'}, indent=2))


if __name__ == '__main__':
    main()
