"""Read-only access to the pinned raw catalog for product selection.

Products are looked up by exact barcode or by a case-insensitive substring of
their names or brands. Raw source values are kept as they are: no unit
inference, cleaning or eligibility filtering happens here.
"""
import gzip
import json
from pathlib import Path
from typing import Optional

from basket.models import NUTRIENTS, ProductRef
from scripts.audit_data import nutrients_100g, number, verify

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_CATALOG_UNITS = ('g', 'ml')


def main_name(row: dict) -> Optional[str]:
    """The source's main-language name, or the first non-empty name; None when absent."""
    entries = row.get('product_name') or []
    for entry in entries:
        if entry.get('lang') == 'main' and entry.get('text'):
            return entry['text']
    for entry in entries:
        if entry.get('text'):
            return entry['text']
    return None


def product_ref(row: dict) -> ProductRef:
    unit = row.get('product_quantity_unit')
    available = nutrients_100g(row)
    return ProductRef(
        code=row['code'],
        name=main_name(row),
        brands=row.get('brands') or None,
        catalog_unit=unit if unit in SUPPORTED_CATALOG_UNITS else None,
        nutrient_100g_available={name: name in available for name in NUTRIENTS},
        environmental_score_available=number(row.get('environmental_score_score')),
    )


class Catalog:
    """In-memory index over the verified catalog snapshot."""

    def __init__(self, rows: list[dict], revision: str, sha256: str):
        self.revision = revision
        self.sha256 = sha256
        self._rows = {row['code']: row for row in rows if row.get('code')}
        self._search_text = {
            code: ' '.join(filter(None, [
                *(entry.get('text') or '' for entry in row.get('product_name') or []),
                row.get('brands') or '',
            ])).lower()
            for code, row in self._rows.items()
        }

    @classmethod
    def load(cls, root: Path = ROOT) -> 'Catalog':
        manifest = json.loads((root / 'data/catalog_manifest.json').read_text())
        raw = gzip.decompress((root / 'data/catalog.jsonl.gz').read_bytes())
        rows = verify(raw, manifest)
        return cls(rows, revision=manifest['revision'], sha256=manifest['sha256'])

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, code: str) -> Optional[ProductRef]:
        """Exact barcode match after trimming whitespace; None when unknown."""
        row = self._rows.get(str(code).strip())
        return product_ref(row) if row is not None else None

    def search(self, query: str, limit: int = 20) -> list[ProductRef]:
        """Products whose code equals the query or whose names/brands contain it."""
        needle = query.strip().lower()
        if not needle:
            return []
        matches = []
        exact = self._rows.get(needle)
        if exact is not None:
            matches.append(exact)
        for code, text in self._search_text.items():
            if len(matches) >= limit:
                break
            if needle in text and (exact is None or code != exact['code']):
                matches.append(self._rows[code])
        return [product_ref(row) for row in matches[:limit]]
