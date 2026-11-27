"""Report candidate near-duplicate aliases among eligible product groups.

Step 3 groups products by exact normalized name and brand string, so a product
listed twice under ``Danone`` and ``Danone, Danonino`` lands in two groups. This
inspection links eligible groups of the same family that look like the same
product and proposes the merged clusters as split units for step 5.

It is a proposal for review. It does not change ``group_id``, freeze partitions or
label any pair, and a link is evidence of a shared listing, not of substitutability.
"""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.comparable import brand_tokens, normalize_key  # noqa: E402
from scripts.build_catalog import MANIFEST, PARQUET, content_sha256  # noqa: E402
from scripts.fetch_data import write_atomic  # noqa: E402

OUTPUT = ROOT / 'data/alias_report.json'
PILOT = ROOT / 'data/annotation_pilot.json'
MIN_INGREDIENT_CHARS = 40
NAME_JACCARD = 0.8
# Links that merge groups into one proposed split unit.
MERGE_SIGNALS = ('same_name_shared_brand', 'same_ingredients_shared_brand',
                 'similar_name_shared_brand')
# Links listed for a human decision; they do not merge groups.
REVIEW_SIGNALS = ('same_ingredients_other_brand',)


def group_profiles(rows):
    """Eligible groups with the evidence used for linking; lowest barcode names the group."""
    profiles = {}
    for row in sorted(rows, key=lambda r: r['code']):
        if not row['eligible']:
            continue
        profile = profiles.setdefault(row['group_id'], {
            'family': row['family'], 'name': row['name'], 'brands': row['brands'],
            'name_key': normalize_key(row['name']), 'brand_tokens': set(), 'ingredient_keys': set()})
        profile['brand_tokens'] |= brand_tokens(row['brands'])
        ingredients = normalize_key(row['ingredients_text'])
        if len(ingredients) >= MIN_INGREDIENT_CHARS:
            profile['ingredient_keys'].add(ingredients)
    for profile in profiles.values():
        profile['name_tokens'] = set(profile['name_key'].split())
    return profiles


def name_jaccard(first, second):
    union = first['name_tokens'] | second['name_tokens']
    return len(first['name_tokens'] & second['name_tokens']) / len(union) if union else 0.0


def same_brand_pairs(profiles):
    """Yield each pair of same-family groups sharing a brand entry once, with its name Jaccard."""
    by_brand = defaultdict(set)
    for group_id, profile in profiles.items():
        for token in profile['brand_tokens']:
            by_brand[(profile['family'], token)].add(group_id)
    seen = set()
    for members in by_brand.values():
        for pair in combinations(sorted(members), 2):
            if pair not in seen:
                seen.add(pair)
                yield pair, name_jaccard(profiles[pair[0]], profiles[pair[1]])


def find_links(profiles):
    """Return ``(links, same_name_other_brand_pairs, jaccard_histogram)``.

    ``links`` maps an ordered pair of group ids to the set of signals joining them.
    """
    links = defaultdict(set)
    by_name, by_ingredients = defaultdict(set), defaultdict(set)
    for group_id, profile in profiles.items():
        by_name[(profile['family'], profile['name_key'])].add(group_id)
        for key in profile['ingredient_keys']:
            by_ingredients[(profile['family'], key)].add(group_id)

    def shared_brand(first, second):
        return bool(profiles[first]['brand_tokens'] & profiles[second]['brand_tokens'])

    same_name_other_brand = 0
    for members in by_name.values():
        for pair in combinations(sorted(members), 2):
            if shared_brand(*pair):
                links[pair].add('same_name_shared_brand')
            else:
                same_name_other_brand += 1
    for members in by_ingredients.values():
        for pair in combinations(sorted(members), 2):
            links[pair].add('same_ingredients_shared_brand' if shared_brand(*pair)
                            else 'same_ingredients_other_brand')
    histogram = Counter()
    for pair, similarity in same_brand_pairs(profiles):
        histogram[f'{int(similarity * 10) / 10:.1f}'] += 1
        if similarity >= NAME_JACCARD and \
                profiles[pair[0]]['name_key'] != profiles[pair[1]]['name_key']:
            links[pair].add('similar_name_shared_brand')
    return dict(links), same_name_other_brand, dict(sorted(histogram.items()))


def merge_clusters(links):
    """Connected components over merge signals, as sorted lists of at least two groups."""
    parent = {}

    def find(item):
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for (first, second), signals in links.items():
        if signals & set(MERGE_SIGNALS):
            parent[find(second)] = find(first)
    components = defaultdict(list)
    for item in parent:
        components[find(item)].append(item)
    return sorted(sorted(members) for members in components.values())


def describe(group_ids, profiles):
    return [{'group_id': group_id, 'name': profiles[group_id]['name'],
             'brands': profiles[group_id]['brands']} for group_id in group_ids]


def build_report(rows, catalog_hash, pilot_tasks):
    profiles = group_profiles(rows)
    links, same_name_other_brand, histogram = find_links(profiles)
    clusters = merge_clusters(links)
    cluster_of = {group_id: index for index, members in enumerate(clusters) for group_id in members}
    review = sorted(pair for pair, signals in links.items() if not signals & set(MERGE_SIGNALS))

    signal_counts = {}
    for signal in MERGE_SIGNALS + REVIEW_SIGNALS:
        pairs = [pair for pair, signals in links.items() if signal in signals]
        signal_counts[signal] = {'group_pairs': len(pairs),
                                 'groups': len({group_id for pair in pairs for group_id in pair})}

    by_family = {}
    for family in sorted({profile['family'] for profile in profiles.values()}):
        groups = [group_id for group_id, profile in profiles.items() if profile['family'] == family]
        family_clusters = [members for members in clusters if profiles[members[0]]['family'] == family]
        clustered = sum(len(members) for members in family_clusters)
        by_family[family] = {
            'eligible_groups': len(groups),
            'alias_clusters': len(family_clusters),
            'groups_in_alias_clusters': clustered,
            'largest_alias_cluster': max((len(members) for members in family_clusters), default=1),
            'proposed_split_units': len(groups) - clustered + len(family_clusters),
        }

    reserved = sorted({task['data'][f'{side}_group_id'] for task in pilot_tasks
                       for side in ('original', 'candidate')})
    reserved_set = set(reserved)
    expansion = []
    for group_id in reserved:
        aliases = [other for other in clusters[cluster_of[group_id]] if other != group_id] \
            if group_id in cluster_of else []
        if aliases:
            expansion.append({'calibration_group_id': group_id, 'alias_group_ids': aliases,
                              'products': describe([group_id] + aliases, profiles)})
    linked_pilot_pairs = []
    for task in pilot_tasks:
        pair = tuple(sorted((task['data']['original_group_id'], task['data']['candidate_group_id'])))
        if pair in links:
            linked_pilot_pairs.append({'pair_id': task['data']['pair_id'],
                                       'signals': sorted(links[pair])})

    return {
        'catalog_content_sha256': catalog_hash,
        'parameters': {
            'scope': 'eligible groups, links only within one family',
            'min_ingredient_chars': MIN_INGREDIENT_CHARS,
            'name_jaccard': NAME_JACCARD,
            'merge_signals': list(MERGE_SIGNALS),
            'review_signals': list(REVIEW_SIGNALS),
        },
        'eligible_groups': len(profiles),
        'signals': signal_counts,
        'same_name_other_brand': {
            'group_pairs': same_name_other_brand,
            'treatment': 'not linked; generic names such as "Lait de coco" recur across brands',
        },
        'same_brand_pairs_by_name_jaccard': histogram,
        'by_family': by_family,
        'proposed_split_units': sum(family['proposed_split_units'] for family in by_family.values()),
        'alias_clusters': [
            {'family': profiles[members[0]]['family'],
             'signals': sorted({signal for pair in combinations(members, 2)
                                for signal in links.get(pair, ())}),
             'products': describe(members, profiles)}
            for members in clusters],
        'review_links': [
            {'family': profiles[pair[0]]['family'], 'signals': sorted(links[pair]),
             'already_in_one_cluster': cluster_of.get(pair[0], -1) == cluster_of.get(pair[1], -2),
             'products': describe(pair, profiles)}
            for pair in review],
        'calibration': {
            'reserved_groups': len(reserved),
            'alias_groups_to_exclude_with_them': sorted(
                {alias for item in expansion for alias in item['alias_group_ids']} - reserved_set),
            'reserved_groups_with_aliases': expansion,
            'pilot_pairs_whose_members_are_linked': linked_pilot_pairs,
        },
        'note': ('Candidate aliases for review before step 5. Merge signals propose split units; '
                 'review signals need a human decision. group_id is unchanged, no partition is '
                 'frozen and no pair is labeled. Flavor variants of one product line fall below '
                 'the name threshold and stay separate; the Jaccard histogram shows how many '
                 'same-brand pairs a lower threshold would add.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Compare without writing')
    args = parser.parse_args()
    rows = pq.read_table(PARQUET).to_pylist()
    digest = content_sha256(rows)
    if digest != json.loads(MANIFEST.read_text())['content_sha256']:
        raise SystemExit('Catalog contents differ from the comparable catalog manifest')
    pilot_tasks = json.loads(PILOT.read_text())
    if {task['data']['catalog_content_sha256'] for task in pilot_tasks} != {digest}:
        raise SystemExit('Pilot tasks were built from a different catalog')
    report = build_report(rows, digest, pilot_tasks)
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
    if args.verify:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != payload:
            raise SystemExit('Alias report differs from the expected build')
    else:
        write_atomic(OUTPUT, payload)
    print(f'{report["eligible_groups"]} eligible groups, {len(report["alias_clusters"])} alias '
          f'clusters, {report["proposed_split_units"]} proposed split units, '
          f'{len(report["review_links"])} links for review')


if __name__ == '__main__':
    main()
