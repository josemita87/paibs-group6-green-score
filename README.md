# Basket Optimizer

A research prototype for improving a shopping basket through acceptable product
substitutions while respecting preferences and a maximum number of changes.

**Status:** raw catalog acquisition, the basket input flow (selection, quantities,
locks, change limit and validation) and the comparable catalog (cleaned text,
per-100 nutrients, fixed score context, product groups, eligibility with recorded
exclusion reasons) are implemented. A 36-pair calibration set is ready for independent
review. Human labels are pending. The recommender, training
pipeline, optimizer and recommendation interface are not implemented yet; declared
preferences and nutritional constraints are recorded but not checked.

Intended use: “Improve my basket's environmental indicator, maintain a minimum
protein level and change at most three products.”

## Contributing

Read [AGENTS.md](AGENTS.md) and [PROJECT_STATUS.md](PROJECT_STATUS.md) before starting.
Every commit must update the shared project status in the same commit, including
changes, validation and the next action. Keep all project content and commits in
English. Follow the numbered pipeline steps in order; record dependency exceptions.

## Design

[Technical pipeline, training and evaluation](docs/PIPELINE.md).
The planned core combines a multilingual encoder fine-tuned on substitution
examples with discrete optimization. Explanations will use the data behind each
comparison; a chat API is not required.

## Repository contents

- `data/`: the original 12,288-product OFF sample and an expanded raw catalog,
  each with a provenance/checksum manifest; `catalog_audit.json` records coverage.
  `catalog.parquet`, `catalog_report.json` and `catalog_parquet_manifest.json` are
  the comparable catalog built from the raw snapshot (step 3).
- `scripts/audit_data.py`: verifies integrity and reports coverage and missing data.
- `scripts/fetch_data.py`: reproduces the historical sample or fetches expanded fields.
- `scripts/expand_catalog.py`: adds family-targeted candidate rows from the same
  pinned revision into `data/catalog_expansion.jsonl.gz` with its own manifest.
- `scripts/build_catalog.py`: builds or verifies the comparable catalog from the
  base snapshot plus the expansion.
- `scripts/build_annotation_pilot.py`, `scripts/review_agreement.py`: build the
  unlabeled step-4 pilot tasks and check two reviewers' exports.
- `scripts/inspect_aliases.py`: reports candidate near-duplicate groups in
  `data/alias_report.json`.
- `scripts/freeze_partitions.py`: freezes eligible groups into calibration, train,
  validation and test partitions in `data/partitions.json` (step 5).
- `scripts/build_pairs.py`: samples the unlabeled annotation pairs of each
  partition into `data/pairs.json` (step 4).
- `scripts/run_baselines.py`: ranks every pair with the untrained baselines into
  `data/baseline_report.json` (step 6).
- `basket/`: Pydantic basket models, validation and read-only catalog lookup (step 1);
  `basket/comparable.py` holds the step-3 normalization and eligibility rules;
  `basket/pairs.py` holds the step-4 pair sampling rules and `basket/baselines.py`
  the step-6 ranking baselines.
- `app/streamlit_app.py`: minimal Streamlit screen that builds and validates a basket.
- `requirements-app.txt`: pinned dependencies for the basket models, app and tests.
- `requirements-data.txt`: optional dependencies for downloading the sample again.
- `DATA_LICENSE.md`: data attribution and licensing terms.

## Verify the data

Python 3.12+; these checks use only the standard library:

```sh
python3 scripts/audit_data.py
python3 scripts/audit_data.py --catalog
```

## Build a basket (step 1)

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-app.txt
python -m unittest discover -s tests -v
streamlit run app/streamlit_app.py
```

The screen selects real products from the pinned catalog by name/brand search or
exact barcode, takes a positive quantity in `g`, `kg`, `ml` or `l`, a lock flag and a
maximum number of substitutions, and produces a JSON `Basket`. The catalog records
product units only as `g` or `ml`; a unit is rejected when it conflicts with the
recorded basis and marked `unverified` when the source records none. Dietary
preferences and nutritional constraints are stored as declared fields with
`enforcement: declared_not_checked`; nothing filters or checks them yet, and no
recommendations are produced.

## Comparable catalog (step 3)

```sh
python scripts/build_catalog.py            # rebuild data/catalog.parquet and the report
python scripts/build_catalog.py --verify   # check the committed outputs against a rebuild
```

Every raw product becomes one row with cleaned name and ingredients (all source
languages kept in `names_json`/`ingredients_json`), nutrients per 100 g or 100 ml
taken from the source `100g` key (already in grams; implausible values are set to
missing and listed in `implausible_nutrients`), the environmental score in the
fixed `fr` context (the `world` score is kept for reference), a `comparison_unit`
of `g` or `ml` taken only from the recorded product unit, and a `group_id` shared
by products with the same normalized name and brand. `exclusion_reasons` says why a
row is not `eligible`. The selected families are yogurts, breakfast cereals and
plant-based milk alternatives; `catalog_report.json` records their counts and the
coverage of families that were not selected. Score differences are an experimental
index, not emissions.

## Review substitution pairs (step 4)

The [annotation guide](docs/ANNOTATION.md) includes the Label Studio form, task
file, label definitions and instructions for two independent reviewers.
Reproduce or verify the unlabeled pilot with the application dependencies installed.

```sh
python scripts/build_annotation_pilot.py
python scripts/build_annotation_pilot.py --verify
python scripts/review_agreement.py ana.json ben.json   # two reviewers' full JSON exports
```

`review_agreement.py` validates both exports against the task file and reports
agreement before discussion. It has been tested with synthetic exports only; no
human review exists yet.

## Inspect near-duplicate groups (input to step 5)

```sh
python scripts/inspect_aliases.py            # rebuild data/alias_report.json
python scripts/inspect_aliases.py --verify   # check the committed report against a rebuild
```

`group_id` joins only products with the same normalized name and brand string, so
one product listed under `Danone` and under `Danone, Danonino` forms two groups.
The report links eligible groups of one family that share a brand entry and have
the same name, the same ingredient text of at least 40 normalized characters, or
a name-token Jaccard of at least 0.8. On the current catalog it proposes 81
clusters covering 219 of the 1,556 groups, which leaves 1,418 split units. Twelve
identical-ingredient links between different brands are listed for a human
decision and merge nothing. The report is a proposal and changes no `group_id`.

## Product partitions (step 5)

```sh
python scripts/freeze_partitions.py            # rebuild data/partitions.json
python scripts/freeze_partitions.py --verify   # check the committed partitions against a rebuild
```

Groups joined by any link of the alias report, including the twelve cross-brand
ones, form one split unit: 1,408 units from 1,556 eligible groups. The 72 units
holding a pilot group are `calibration`. Within each family the others are ordered
by a seeded hash and sliced into 200 test, 200 validation and 936 train units.
Only products are partitioned; pairs and triplets do not exist yet. Flavor
variants of one brand whose names and ingredient texts differ can fall in
different partitions: 107 same-brand group pairs with a name-token Jaccard of at
least 0.6 sit across train and test.

## Annotation pairs inside the partitions (step 4)

```sh
python scripts/build_pairs.py            # rebuild data/pairs.json
python scripts/build_pairs.py --verify   # check the committed pairs against a rebuild
```

`data/pairs.json` holds 300 unlabeled Label Studio tasks in the step-4 review form:
60 pairs per family for train and 20 each for validation and test. Both sides of a
pair are eligible groups of one family that sit in the same partition and in
different split units, so no pair joins two near-duplicates and no pair crosses a
partition. The 72 calibration groups stay reserved for the pilot.

Each family and partition splits its budget over three sampling strategies. The
`lookalike` strategy takes the pairs with the highest name-token Jaccard, which is
at least 0.4. The `brand_variant` strategy takes pairs that share a brand entry and
score below 0.4. The `family_random` strategy takes pairs that share no brand entry
and score below 0.4. A seeded barcode hash orders the last two and breaks ties in
the first. No group appears in more than three pairs of one family and partition.
The file records the strategy and the name overlap of every pair and no label; a
strategy says how a pair was sampled, not whether the products substitute.

## Baseline rankings (step 6)

```sh
python scripts/run_baselines.py            # rebuild data/baseline_report.json
python scripts/run_baselines.py --verify   # check the committed report against a rebuild
```

Three untrained baselines rank candidates for every pair of `data/pairs.json` and
for the 36 pilot pairs. The pool of one pair is every eligible group of the same
family and partition, except the groups of the original's own split unit.

- `category_rules` scores 0 for another family or comparison unit. Otherwise it
  scores 1 minus the mean relative difference on protein, sugars and salt per 100.
- `tfidf_char` is the cosine of character 4-gram TF-IDF vectors of the name and the
  ingredient text. Document frequencies come from the 1,045 train groups only.
- `random_control` is a seeded hash of the two barcodes. It measures nothing and
  shows what a given rank statistic looks like by chance.

The frozen-encoder baseline of the pipeline document is not implemented; it needs
Sentence Transformers and a downloaded model. The report records the rank and
percentile of every pair under each baseline, the statistics per sampling strategy
and partition, the share of the top 10 that the rule and text baselines agree on,
and the scores grouped by the model-drafted pilot labels. No baseline reads a
label, and the pilot sample holds two `unacceptable` labels, so the label section
describes that sample and establishes nothing about baseline quality.

## Family-targeted expansion (step 2, in support of step 4)

```sh
python scripts/expand_catalog.py            # resumable; caches under data/cache/
python scripts/build_catalog.py             # rebuild the comparable catalog with the expansion
```

The pinned `food.parquet` (4.3 GB, 2,068 row groups ordered by barcode) is not
organized by category, so the script first scans three light columns of every row
group (about 29 MB) to locate candidates: rows in a selected family with a recorded
`g`/`ml` unit and a numeric exported score. It then reads the full field set only for
the row groups richest in candidates of families still below 100 distinct eligible
groups, in deterministic waves of 8, within a budget of 200 row groups (about
1.3 MB each). Only candidate rows are kept; the 12 historical row groups and codes
already in the base snapshot are excluded. `data/catalog_expansion_manifest.json`
records the revision, fields, criteria, row groups read, wave log, byte estimates
and checksum. The base snapshots and their manifests are unchanged. Both
`build_catalog.py` and the Streamlit app load the base snapshot and the expansion
together, deduplicated by barcode, and the comparable catalog records each row's
`source_snapshot`.

To download the expanded catalog from the pinned source revision:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-data.txt
python scripts/fetch_data.py --catalog
```

Omit `--catalog` to reproduce the historical sample. The expanded catalog uses the
same source revision and row groups, adding raw nutrients, quantity/unit fields,
allergen/trace tags, dietary analysis, quality flags and modification timestamps.
The downloader checks that all original fields still match the historical checksum.
Caches are separated by revision and selected fields; downloads can be resumed.

`catalog.jsonl.gz` preserves raw source values and languages. Nutrients are a list
of records with `name`, `100g`, `unit`, serving and prepared-value fields. Coverage
is not eligibility: units, mass/volume basis, missing data and score context still
need normalization. Prices and stock are absent. This clustered sample is not
representative of the OFF catalog and is not yet a comparable-product dataset.

## Previous work

Green-Score prediction and label auditing belong to an earlier project direction.
Their code, results and documents can be recovered from the Git tag
`archive/claim-audit-v1` (commit `62ff9bf`). They are not Basket Optimizer results.

The embedding experiment subsequently added to the remote repository is preserved
under `archive/embeddings-v1` (commit `e508342`).
