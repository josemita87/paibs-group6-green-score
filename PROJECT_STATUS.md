# Project status

Last updated: 2026-10-28

This is the shared handoff for contributors and AI assistants. Read
[AGENTS.md](AGENTS.md) before editing and update this file in every commit.
The numbered roadmap is [docs/PIPELINE.md](docs/PIPELINE.md). Git is the authoritative
version history; this file explains what is ready and what to do next.

## Current focus

Raw catalog acquisition (step 2) and the basket input flow (step 1) are implemented.
The comparable catalog, recommender, training pipeline, optimizer and recommendation
interface are not implemented. The next task is **step 3: build a comparable,
usable catalog**.

Earlier conversation called raw acquisition “step 1.” In the canonical pipeline
it is **step 2**. Use the document's 1–13 numbering from now on; do not rename steps.

## Roadmap

| Step | Deliverable | Status | Evidence or remaining work |
|---|---|---|---|
| 1 | User input | Done — minimal flow | `basket/` Pydantic models and catalog lookup, `app/streamlit_app.py`, `tests/test_basket.py`. Preferences and nutritional constraints are declared fields only (`declared_not_checked`); enforcement belongs to steps 9–10. |
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
- Raw `product_quantity_unit` is only ever `g` (3,653) or `ml` (658); 7,977 products
  record none. The input flow therefore accepts `g`, `kg`, `ml`, `l` only, rejects a
  unit that conflicts with a recorded basis and marks items `unverified` when the
  source records no unit. Counts, pieces and ounces in the free-text `quantity`
  field are not parsed.
- A `Basket` records inputs only: it carries no nutrient values, no eligibility
  judgement and no recommendation. Availability flags on `ProductRef` report
  whether a raw value exists, not whether it is comparable.
- No substitution pairs have been labeled and no new model has been trained.
- Local data checks and remote CI passed for acquisition commit `2ecf444`.
- Historical experiments remain available under `archive/claim-audit-v1` and
  `archive/embeddings-v1`; their metrics are not Basket Optimizer results.

## Next action

Implement step 3 in a focused change: standardize nutrient names and units
(including `salt` recorded in `mg`), resolve the mass/volume basis per product,
keep missing values explicitly missing, group duplicates and near-duplicate
variants, and select candidate product families with enough complete products.
Record exclusion reasons and output `catalog.parquet` plus a coverage report. The
step-1 `Basket` schema (`schema_version: 1`) is the input contract later steps
should consume; extend it rather than replacing it.

## Change log

### 2026-10-28 — Basket input flow and validation (step 1)

- Added `basket/models.py` (Pydantic v2): `Unit` (`g`, `kg`, `ml`, `l` with exact
  canonical conversion), `ProductRef` with raw availability flags, `BasketItem`
  (positive finite quantity, lock flag, unit-basis check against the recorded
  catalog unit, `unit_basis` verified/unverified), `Preferences` and
  `NutritionalConstraints` as declared-only fields, `Basket` (≥1 item, unique
  products, `max_substitutions ≥ 0`, catalog revision and checksum) and
  `build_basket`, which reports every unknown barcode and invalid value at once.
- Added `basket/catalog.py`: verified snapshot loading, exact barcode lookup and
  case-insensitive name/brand search; no cleaning or inference of source values.
- Added `app/streamlit_app.py`: search or barcode selection, product evidence
  display, quantity/unit/lock entry, change limit, preference and constraint fields,
  basket table with lock toggles and removal, JSON output and download. The UI
  states that recommendations and constraint checks are not implemented.
- Added `requirements-app.txt` (pydantic 2.14.1, streamlit 1.66.1); CI now installs
  it before the unit tests. Updated README and pipeline status text.
- Validation (local, Python 3.13 venv): 20 unit tests pass (4 existing data checks,
  13 model/catalog checks, 3 headless `AppTest` runs of the Streamlit screen);
  `scripts/audit_data.py` and `--catalog` unchanged against the committed report;
  manual browser run of the app: search “yogurt”, add 100 g, build basket, observed
  the unverified-unit warning, success message and JSON. Remote CI for this commit
  is not known at commit time.
- Limitations: no nutrient values, eligibility or recommendations in the basket;
  preferences and constraints are stored, not checked; search is substring-only;
  names keep raw source text (HTML entities are unescaped only for display).

### 2026-10-28 — Work 2 walking skeleton worksheet

- Added `output/word/group_6_work_2_walking_skeleton.docx`: an English Group 6
  sprint plan with proposed workstreams, a real/stub log, risks and acceptance criteria.
- Records Level 1 (data in hand) as the current position and Level 2 as the sprint
  target. Planned stubs and ownership are not presented as completed or agreed work.
- Validation: rendered and visually reviewed both pages; verified two editable tables.
  Runtime tests were not needed for this document-only change.
- No implementation step advanced. Next implementation task remains step 1.


### 2026-10-28 — Editable Work 2a Word document

- Added `output/word/group_6_work_2a_stack_editable.docx`, preserving the English
  Group 6 stack table, provisional levels and unconfirmed experience fields.
- Reused the matching local Word content in a separate editable copy; preserved
  the existing untracked Word file. No pipeline step advanced.
- Validation: confirmed the editable 11-row table, rendered and visually reviewed
  the single-page document. Runtime tests were not needed for this format change.
- Next implementation task remains step 1.


### 2026-10-28 — Work 2a stack PDF

- Added `output/pdf/group_6_work_2a_your_stack.pdf`: a one-page English stack table
  for Group 6, covering components, tools, levels, prior use and alternatives.
- Levels 2-3 are provisional estimates requested by the user. Prior team experience
  remains unconfirmed; coaching priorities are conditional on the team's review.
- Validation: rendered and visually reviewed the PDF; checked one-page layout and
  extracted text. Runtime tests were not needed for this document-only addition.
- No pipeline step advanced. Next implementation task remains step 1.


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
