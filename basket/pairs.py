"""Build unlabeled substitution annotation pairs inside frozen partitions (pipeline step 4).

Every pair joins two eligible product groups of one family that sit in the same
partition of ``data/partitions.json`` and in different split units, so no pair can
leak a near-duplicate across partitions and no pair compares a group with itself.
Calibration groups stay reserved for the pilot and are never used here.

Three sampling strategies share the budget of each family and partition:

- ``lookalike``: the most name-similar cross-unit pairs, the hard cases a text
  baseline is most likely to rank as substitutes.
- ``brand_variant``: pairs sharing a brand entry whose names have little in common,
  which usually means another flavor or format of one product line.
- ``family_random``: pairs with no shared brand and little name overlap, which give
  the easy negatives a label set needs.

This module selects pairs and records how each was chosen. It writes no label and
makes no substitutability judgement.
"""
from collections import Counter
import hashlib
from itertools import combinations

from basket.comparable import brand_tokens, normalize_key

VERSION = 'pairs-v1'
SEED = 'basket-optimizer-pairs-v1'
STRATEGIES = ('lookalike', 'brand_variant', 'family_random')
# Pairs per family in each partition. Calibration keeps the 36 pilot pairs only.
BUDGETS: dict[str, int] = {'train': 60, 'validation': 20, 'test': 20}
MAX_PAIRS_PER_GROUP = 3
LOOKALIKE_MIN_JACCARD = 0.4   # below this, two names no longer look alike
PAIR_FIELDS = ('code', 'group_id', 'name', 'brands', 'lang', 'ingredients_text')


def representatives(rows) -> dict[int, dict]:
    """One eligible row per group: the lowest barcode, as in every other step."""
    chosen: dict[int, dict] = {}
    for row in sorted(rows, key=lambda row: row['code']):
        if row['eligible']:
            chosen.setdefault(row['group_id'], row)
    return chosen


def name_tokens(row) -> set[str]:
    return set(normalize_key(row['name']).split())


def jaccard(first: set[str], second: set[str]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def tie_break(pair_id: str, seed: str = SEED) -> bytes:
    return hashlib.sha256(f'{seed}|{pair_id}'.encode()).digest()


def pair_id(partition: str, family: str, original: dict, candidate: dict) -> str:
    return f"{VERSION}/{partition}/{family}/{original['code']}/{candidate['code']}"


def describe(pair_id_value, partition, family, unit, context, original, candidate,
             strategy, similarity, shared_brand) -> dict:
    """One Label Studio task: the same fields as the pilot plus how the pair was chosen."""
    data = {
        'pair_id': pair_id_value, 'partition': partition, 'family': family,
        'comparison_unit': unit, 'context': context, 'strategy': strategy,
        'name_jaccard': round(similarity, 4), 'shared_brand': shared_brand,
    }
    for role, product in (('original', original), ('candidate', candidate)):
        for field in PAIR_FIELDS:
            data[f'{role}_{field}'] = product[field]
    return data


def candidates(group_ids, products, unit_of):
    """Every cross-unit pair with its name overlap and brand evidence, lowest barcode first."""
    tokens = {group_id: name_tokens(products[group_id]) for group_id in group_ids}
    brands = {group_id: brand_tokens(products[group_id]['brands']) for group_id in group_ids}
    for pair in combinations(sorted(group_ids), 2):
        if unit_of[pair[0]] != unit_of[pair[1]]:
            first, second = sorted(pair, key=lambda group_id: products[group_id]['code'])
            yield ((first, second), jaccard(tokens[first], tokens[second]),
                   bool(brands[first] & brands[second]))


def strategy_of(similarity: float, shared_brand: bool) -> str:
    """The one strategy a candidate pair belongs to; name overlap decides before the brand."""
    if similarity >= LOOKALIKE_MIN_JACCARD:
        return 'lookalike'
    return 'brand_variant' if shared_brand else 'family_random'


def select(pool, products, unit_of, partition, family, budget, seed=SEED):
    """Choose up to ``budget`` pairs, split evenly over the strategies.

    Pairs are taken in descending name overlap for ``lookalike`` and in seeded hash
    order otherwise, skipping any group already used ``MAX_PAIRS_PER_GROUP`` times.
    """
    ranked: dict[str, list] = {strategy: [] for strategy in STRATEGIES}
    for (first, second), similarity, shared_brand in candidates(pool, products, unit_of):
        identifier = pair_id(partition, family, products[first], products[second])
        ranked[strategy_of(similarity, shared_brand)].append(
            (identifier, (first, second), similarity, shared_brand))
    ranked['lookalike'].sort(key=lambda item: (-item[2], tie_break(item[0], seed)))
    for strategy in ('brand_variant', 'family_random'):
        ranked[strategy].sort(key=lambda item: tie_break(item[0], seed))

    share = budget // len(STRATEGIES)
    quotas = {strategy: share for strategy in STRATEGIES}
    quotas['lookalike'] += budget - share * len(STRATEGIES)

    selected, used = [], Counter()
    for strategy in STRATEGIES:
        taken = 0
        for identifier, (first, second), similarity, shared_brand in ranked[strategy]:
            if taken == quotas[strategy]:
                break
            if max(used[first], used[second]) >= MAX_PAIRS_PER_GROUP:
                continue
            used[first] += 1
            used[second] += 1
            taken += 1
            selected.append((identifier, strategy, (first, second), similarity, shared_brand))
    return selected, quotas


def build_pairs(rows, partitions, contexts, catalog_hash: str) -> dict:
    """The complete pair file: parameters, per-partition counts, shortfalls and tasks."""
    products = representatives(rows)
    unit_of = {group_id: unit['unit_id'] for unit in partitions['units']
               for group_id in unit['group_ids']}
    partition_of = {group_id: unit['partition'] for unit in partitions['units']
                    for group_id in unit['group_ids']}

    tasks, counts, shortfalls = [], {}, {}
    for family, (unit, context) in sorted(contexts.items()):
        counts[family] = {}
        for partition, budget in sorted(BUDGETS.items()):
            pool = [group_id for group_id, row in products.items()
                    if row['family'] == family and partition_of.get(group_id) == partition]
            selected, quotas = select(pool, products, unit_of, partition, family, budget)
            taken = Counter(strategy for _, strategy, _, _, _ in selected)
            counts[family][partition] = {'groups_available': len(pool), 'pairs': len(selected),
                                         **{strategy: taken[strategy] for strategy in STRATEGIES}}
            for strategy in STRATEGIES:
                if taken[strategy] < quotas[strategy]:
                    shortfalls[f'{family}|{partition}|{strategy}'] = {
                        'requested': quotas[strategy], 'selected': taken[strategy]}
            for identifier, strategy, (first, second), similarity, shared_brand in selected:
                tasks.append({'data': describe(identifier, partition, family, unit, context,
                                               products[first], products[second], strategy,
                                               similarity, shared_brand)})
    # Mix families, partitions and strategies in the order presented to reviewers.
    tasks.sort(key=lambda task: tie_break(task['data']['pair_id']))
    for task in tasks:
        task['data']['catalog_content_sha256'] = catalog_hash

    return {
        'version': VERSION,
        'catalog_content_sha256': catalog_hash,
        'partitions_version': partitions['version'],
        'parameters': {
            'seed': SEED,
            'budget_per_family': dict(BUDGETS),
            'strategies': list(STRATEGIES),
            'lookalike_min_jaccard': LOOKALIKE_MIN_JACCARD,
            'max_pairs_per_group': MAX_PAIRS_PER_GROUP,
            'pair_rule': 'both groups eligible, same family and partition, different split units',
            'representative': 'lowest eligible barcode of the group',
        },
        'pairs_total': len(tasks),
        'counts': counts,
        'shortfalls': shortfalls,
        'tasks': tasks,
        'note': ('Unlabeled pairs for human review with the step-4 form. Calibration groups are '
                 'reserved for the pilot and excluded. A strategy records how a pair was sampled, '
                 'not whether the products substitute for each other. Changing the seed, a '
                 'threshold, the budgets, the catalog or the partitions requires a new version.'),
    }
