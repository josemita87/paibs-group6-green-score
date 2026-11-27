"""Build unlabeled annotation pairs around anchor products (pipeline step 4).

A training triplet needs one original with an acceptable and an unacceptable
candidate. ``pairs-v1`` gives most originals a single pair, so it allows few
triplets. This set fixes anchor products and gives each several candidates:

- ``same_format``: candidates with no evidence of another format, like the anchor.
- ``other_format``: candidates whose name or ingredients suggest another format
  (``basket/formats.py``), where the pilot found its unacceptable pairs.

Anchors and candidates are drawn in seeded hash order. No similarity score chooses
a pair, so no baseline is favored by the sampling. Every pair stays inside one
partition and one family, joins two split units and avoids calibration groups.

A strategy records how a candidate was drawn. It is not a label.
"""
from collections import Counter

from basket.comparable import brand_tokens
from basket.formats import format_evidence
from basket.pairs import PAIR_FIELDS, jaccard, name_tokens, representatives, tie_break

VERSION = 'anchored-pairs-v1'
SEED = 'basket-optimizer-anchored-pairs-v1'
STRATEGIES = ('same_format', 'other_format')
# Anchors per family in each partition, and candidates per anchor for each strategy.
ANCHORS: dict[str, int] = {'train': 16, 'validation': 8, 'test': 8}
CANDIDATES_PER_ANCHOR: dict[str, int] = {'same_format': 2, 'other_format': 2}
MAX_USES_PER_CANDIDATE = 3


def pair_id(partition: str, family: str, anchor: dict, candidate: dict) -> str:
    return f"{VERSION}/{partition}/{family}/{anchor['code']}/{candidate['code']}"


def choose(pool, flagged, products, unit_of, partition, family, anchors, taken_pairs, seed=SEED):
    """Return ``(anchor ids, [(anchor, candidate, strategy)])`` for one family and partition.

    ``pool`` holds the groups that may be used, ``flagged`` those with format
    evidence, ``taken_pairs`` unordered group pairs that another pair set holds.
    Candidates are handed out one round at a time so that a scarce strategy
    reaches as many anchors as possible.
    """
    plain = sorted((group_id for group_id in pool if group_id not in flagged),
                   key=lambda group_id: tie_break(f"anchor|{products[group_id]['code']}", seed))
    chosen = plain[:anchors]
    sources = {'same_format': plain[anchors:],
               'other_format': [group_id for group_id in pool if group_id in flagged]}
    used, selected = Counter(), []
    paired = {frozenset(pair) for pair in taken_pairs}
    for strategy in STRATEGIES:
        # Each anchor sees the candidates of a strategy in its own seeded order.
        order = {anchor: sorted(sources[strategy], key=lambda group_id: tie_break(
            pair_id(partition, family, products[anchor], products[group_id]), seed))
            for anchor in chosen}
        for _ in range(CANDIDATES_PER_ANCHOR[strategy]):
            for anchor in chosen:
                for candidate in order[anchor]:
                    if (used[candidate] < MAX_USES_PER_CANDIDATE
                            and unit_of[candidate] != unit_of[anchor]
                            and frozenset((anchor, candidate)) not in paired):
                        used[candidate] += 1
                        paired.add(frozenset((anchor, candidate)))
                        selected.append((anchor, candidate, strategy))
                        break
    return chosen, selected


def describe(partition, family, unit, context, anchor, candidate, strategy, evidence) -> dict:
    """One Label Studio task in the step-4 form, the anchor as the original."""
    data = {
        'pair_id': pair_id(partition, family, anchor, candidate), 'partition': partition,
        'family': family, 'comparison_unit': unit, 'context': context, 'strategy': strategy,
        'name_jaccard': round(jaccard(name_tokens(anchor), name_tokens(candidate)), 4),
        'shared_brand': bool(brand_tokens(anchor['brands']) & brand_tokens(candidate['brands'])),
        'candidate_format_evidence': evidence,
    }
    for role, product in (('original', anchor), ('candidate', candidate)):
        for field in PAIR_FIELDS:
            data[f'{role}_{field}'] = product[field]
    return data


def triplet_ceiling(sizes) -> int:
    """Most triplets a set of anchors can give, from each anchor's candidate count."""
    return sum((size // 2) * (size - size // 2) for size in sizes)


def build_anchored_pairs(rows, partitions, contexts, catalog_hash: str, other_tasks=()) -> dict:
    """The complete pair file: parameters, counts, shortfalls and unlabeled tasks.

    ``other_tasks`` are the tasks of earlier pair sets; their group pairs are not
    drawn again in either direction.
    """
    products = representatives(rows)
    unit_of = {group_id: unit['unit_id'] for unit in partitions['units']
               for group_id in unit['group_ids']}
    partition_of = {group_id: unit['partition'] for unit in partitions['units']
                    for group_id in unit['group_ids']}
    evidence = {group_id: format_evidence(row) for group_id, row in products.items()}
    taken = [(task['data']['original_group_id'], task['data']['candidate_group_id'])
             for task in other_tasks]

    tasks, counts, shortfalls = [], {}, {}
    for family, (unit, context) in sorted(contexts.items()):
        counts[family] = {}
        for partition, anchors in sorted(ANCHORS.items()):
            pool = [group_id for group_id, row in products.items()
                    if row['family'] == family and row['comparison_unit'] == unit
                    and partition_of.get(group_id) == partition]
            flagged = {group_id for group_id in pool if evidence[group_id]}
            chosen, selected = choose(pool, flagged, products, unit_of, partition, family,
                                      anchors, taken)
            by_strategy = Counter(strategy for _, _, strategy in selected)
            per_anchor = Counter(anchor for anchor, _, _ in selected)
            mixed = sum(1 for anchor in chosen if {strategy for a, _, strategy in selected
                                                   if a == anchor} == set(STRATEGIES))
            counts[family][partition] = {
                'groups_available': len(pool), 'groups_with_format_evidence': len(flagged),
                'anchors': len(chosen), 'pairs': len(selected),
                **{strategy: by_strategy[strategy] for strategy in STRATEGIES},
                'anchors_with_both_strategies': mixed,
                'triplet_ceiling': triplet_ceiling(per_anchor.values()),
            }
            if len(chosen) < anchors:
                shortfalls[f'{family}|{partition}|anchors'] = {
                    'requested': anchors, 'selected': len(chosen)}
            for strategy in STRATEGIES:
                requested = len(chosen) * CANDIDATES_PER_ANCHOR[strategy]
                if by_strategy[strategy] < requested:
                    shortfalls[f'{family}|{partition}|{strategy}'] = {
                        'requested': requested, 'selected': by_strategy[strategy]}
            for anchor, candidate, strategy in selected:
                tasks.append({'data': describe(partition, family, unit, context, products[anchor],
                                               products[candidate], strategy,
                                               evidence[candidate])})
    # Mix families, partitions and strategies in the order presented to reviewers.
    tasks.sort(key=lambda task: tie_break(task['data']['pair_id'], SEED))
    for task in tasks:
        task['data']['catalog_content_sha256'] = catalog_hash

    return {
        'version': VERSION,
        'catalog_content_sha256': catalog_hash,
        'partitions_version': partitions['version'],
        'parameters': {
            'seed': SEED,
            'anchors_per_family': dict(ANCHORS),
            'candidates_per_anchor': dict(CANDIDATES_PER_ANCHOR),
            'max_uses_per_candidate': MAX_USES_PER_CANDIDATE,
            'anchor_rule': ('eligible group in the family unit with no format evidence, '
                            'in seeded hash order'),
            'pair_rule': ('anchor and candidate eligible, same family, unit and partition, '
                          'different split units, not paired in an earlier pair set'),
            'format_evidence': 'keyword rules on name, brand and ingredients (basket/formats.py)',
            'representative': 'lowest eligible barcode of the group',
            'excluded_earlier_pairs': len(taken),
        },
        'pairs_total': len(tasks),
        'anchors_total': sum(c['anchors'] for family in counts.values() for c in family.values()),
        'triplet_ceiling': sum(c['triplet_ceiling'] for family in counts.values()
                               for c in family.values()),
        'counts': counts,
        'shortfalls': shortfalls,
        'tasks': tasks,
        'note': ('Unlabeled pairs for human review with the step-4 form; the anchor is the '
                 'original. A strategy and its format evidence record how a candidate was drawn, '
                 'not whether it substitutes. The triplet ceiling assumes the labels fall evenly '
                 'and is not a count of triplets. Changing the seed, a budget, the format rules, '
                 'the catalog or the partitions requires a new version.'),
    }
