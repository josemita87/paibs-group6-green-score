# Basket Optimizer

A research prototype for improving a shopping basket through acceptable product
substitutions while respecting preferences and a maximum number of changes.

**Status:** the design is documented and the original data sample is retained.
The recommender, training pipeline, optimizer and interface are not implemented yet.

Intended use: “Improve my basket's environmental indicator, maintain a minimum
protein level and change at most three products.”

## Design

[Technical pipeline, training and evaluation](docs/PIPELINE.md).
The planned core combines a multilingual encoder fine-tuned on substitution
examples with discrete optimization. Explanations will use the data behind each
comparison; a chat API is not required.

## Repository contents

- `data/`: an OFF sample of 12,288 products and a provenance/checksum manifest.
- `scripts/audit_data.py`: verifies integrity and reports coverage and missing data.
- `scripts/fetch_data.py`: reproduces the pinned historical sample.
- `requirements-data.txt`: optional dependencies for downloading the sample again.
- `DATA_LICENSE.md`: data attribution and licensing terms.

## Verify the data

Python 3.12; this check uses only the standard library:

```sh
python3 scripts/audit_data.py
```

To download the historical snapshot again:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-data.txt
python scripts/fetch_data.py
```

The current sample has no nutrient, price or stock data. It does not yet support
the complete example above and is not representative of the OFF catalog.
Original product records retain their source languages for multilingual research.

## Previous work

Green-Score prediction and label auditing belong to an earlier project direction.
Their code, results and documents can be recovered from the Git tag
`archive/claim-audit-v1` (commit `62ff9bf`). They are not Basket Optimizer results.

The embedding experiment subsequently added to the remote repository is preserved
under `archive/embeddings-v1` (commit `e508342`).
