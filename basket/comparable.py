"""Turn raw Open Food Facts records into comparable catalog records (pipeline step 3).

Rules applied here, in order of appearance in :func:`build_record`:

- Text is cleaned of HTML tags, entities and OFF allergen markers; the source
  languages are preserved.
- Nutrient values come from the source ``100g`` key, which OFF already expresses
  per 100 g or 100 ml in grams (kcal for energy) regardless of the display unit.
  Missing values stay ``None``; implausible values are set to ``None`` and recorded.
- The comparison unit is the recorded ``product_quantity_unit`` (``g`` or ``ml``).
  It is never inferred from other fields.
- The environmental score is read in one context (``scores.fr``, which equals the
  exported score); the ``world`` context is kept for reference only.
- Products are grouped by normalized name and brand so that duplicates and
  quantity variants share a group before any annotation or split.
- Every record lists why it is excluded; ``eligible`` means the list is empty.
"""
import html
import json
import math
import re
import unicodedata
from typing import Optional

SCHEMA_VERSION = 1
SCORE_CONTEXT = 'fr'
MIN_ELIGIBLE_PER_FAMILY = 20

# Family id -> category tags that place a product in it. The first match in this
# order wins. Selected for the MVP after checking coverage; see the build report.
FAMILIES: dict[str, tuple[str, ...]] = {
    'plant_based_milk_alternatives': ('en:plant-based-milk-alternatives', 'en:milk-substitutes'),
    'yogurts': ('en:yogurts',),
    'breakfast_cereals': ('en:breakfast-cereals',),
}

# Families with notable raw coverage that were not selected; reported for the team.
CANDIDATE_FAMILIES: dict[str, tuple[str, ...]] = {
    'dairy_desserts': ('en:dairy-desserts',),
    'cheeses': ('en:cheeses',),
    'biscuits': ('en:biscuits',),
    'sweet_spreads': ('en:sweet-spreads',),
    'breads': ('en:breads',),
    'plant_based_beverages': ('en:plant-based-beverages',),
    'fruit_juices': ('en:fruit-juices',),
}

# Source nutrient name -> (output column, upper plausibility bound per 100 g/ml).
NUTRIENT_COLUMNS: dict[str, tuple[str, float]] = {
    'energy-kcal': ('energy_kcal_per_100', 900.0),
    'fat': ('fat_g_per_100', 100.0),
    'saturated-fat': ('saturated_fat_g_per_100', 100.0),
    'carbohydrates': ('carbohydrates_g_per_100', 100.0),
    'sugars': ('sugars_g_per_100', 100.0),
    'fiber': ('fiber_g_per_100', 100.0),
    'proteins': ('proteins_g_per_100', 100.0),
    'salt': ('salt_g_per_100', 100.0),
}
REQUIRED_NUTRIENTS = ('proteins', 'sugars', 'salt')
COMPARISON_UNITS = ('g', 'ml')

_TAG = re.compile(r'<[^>]+>')
_ALLERGEN_MARK = re.compile(r'_([^_]{1,80})_')
_SPACE = re.compile(r'\s+')
_NON_WORD = re.compile(r'[\W_]+')  # Unicode-aware: keeps Cyrillic, Greek, Arabic letters


def clean_text(text: Optional[str]) -> Optional[str]:
    """Remove HTML tags/entities and ``_allergen_`` markers; keep words and language."""
    if not text:
        return None
    cleaned = html.unescape(_TAG.sub(' ', text))
    cleaned = _ALLERGEN_MARK.sub(r'\1', cleaned)
    cleaned = _SPACE.sub(' ', cleaned).strip()
    return cleaned or None


def normalize_key(text: Optional[str]) -> str:
    """Lowercase words without accents or punctuation, for grouping duplicates and variants."""
    cleaned = clean_text(text) or ''
    folded = unicodedata.normalize('NFKD', cleaned.lower())
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    return _NON_WORD.sub(' ', folded).strip()


def brand_tokens(brands: Optional[str]) -> set[str]:
    """Normalized entries of a comma-separated brand string."""
    return {token for token in (normalize_key(part) for part in (brands or '').split(',')) if token}


def language_entries(entries) -> list[dict]:
    """Cleaned ``{lang, text}`` entries with empty texts dropped."""
    result = []
    for entry in entries or []:
        text = clean_text(entry.get('text'))
        if text:
            result.append({'lang': entry.get('lang'), 'text': text})
    return result


def main_entry(entries: list[dict]) -> Optional[dict]:
    for entry in entries:
        if entry['lang'] == 'main':
            return entry
    return entries[0] if entries else None


def finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def nutrients_per_100(nutriments) -> tuple[dict[str, Optional[float]], list[str]]:
    """Per-100 g/ml values in grams (kcal for energy) and the names set aside as implausible."""
    values: dict[str, Optional[float]] = {column: None for column, _ in NUTRIENT_COLUMNS.values()}
    implausible = []
    for item in nutriments or []:
        name = item.get('name')
        if name not in NUTRIENT_COLUMNS:
            continue
        column, upper = NUTRIENT_COLUMNS[name]
        raw = item.get('100g')
        if not finite_number(raw):
            continue
        if raw < 0 or raw > upper:
            implausible.append(name)
            continue
        values[column] = float(raw)
    return values, implausible


def environmental_score(data) -> dict:
    """Score in the fixed context plus provenance; all ``None`` when the status is not known."""
    result = {'environmental_score': None, 'environmental_score_world': None,
              'environmental_grade': None, 'agribalyse_version': None,
              'environmental_missing_key_data': None}
    if not data:
        return result
    parsed = json.loads(data) if isinstance(data, str) else data
    if parsed.get('status') != 'known':
        return result
    scores = parsed.get('scores') or {}
    grades = parsed.get('grades') or {}
    context_score = scores.get(SCORE_CONTEXT)
    result.update({
        'environmental_score': float(context_score) if finite_number(context_score) else None,
        'environmental_score_world': float(scores['world']) if finite_number(scores.get('world')) else None,
        'environmental_grade': grades.get(SCORE_CONTEXT) or parsed.get('grade'),
        'agribalyse_version': (parsed.get('agribalyse') or {}).get('version'),
        'environmental_missing_key_data': bool(parsed.get('missing_key_data')),
    })
    return result


def assign_family(categories, families: dict[str, tuple[str, ...]] = FAMILIES) -> Optional[str]:
    tags = set(categories or [])
    for family, family_tags in families.items():
        if tags & set(family_tags):
            return family
    return None


def group_key(code: str, name: Optional[str], brands: Optional[str]) -> str:
    """``name|brand`` after normalization; products without a usable name stand alone."""
    normalized_name = normalize_key(name)
    if not normalized_name:
        return f'code:{code}'
    return f'{normalized_name}|{normalize_key(brands)}'


def build_record(row: dict) -> dict:
    """One comparable record. Family-size exclusions are added later by the builder."""
    names = language_entries(row.get('product_name'))
    ingredients = language_entries(row.get('ingredients_text'))
    name = main_entry(names)
    ingredient = main_entry(ingredients)
    unit = row.get('product_quantity_unit')
    comparison_unit = unit if unit in COMPARISON_UNITS else None
    nutrients, implausible = nutrients_per_100(row.get('nutriments'))
    score = environmental_score(row.get('environmental_score_data'))
    quantity = row.get('product_quantity')
    try:
        quantity = float(quantity) if quantity not in (None, '') else None
    except (TypeError, ValueError):
        quantity = None

    reasons = []
    if name is None:
        reasons.append('missing_name')
    if ingredient is None:
        reasons.append('missing_ingredients')
    if comparison_unit is None:
        reasons.append('unknown_comparison_unit')
    for nutrient in REQUIRED_NUTRIENTS:
        if nutrient in implausible:
            reasons.append(f'implausible_nutrient:{nutrient}')
        elif nutrients[NUTRIENT_COLUMNS[nutrient][0]] is None:
            reasons.append(f'missing_nutrient:{nutrient}')
    if score['environmental_score'] is None:
        reasons.append('missing_environmental_score')
    family = assign_family(row.get('categories_tags'))
    if family is None:
        reasons.append('not_in_selected_family')

    record = {
        'code': row['code'],
        'source_row': row.get('_source_row'),
        'source_snapshot': row.get('_source_snapshot', 'catalog'),
        'name': name['text'] if name else None,
        'name_lang': name['lang'] if name else None,
        'names_json': json.dumps(names, ensure_ascii=False),
        'brands': clean_text(row.get('brands')),
        'lang': row.get('lang'),
        'categories_tags': list(row.get('categories_tags') or []),
        'family': family,
        'ingredients_text': ingredient['text'] if ingredient else None,
        'ingredients_lang': ingredient['lang'] if ingredient else None,
        'ingredients_json': json.dumps(ingredients, ensure_ascii=False),
        'labels_tags': list(row.get('labels_tags') or []),
        'ingredients_analysis_tags': list(row.get('ingredients_analysis_tags') or []),
        'allergens_tags': list(row.get('allergens_tags') or []),
        'traces_tags': list(row.get('traces_tags') or []),
        'product_quantity': quantity,
        'comparison_unit': comparison_unit,
        'nutrition_data_per': row.get('nutrition_data_per') or None,
        **nutrients,
        'implausible_nutrients': implausible,
        **score,
        'environmental_score_context': SCORE_CONTEXT if score['environmental_score'] is not None else None,
        'group_key': group_key(row['code'], name['text'] if name else None, row.get('brands')),
        'exclusion_reasons': reasons,
        'last_modified_t': row.get('last_modified_t'),
    }
    return record


def finalize(records: list[dict], min_eligible: int = MIN_ELIGIBLE_PER_FAMILY) -> list[dict]:
    """Assign group ids/sizes, apply the family minimum and set ``eligible``."""
    groups: dict[str, int] = {}
    for record in records:
        groups.setdefault(record['group_key'], len(groups) + 1)
    sizes: dict[str, int] = {}
    for record in records:
        sizes[record['group_key']] = sizes.get(record['group_key'], 0) + 1
    provisional = {}
    for record in records:
        if record['family'] and not record['exclusion_reasons']:
            provisional[record['family']] = provisional.get(record['family'], 0) + 1
    for record in records:
        family = record['family']
        if family and provisional.get(family, 0) < min_eligible:
            record['exclusion_reasons'].append('family_below_minimum')
        record['group_id'] = groups[record['group_key']]
        record['group_size'] = sizes[record['group_key']]
        record['eligible'] = not record['exclusion_reasons']
    return records
