# Project status

Last updated: 2026-10-28

This is the shared handoff for contributors and AI assistants. Read
[AGENTS.md](AGENTS.md) before editing and update this file in every commit.
The numbered roadmap is [docs/PIPELINE.md](docs/PIPELINE.md). Git is the authoritative
version history; this file explains what is ready and what to do next.

## Current focus

Raw catalog acquisition is implemented. The recommender, training pipeline,
optimizer and user interface are not implemented. The next task is **step 1:
define and validate basket input**.

Earlier conversation called raw acquisition “step 1.” In the canonical pipeline
it is **step 2**. Use the document's 1–13 numbering from now on; do not rename steps.

## Roadmap

| Step | Deliverable | Status | Evidence or remaining work |
|---|---|---|---|
| 1 | User input | Not started | Define basket items, quantities, preferences, locked products and change limit; implement input validation and a minimal input flow. |
| 2 | Acquire and version the product catalog | Done — raw sample | `scripts/fetch_data.py --catalog`, catalog snapshot, manifest and coverage audit. Broader catalog acquisition can follow if coverage requires it. |
| 3 | Build a comparable, usable catalog | Not started | Normalize units and nutrient basis, resolve missing data and choose eligible families. |
| 4 | Create the substitution dataset | Not started | Annotation guidelines, candidate generation, pilot review and labels; establish product groups before creating pairs. |
| 5 | Split the data before training | Not started | Freeze and verify group partitions; construct within-partition pairs/triplets. |
| 6 | Establish the baselines | Not started | Category/rules, TF-IDF and frozen-encoder rankings on shared cases. |
| 7 | Fine-tune the substitution encoder | Not started | Training and comparison with frozen embeddings. |
| 8 | Encode and index the catalog | Not started | Versioned embeddings and retrieval. |
| 9 | Filter and accept candidates | Not started | Eligibility, preference filters and abstention. |
| 10 | Optimize the complete basket | Not started | Constraints, objective and solver outcome handling. |
| 11 | Present the recommendation | Not started | Comparison interface and explanations. |
| 12 | Evaluate model and optimizer | Not started | Held-out results, ablations and user acceptance. |
| 13 | Reproducibility and delivery | Partial — ongoing | Snapshot manifests and data CI exist; model artifacts and final delivery remain pending. |

Follow the steps in order, skipping completed work. Reproducibility applies to
every step, even though final delivery is step 13. Product grouping must happen
before annotation pairs are built; do not postpone leakage prevention until step 5.
Record any other dependency-driven change of order here before proceeding.

## Available evidence and limitations

- Pinned OFF revision: `89cfb571db20b1f1b246f27cab71837fc96225b1`.
- 12,288 raw products; 10,751 have nutrient records.
- 9,349 have nonnegative numeric source values for protein, sugars and salt under
  the source `100g` key; 3,291 also have a numeric exported environmental score.
- These counts are coverage, not validated compatibility or nutritional eligibility.
  Units, mass/volume basis, prepared values and environmental score context still
  need normalization. Prices and stock are absent.
- No substitution pairs have been labeled and no new model has been trained.
- Local data checks and remote CI passed for acquisition commit `2ecf444`.
- Historical experiments remain available under `archive/claim-audit-v1` and
  `archive/embeddings-v1`; their metrics are not Basket Optimizer results.

## Next action

Implement step 1 in a focused change: specify basket items and supported constraint
fields, validate quantities and limits, and provide a minimal input flow. Use
sample-backed product selection and clearly represent unavailable data. Full
recommendations belong to later steps. Start with a short plan and update this
file with implementation evidence before committing.

## Change log

### 2026-10-28 — Shared contributor workflow

- Added root contributor instructions and this shared status tracker; linked both
  from the README and aligned the pipeline's implementation order with steps 1–13.
- Corrected the earlier acquisition-step numbering. No implementation step advanced.
- Validation: documentation links, roadmap numbering and `git diff --check` checked.
  Runtime tests not run for this documentation-only change. Remote CI for this
  commit is not yet known at commit time.
- Next: step 1 input definition and validation; step 3 follows completed step 2.

### 2026-10-28 — Raw catalog acquisition (step 2)

- Added expanded source fields, revision/field-scoped caches, historical-field
  verification, coverage reporting and regression checks.
- Validation: clean dependency installation, download, cached reproduction,
  historical and expanded integrity checks, four regression tests and remote CI
  passed for commit `2ecf444`.
- Remaining: normalization and eligibility; no comparable pairs or recommendations.
