"""Does a multilingual embedding model save us from writing the dictionary?

The claim audit works because somebody hand-wrote term lists in five languages.
That does not scale: every new concept and every new language is more hand work.
This experiment tests whether sentence embeddings reach the same decisions from
an English-only seed.

Three systems label the same products for the same concepts:

  oracle     the full multilingual term list in contradictions.py
  en_terms   the English seed terms only, matched as words
  embedding  the English seed terms embedded, matched by cosine similarity

The oracle supplies the labels, so precision and recall below are agreement with
a careful human lexicon, not truth. The interesting number is whether the
embedding system recovers the non-English mentions that en_terms misses, using
the same English starting point. Matches the embedding system finds outside the
oracle are written out for hand review rather than counted as errors.

The decision threshold is chosen on a calibration split and reported on a
held-out split; it is never tuned on the reported numbers.

    python embed_match.py          # run the comparison
"""
import csv
import json
import pathlib
import re
import sys

import numpy as np

from contradictions import EXCEPTION_RE, find_concept, ingredient_clauses, name, rows

RESULTS = pathlib.Path(__file__).parent / 'results'
MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
SEED = 20261027
SAMPLE = 1500

# What a person writes on day one, before discovering that the database is
# mostly French. One short English phrase per concept sense.
EN_SEEDS = {
    'dairy': ['milk', 'cream', 'butter', 'cheese', 'whey', 'yogurt', 'lactose', 'casein'],
    'egg': ['egg', 'egg white', 'egg yolk'],
    'meat': ['meat', 'beef', 'pork', 'chicken', 'ham', 'bacon', 'gelatin', 'lard'],
    'fish': ['fish', 'tuna', 'salmon', 'anchovy', 'shrimp', 'cod'],
    'honey': ['honey'],
    'gluten': ['wheat', 'barley', 'rye', 'spelt', 'malt', 'semolina', 'wheat flour'],
    'palm': ['palm oil', 'palm fat'],
}
EN_RE = {c: [re.compile(r'\b' + re.escape(t) + r'\b') for t in terms] for c, terms in EN_SEEDS.items()}

# One seed can carry a whole concept's error rate. "spelt" is also the past tense
# of "spell", and the model places short unrelated words near it: sel (salt) 0.90,
# leek 0.92, choux 0.92. The ablation drops it and re-measures.
ABLATION = {'gluten': [t for t in EN_SEEDS['gluten'] if t != 'spelt']}


def items(text):
    """Ingredient items: comma and bracket separated fragments of a clause."""
    out = []
    for clause in ingredient_clauses(text):
        for piece in re.split(r'[,;()\[\]/*]|\s+-\s+', clause):
            piece = piece.strip(' .:%0123456789').strip()
            if 2 <= len(piece) <= 60 and len(piece.split()) <= 6:
                out.append(piece)
    return out


def en_term_hit(text, concept):
    """The English-only lexicon, with the same exception rules as the oracle."""
    for clause in ingredient_clauses(text):
        lowered = clause.lower()
        blocked = [m.span() for pattern in EXCEPTION_RE.get(concept, []) for m in pattern.finditer(lowered)]
        for pattern in EN_RE[concept]:
            for match in pattern.finditer(lowered):
                start, end = match.span()
                if not any(bs <= start and end <= be for bs, be in blocked):
                    return match.group(0)
    return None


def scores(matrix, labels, threshold):
    predicted = matrix >= threshold
    tp = int((predicted & labels).sum())
    fp = int((predicted & ~labels).sum())
    fn = int((~predicted & labels).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'precision': round(precision, 4), 'recall': round(recall, 4), 'f1': round(f1, 4),
            'tp': tp, 'fp': fp, 'fn': fn}


def main():
    from sentence_transformers import SentenceTransformer

    products = [(record, text) for record, text in rows()]
    rng = np.random.default_rng(SEED)
    picked = rng.choice(len(products), size=min(SAMPLE, len(products)), replace=False)
    products = [products[i] for i in picked]
    print(f'{len(products)} products with ingredient text')

    concepts = list(EN_SEEDS)
    oracle = {c: np.array([find_concept(t, c) is not None for _, t in products]) for c in concepts}
    en_hits = {c: np.array([en_term_hit(t, c) is not None for _, t in products]) for c in concepts}

    product_items = [items(text) for _, text in products]
    vocabulary = sorted({item.lower() for group in product_items for item in group})
    print(f'{len(vocabulary)} distinct ingredient items to embed')

    model = SentenceTransformer(MODEL_NAME)
    item_vectors = model.encode(vocabulary, batch_size=256, normalize_embeddings=True,
                                show_progress_bar=False)
    index = {item: i for i, item in enumerate(vocabulary)}

    similarity, seed_vectors = {}, {}
    for concept in concepts:
        seed_vectors[concept] = model.encode(EN_SEEDS[concept], normalize_embeddings=True)
        best = item_vectors @ seed_vectors[concept].T
        best = best.max(axis=1)
        similarity[concept] = np.array([
            max((best[index[item.lower()]] for item in group), default=0.0) for group in product_items])

    # Calibration/test split of products, then one threshold per concept.
    order = rng.permutation(len(products))
    calibration, test = order[:len(order) * 2 // 5], order[len(order) * 2 // 5:]
    report, finds = {}, []
    for concept in concepts:
        grid = np.arange(0.30, 0.95, 0.01)
        best_threshold = max(grid, key=lambda t: scores(similarity[concept][calibration],
                                                        oracle[concept][calibration], t)['f1'])
        report[concept] = {
            'oracle_positive_test': int(oracle[concept][test].sum()),
            'threshold': round(float(best_threshold), 2),
            'en_terms': scores(en_hits[concept][test].astype(float), oracle[concept][test], 0.5),
            'embedding': scores(similarity[concept][test], oracle[concept][test], best_threshold),
        }
        if concept in ABLATION:
            ablated = model.encode(ABLATION[concept], normalize_embeddings=True)
            ablated_sim = (item_vectors @ ablated.T).max(axis=1)
            per_product = np.array([max((ablated_sim[index[item.lower()]] for item in group), default=0.0)
                                    for group in product_items])
            ablated_threshold = max(np.arange(0.30, 0.95, 0.01),
                                    key=lambda t: scores(per_product[calibration],
                                                         oracle[concept][calibration], t)['f1'])
            report[concept]['ablation_without_spelt'] = {
                'threshold': round(float(ablated_threshold), 2),
                **scores(per_product[test], oracle[concept][test], ablated_threshold)}
        for i in test:
            if similarity[concept][i] >= best_threshold and not oracle[concept][i]:
                record, text = products[i]
                closest = max(items(text), default='',
                              key=lambda item: float((item_vectors[index[item.lower()]] @
                                                      seed_vectors[concept].T).max()))
                finds.append({'code': record['code'], 'name': name(record), 'concept': concept,
                              'similarity': round(float(similarity[concept][i]), 3),
                              'closest_item': closest, 'ingredients': text[:200]})

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / 'embedding_comparison.json').write_text(json.dumps(
        {'model': MODEL_NAME, 'seed': SEED, 'products': len(products),
         'calibration_n': len(calibration), 'test_n': len(test),
         'labels': 'oracle = multilingual term list in contradictions.py; agreement, not truth',
         'per_concept': report}, indent=2) + '\n')
    finds.sort(key=lambda row: -row['similarity'])
    with open(RESULTS / 'embedding_finds.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['code', 'name', 'concept', 'similarity',
                                                    'closest_item', 'ingredients'])
        writer.writeheader()
        writer.writerows(finds[:120])

    print(f"\n{'concept':8s} {'pos':>4s}  {'en_terms R':>10s} {'embed R':>8s}  "
          f"{'en_terms P':>10s} {'embed P':>8s}  thr")
    for concept, row in report.items():
        print(f"{concept:8s} {row['oracle_positive_test']:4d}  {row['en_terms']['recall']:10.3f} "
              f"{row['embedding']['recall']:8.3f}  {row['en_terms']['precision']:10.3f} "
              f"{row['embedding']['precision']:8.3f}  {row['threshold']:.2f}")
    print(f'\n{len(finds)} matches outside the oracle written to results/embedding_finds.csv')


if __name__ == '__main__':
    sys.exit(main() or 0)
