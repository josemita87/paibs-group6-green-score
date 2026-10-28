"""Flag products whose label claim contradicts their own ingredient list.

This is the deterministic baseline for the claim-audit experiment: multilingual
term lists with explicit exceptions, no learning. An embedding matcher is
evaluated against these numbers, so the lists are written to be as strong as a
careful person would make them by hand, not as a strawman.

    python contradictions.py scan     # write results/contradictions.csv
    python contradictions.py test     # self-checks on known tricky strings

Nothing here is a verdict on a product. A flag is a request for a human to look
at the record; the ingredient text itself can be wrong, outdated or truncated.
"""
import csv
import gzip
import json
import pathlib
import re
import sys
from collections import Counter

DATA = pathlib.Path(__file__).parent / 'data' / 'off_sample.jsonl.gz'
RESULTS = pathlib.Path(__file__).parent / 'results'

# Terms are matched on word boundaries over lowercased text. Languages follow the
# sample: French dominates, then English, Spanish, Italian and German.
CONCEPTS = {
    'dairy': [r'lait', r'milk', r'leche', r'latte', r'milch', r'cream', r'cr[eè]me', r'nata', r'panna',
              r'butter', r'beurre', r'mantequilla', r'burro', r'cheese', r'fromage', r'queso', r'formaggio',
              r'whey', r'lactos[eé]rum', r'petit-lait', r'suero', r'casein[ae]?', r'cas[eé]inate',
              r'caseinato', r'lactose', r'lactosa', r'yogh?urts?', r'yaourts?', r'yogur', r'ghee', r'kefir'],
    'egg': [r'eggs?', r'(oe|œ)ufs?', r'huevos?', r'uovo', r'uova', r'albumin[ae]?', r'ovoproduit',
            r'ovoprodotto'],
    'meat': [r'meat', r'viande', r'carne', r'fleisch', r'beef', r'b[oœ]uf', r'manzo', r'pork', r'porc',
             r'cerdo', r'maiale', r'chicken', r'poulet', r'pollo', r'turkey', r'dinde', r'pavo',
             r'ham', r'jambon', r'jam[oó]n', r'prosciutto', r'bacon', r'lard', r'saindoux', r'strutto',
             r'g[eé]latin[ae]?', r'gelatina', r'gelatine', r'suif', r'tallow'],
    'fish': [r'fish', r'poisson', r'pescado', r'pesce', r'anchoi?s', r'anchoa', r'acciugh[ae]',
             r'tuna', r'thon', r'at[uú]n', r'tonno', r'salmon', r'saumon', r'salm[oó]n', r'salmone',
             r'crevette', r'shrimp', r'gamba', r'morue', r'bacalao', r'sardine', r'sardina'],
    'honey': [r'honey', r'miel', r'miele', r'honig'],
    'gluten': [r'wheat', r'bl[eé]', r'trigo', r'frumento', r'weizen', r'barley', r'orge', r'cebada',
               r'orzo', r'rye', r'seigle', r'centeno', r'segale', r'spelt', r'[eé]peautre', r'espelta',
               r'semoule', r'semolina', r's[eé]mola', r'malt', r'malte', r'malta', r'gluten'],
    'palm': [r'palme?', r'palma'],
}

# A match is dropped when an exception pattern covers it. These are the cases a
# careful reader would never flag: cocoa butter is not dairy, coconut milk is not
# dairy, maltodextrin is not a gluten source, "sans huile de palme" is the claim
# itself appearing in the ingredient text.
EXCEPTIONS = {
    'dairy': [r'beurre\s+de\s+(cacao|karit[eé]|cacahu[eè]te|arachide)', r'(cocoa|shea|peanut)\s+butter',
              r'manteca\s+de\s+(cacao|cacahuete)', r'burro\s+di\s+cacao',
              r'lait\s+de\s+(coco|soja|soya|riz|avoine|amande|noisette)', r'leche\s+de\s+(coco|soja|arroz|avena|almendra)',
              r'(coconut|soy|soya|rice|oat|almond|hazelnut|cashew)\s+milk', r'latte\s+di\s+(cocco|soia|riso|avena|mandorla)',
              r'cr[eè]me\s+de\s+(coco|soja|riz|cassis|marron)', r'coconut\s+cream', r'cr[eè]me\s+v[eé]g[eé]tale',
              r'sans\s+lactose', r'lactose[- ]free', r'd[eé]lactos[eé]', r'sin\s+lactosa',
              r'(yaourt|yogh?urt|yogur|lait|cr[eè]me|fromage|beurre|queso)\s+(v[eé]g[eé]tal\w*|vegan|de\s+soja)',
              r'beurre\s+de\s+cacao', r'cream\s+of\s+tartar', r'cr[eè]me\s+de\s+tartre'],
    'egg': [r'sans\s+[oœ]ufs?', r'egg[- ]free', r'sin\s+huevo'],
    'meat': [r'sans\s+viande', r'meat[- ]free', r'carne\s+vegetal', r'viande\s+v[eé]g[eé]tale',
             r'g[eé]latine\s+v[eé]g[eé]tale', r'carnauba'],
    'fish': [r'sans\s+poisson', r'fish[- ]free'],
    'honey': [r'sans\s+miel', r'honey[- ]free'],
    'gluten': [r'sans\s+gluten', r'gluten[- ]free', r'sin\s+gluten', r'senza\s+glutine', r'glutenfrei',
               r'maltodextrin[ae]?', r'maltodextrine', r'maltitol', r'malt[ií]tol',
               r'amidon\s+de\s+bl[eé]\s+sans\s+gluten', r'sarrasin', r'buckwheat',
               r'gluten\s*-?\s*(and|und|et|y)\s+\w+[- ]free', r'f[aă]r[aă]\s+gluten',
               r'(s[eé]mol[ae]|semoule|semolina)\s+(de\s+|di\s+)?(ma[ií]z|ma[ïi]s|corn|riz|rice|arroz)',
               r'(corn|rice|maize)\s+semolina'],
    'palm': [r'sans\s+(huile\s+de\s+)?palme?', r'palm[- ]oil[- ]free', r'sin\s+(aceite\s+de\s+)?palma',
             r'senza\s+olio\s+di\s+palma', r'non\s+issue\s+de\s+palme', r'palmitate', r'palmitoyl',
             r'c[oœ]ur\s+de\s+palmier', r'hearts?\s+of\s+palm', r'palmier'],
}

# claim tag -> (concepts that contradict it, tier). "review" means the pairing is
# commonly legitimate and needs a person, not that it is wrong.
CLAIMS = {
    'en:vegan': (['dairy', 'egg', 'meat', 'fish', 'honey'], 'contradiction'),
    'en:vegetarian': (['meat', 'fish'], 'contradiction'),
    'en:no-gluten': (['gluten'], 'review'),
    'en:no-lactose': (['dairy'], 'review'),
    'en:no-palm-oil': (['palm'], 'contradiction'),
}

# A clause matching one of these is a cross-contamination warning, not a list of
# what is in the product. "May contain traces of milk" is normal on a vegan
# product and must never be read as dairy content. Dropping these clauses is the
# single largest source of false positives in the first version of this scan.
TRACE = re.compile(r'(peu(t|vent)\s+contenir|traces?\s+[eé]ventuelles?|traces?\s+de|may\s+contain|'
                   r'kann\s+[^.;]{0,80}?enthalten|spuren\s+von|pu[oò]\s+contenere|puede\s+contener|'
                   r'contiene\s+trazas|fabriqu[eé]\s+dans|hergestellt\s+in\s+einem\s+betrieb|'
                   r'produced\s+in\s+a\s+(facility|factory)|prodotto\s+in\s+uno\s+stabilimento|'
                   r'elaborado\s+en\s+una\s+(f[aá]brica|instalaci[oó]n))')

# A negation immediately before a term flips its meaning: "ohne Fleisch",
# "sans lait", "senza latte", "free from milk".
NEGATION = re.compile(r'(sans|ohne|senza|sin|no|non|f[aă]r[aă]|free\s+from|without)\s+(\w+\s+){0,3}$')

CONCEPT_RE = {c: [re.compile(r'\b' + p + r'\b') for p in pats] for c, pats in CONCEPTS.items()}
EXCEPTION_RE = {c: [re.compile(p) for p in pats] for c, pats in EXCEPTIONS.items()}


def ingredient_clauses(text):
    """Split into clauses and drop cross-contamination warnings."""
    return [c for c in re.split(r'(?<=[.;!?])\s+|\n+', text) if c and not TRACE.search(c.lower())]


def find_concept(text, concept):
    """Return the first surviving match for a concept, or None.

    A candidate is dropped when an exception pattern's span covers it (so
    "beurre de cacao" is not dairy while a bare "beurre" is), when it sits in a
    cross-contamination warning, or when a negation precedes it.
    """
    for clause in ingredient_clauses(text):
        lowered = clause.lower()
        blocked = [m.span() for pattern in EXCEPTION_RE.get(concept, []) for m in pattern.finditer(lowered)]
        for pattern in CONCEPT_RE[concept]:
            for match in pattern.finditer(lowered):
                start, end = match.span()
                if any(bs <= start and end <= be for bs, be in blocked):
                    continue
                if NEGATION.search(lowered[:start]):
                    continue
                return match.group(0), clause[max(0, start - 40):min(len(clause), end + 40)]
    return None


def name(record):
    value = record.get('product_name') or ''
    if isinstance(value, list):
        value = next((p.get('text', '') for p in value if p.get('text')), '')
    return re.sub(r'\s+', ' ', str(value)).strip()


def rows():
    for line in gzip.open(DATA, 'rt'):
        record = json.loads(line)
        text = record.get('ingredients_text') or ''
        if isinstance(text, list):
            text = ' '.join(part.get('text', '') for part in text)
        text = re.sub(r'\s+', ' ', re.sub('<[^>]+>', ' ', text)).strip()
        if len(text) >= 15:
            yield record, text


def scan():
    flags, claim_totals = [], Counter()
    for record, text in rows():
        tags = record.get('labels_tags') or []
        for tag in tags:
            if tag not in CLAIMS:
                continue
            claim_totals[tag] += 1
            concepts, tier = CLAIMS[tag]
            for concept in concepts:
                hit = find_concept(text, concept)
                if hit:
                    term, evidence = hit
                    flags.append({'code': record['code'], 'name': name(record), 'language': record.get('lang', ''),
                                  'claim': tag, 'concept': concept, 'tier': tier, 'matched_term': term,
                                  'evidence': evidence, 'ingredients': text[:400]})
                    break
    return flags, claim_totals


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if command == 'test':
        return selfcheck()
    flags, claim_totals = scan()
    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / 'contradictions.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flags[0]) if flags else
                                ['code', 'name', 'language', 'claim', 'concept', 'tier', 'matched_term',
                                 'evidence', 'ingredients'])
        writer.writeheader()
        writer.writerows(flags)
    by_claim = Counter(f['claim'] for f in flags)
    summary = {'claims_checked': dict(claim_totals), 'flags_by_claim': dict(by_claim),
               'flags_by_tier': dict(Counter(f['tier'] for f in flags)),
               'flag_rate': {k: round(by_claim[k] / v, 4) for k, v in claim_totals.items() if v},
               'note': 'Keyword baseline with hand-written exceptions. Flags are review requests, '
                       'not confirmed label errors; ingredient text can itself be wrong or truncated.'}
    (RESULTS / 'contradictions_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for claim, checked in claim_totals.most_common():
        print(f'{claim:18s} checked {checked:5d}  flagged {by_claim[claim]:4d}')
    print(f'\n{len(flags)} flags written to results/contradictions.csv')


def selfcheck():
    cases = [
        ('dairy', 'Sucre, beurre de cacao, pâte de cacao', None),
        ('dairy', 'Sucre, beurre, farine', 'beurre'),
        ('dairy', 'Boisson au lait de coco, sucre', None),
        ('dairy', 'Lait entier, ferments lactiques', 'lait'),
        ('dairy', 'Protéines de lactosérum', 'lactosérum'),
        ('gluten', 'Amidon, maltodextrine de maïs', None),
        ('gluten', 'Farine de blé, eau, sel', 'blé'),
        ('palm', 'Huile de tournesol, sans huile de palme', None),
        ('palm', 'Huile de palme, sucre', 'palme'),
        ('palm', 'Coeur de palmier, eau, sel', None),
        ('meat', 'Gélatine de porc, sucre', {'gélatine', 'porc'}),
        ('meat', 'Cire de carnauba, sucre', None),
        ('dairy', 'Farine, sucre. Peut contenir des traces de lait.', None),
        ('dairy', 'Mehl, Zucker. Kann Spuren von Milch enthalten.', None),
        ('dairy', 'Flour, sugar. May contain traces of milk and peanuts.', None),
        ('dairy', 'Farina, zucchero. Puo contenere latte, uova.', None),
        ('meat', 'Gemuse, Gewurze, ohne Fleisch und ohne tierisches Eiweiss', None),
        ('dairy', 'Lait entier. Peut contenir des traces de soja.', 'lait'),
        ('dairy', 'Kann andere glutenhaltige Getreide, Milch, Ei enthalten.', None),
        ('dairy', 'Sucre, ferments de yaourt vegetalien', None),
        ('gluten', 'This product is gluten - and lactose-free, packed in a protective atmosphere', None),
        ('gluten', 'Fara gluten.', None),
        ('gluten', 'Harina de TRIGO integral 85%, aceite de girasol', 'trigo'),
        ('gluten', 'Semola de maiz (75%), aceite de girasol', None),
        ('egg', 'Flour, sugar, eggs, butter', 'eggs'),
        ('egg', 'Sucre, amandes, blanc d oeuf', 'oeuf'),
        ('egg', 'Harina de trigo, azucar, huevos', 'huevos'),
    ]
    failures = 0
    for concept, text, expected in cases:
        hit = find_concept(text, concept)
        found = hit[0] if hit else None
        ok = found in expected if isinstance(expected, set) else found == expected
        status = 'ok' if ok else 'FAIL'
        if status == 'FAIL':
            failures += 1
        print(f'{status:4s} {concept:7s} expected {str(expected):12s} got {str(found):12s} | {text}')
    print(f'\n{len(cases) - failures}/{len(cases)} self-checks passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main() or 0)
