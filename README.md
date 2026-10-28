# Basket Optimizer

A research prototype for improving a shopping basket through acceptable product
substitutions while respecting preferences and a maximum number of changes.

**Status:** raw catalog acquisition and the basket input flow (selection, quantities,
locks, change limit and validation) are implemented. The recommender, training
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
- `scripts/audit_data.py`: verifies integrity and reports coverage and missing data.
- `scripts/fetch_data.py`: reproduces the historical sample or fetches expanded fields.
- `basket/`: Pydantic basket models, validation and read-only catalog lookup (step 1).
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
