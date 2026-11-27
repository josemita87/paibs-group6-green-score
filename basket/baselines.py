"""Rank substitution candidates without a trained model (pipeline step 6).

Four baselines score an ordered product pair; a higher score ranks first:

- ``category_rules`` rejects a candidate of another family or comparison unit and
  otherwise scores how close the two products are on protein, sugars and salt.
- ``tfidf_char`` is the cosine of character 4-gram TF-IDF vectors of the name and
  the ingredient text. Document frequencies come from the train partition only.
- ``frozen_encoder`` is the cosine of stored embeddings from a pretrained
  multilingual encoder whose weights were not updated (``basket/embeddings.py``).
  It can be negative.
- ``random_control`` is a seeded hash of the pair id. It measures nothing and gives
  the others a reference: its mean percentile is near 0.5 by construction.

A score ranks candidates. It is not a probability and no baseline was trained on
a label, because no human label exists yet.
"""
from collections import Counter
import hashlib
import math

from basket.comparable import normalize_key

NGRAM = 4
SCORE_DIGITS = 6
# Nutrient column -> the denominator floor that keeps small values from dominating.
RULE_NUTRIENTS: dict[str, float] = {
    'proteins_g_per_100': 1.0, 'sugars_g_per_100': 1.0, 'salt_g_per_100': 0.1,
}
BASELINES = ('category_rules', 'tfidf_char', 'frozen_encoder', 'random_control')


def product_text(row) -> str:
    """The normalized name and ingredient text a text baseline reads."""
    return normalize_key(f"{row['name'] or ''} {row['ingredients_text'] or ''}")


def ngrams(text: str, size: int = NGRAM) -> Counter:
    """Character n-grams of the text padded with one space; empty text yields nothing."""
    if not text:
        return Counter()
    padded = f' {text} '
    if len(padded) <= size:
        return Counter([padded])
    return Counter(padded[index:index + size] for index in range(len(padded) - size + 1))


def document_frequencies(texts) -> tuple[dict[str, int], int]:
    """How many documents hold each n-gram, with the document count."""
    frequencies: Counter = Counter()
    total = 0
    for text in texts:
        total += 1
        frequencies.update(set(ngrams(text)))
    return dict(frequencies), total


def tfidf_vector(text: str, frequencies: dict[str, int], documents: int) -> dict[str, float]:
    """L2-normalized TF-IDF weights; an n-gram unseen in the fit corpus has frequency 0."""
    weights = {}
    for gram, count in ngrams(text).items():
        idf = math.log((documents + 1) / (frequencies.get(gram, 0) + 1)) + 1
        weights[gram] = (1 + math.log(count)) * idf
    norm = math.sqrt(sum(weight * weight for weight in weights.values()))
    return {gram: weight / norm for gram, weight in weights.items()} if norm else {}


def cosine(first: dict[str, float], second: dict[str, float]) -> float:
    if len(first) > len(second):
        first, second = second, first
    return sum(weight * second.get(gram, 0.0) for gram, weight in first.items())


def nutrient_distance(original, candidate) -> float:
    """Mean relative difference over protein, sugars and salt, each capped at 1."""
    distances = []
    for column, floor in RULE_NUTRIENTS.items():
        first, second = original[column], candidate[column]
        if first is None or second is None:
            distances.append(1.0)
            continue
        denominator = max(abs(first), abs(second), floor)
        distances.append(min(1.0, abs(first - second) / denominator))
    return sum(distances) / len(distances)


def category_rules(original, candidate) -> float:
    """0 for another family or comparison unit, otherwise nutritional closeness."""
    if original['family'] != candidate['family']:
        return 0.0
    if original['comparison_unit'] != candidate['comparison_unit']:
        return 0.0
    return 1.0 - nutrient_distance(original, candidate)


def random_control(original, candidate, seed: str) -> float:
    """A seeded hash of the two barcodes, uniform in [0, 1) and reproducible."""
    digest = hashlib.sha256(f"{seed}|{original['code']}|{candidate['code']}".encode()).digest()
    return int.from_bytes(digest[:8], 'big') / 2 ** 64


class Baselines:
    """The baselines over one catalog, with the TF-IDF fit corpus recorded.

    ``embeddings`` is a ``StoredEmbeddings``; without it ``frozen_encoder`` cannot score.
    """

    def __init__(self, products: dict[int, dict], fit_group_ids, seed: str, embeddings=None):
        self.products = products
        self.seed = seed
        self.embeddings = embeddings
        texts = {group_id: product_text(row) for group_id, row in products.items()}
        frequencies, documents = document_frequencies(texts[group_id]
                                                      for group_id in sorted(fit_group_ids))
        self.vectors = {group_id: tfidf_vector(text, frequencies, documents)
                        for group_id, text in texts.items()}

    def score(self, baseline: str, original_id: int, candidate_id: int) -> float:
        original, candidate = self.products[original_id], self.products[candidate_id]
        if baseline == 'category_rules':
            value = category_rules(original, candidate)
        elif baseline == 'tfidf_char':
            value = cosine(self.vectors[original_id], self.vectors[candidate_id])
        elif baseline == 'frozen_encoder':
            if self.embeddings is None:
                raise ValueError('frozen_encoder needs stored embeddings')
            value = self.embeddings.cosine(original_id, candidate_id)
        elif baseline == 'random_control':
            value = random_control(original, candidate, self.seed)
        else:
            raise ValueError(f'Unknown baseline: {baseline}')
        return round(value, SCORE_DIGITS)

    def rank(self, baseline: str, original_id: int, pool) -> list[tuple[int, float]]:
        """The pool ordered by score, highest first, ties broken by barcode."""
        scored = [(group_id, self.score(baseline, original_id, group_id)) for group_id in pool]
        scored.sort(key=lambda item: (-item[1], self.products[item[0]]['code']))
        return scored


def rank_of(ranking, group_id: int) -> int:
    """1-based position of a group in a ranking."""
    return [candidate for candidate, _ in ranking].index(group_id) + 1


def percentile(rank: int, pool_size: int) -> float:
    """Share of the pool ranked below the candidate; 1.0 is the top of a full pool."""
    return 1.0 if pool_size <= 1 else round((pool_size - rank) / (pool_size - 1), 4)


def roc_auc(positives, negatives) -> float:
    """Probability that a positive outranks a negative, ties counted as a half."""
    wins = sum((first > second) + 0.5 * (first == second)
               for first in positives for second in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)
