# Project status

Last updated: 2026-11-04

This is the shared handoff for contributors and AI assistants. Read
[AGENTS.md](AGENTS.md) before editing and update this file in every commit.
The numbered roadmap is [docs/PIPELINE.md](docs/PIPELINE.md). Git is the authoritative
version history; this file explains what is ready and what to do next.

## Current focus

Raw catalog acquisition (step 2), the basket input flow (step 1) and the comparable
catalog (step 3) are implemented. The substitution dataset, recommender, training
pipeline, optimizer and recommendation interface are not implemented. The next task
is **step 4: create the substitution dataset** (guidelines, candidate pairs within
the eligible families and product groups, pilot annotation).

Earlier conversation called raw acquisition “step 1.” In the canonical pipeline
it is **step 2**. Use the document's 1–13 numbering from now on; do not rename steps.

## Roadmap

| Step | Deliverable | Status | Evidence or remaining work |
|---|---|---|---|
| 1 | User input | Done — minimal flow | `basket/` Pydantic models and catalog lookup, `app/streamlit_app.py`, `tests/test_basket.py`. Preferences and nutritional constraints are declared fields only (`declared_not_checked`); enforcement belongs to steps 9–10. |
| 2 | Acquire and version the product catalog | Done — raw sample | `scripts/fetch_data.py --catalog`, catalog snapshot, manifest and coverage audit. Broader catalog acquisition can follow if coverage requires it. |
| 3 | Build a comparable, usable catalog | Done — first version | `basket/comparable.py`, `scripts/build_catalog.py`, `data/catalog.parquet` + report + manifest, `tests/test_comparable.py`. 142 eligible products in three families; CI verifies the committed outputs against a rebuild. Coverage is thin for two families. |
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
  whether a raw value exists, not whether it is comparable. The step-1 app and
  `basket/catalog.py` still read the raw snapshot, not `catalog.parquet`.
- Comparable catalog (`data/catalog.parquet`, 12,288 rows): 142 eligible products —
  yogurts 93 (91 `g`, 2 `ml`), breakfast cereals 29 (`g`), plant-based milk
  alternatives 20 (`ml`) — in 141 product groups. Main exclusions: no recorded
  g/ml unit 7,977; no known environmental score 8,249; no ingredients 6,861;
  7 implausible values among the three target nutrients were set to missing.
  Score context is `fr` (equals the exported score; `world` differs for 772
  products). Among eligible products, 137 use Agribalyse 3.2 and 5 use 3.1.1, and
  the source flags `missing_key_data` for most known scores. These are index
  comparisons, not emissions.
- Families not selected but with more complete products (dairy desserts 122,
  cheeses 111, plant-based beverages 87, biscuits 74) are listed in
  `catalog_report.json`; 20–29 products per family is thin for the 600–1,000
  annotated pairs planned in step 4. Broader acquisition (step 2) may be needed.
- No substitution pairs have been labeled and no new model has been trained.
- Local data checks and remote CI passed for acquisition commit `2ecf444`.
- Historical experiments remain available under `archive/claim-audit-v1` and
  `archive/embeddings-v1`; their metrics are not Basket Optimizer results.

## Next action

Start step 4 with a focused change: write the annotation guidelines (labels,
usage contexts per family, reasons), generate candidate pairs only among eligible
products of the same family and comparison unit, never pairing products from the
same `group_id`, and prepare a pilot set for two independent annotators. Decide
with the team whether to widen the families or acquire more products first, given
20–29 eligible products in two of the three families. The step-1 `Basket` schema
and the step-3 `catalog.parquet` columns are the contracts later steps consume.

## Change log

### 2026-11-04 — Family-targeted expansion of the raw catalog (return to step 2)

- Added `scripts/expand_catalog.py`. Probed the pinned `food.parquet` footer first:
  4.3 GB, 2,068 row groups of 963–1,024 rows ordered by barcode, so no category
  layout can be exploited. Phase 1 scans only `categories_tags`,
  `product_quantity_unit` and `environmental_score_score` for every row group
  (28.6 MB compressed) to locate candidates of the three families with a recorded
  g/ml unit and a numeric score. Phase 2 reads the full selected fields for the
  row groups richest in candidates of families still below 100 distinct eligible
  groups, in deterministic waves of 8, within a budget of 200 row groups
  (about 1.3 MB each). Both phases cache per row group under `data/cache/`.
- Outcome: 16 row groups read (26.2 MB), 1,678 candidate rows saved to
  `data/catalog_expansion.jsonl.gz` (2.8 MB) with
  `data/catalog_expansion_manifest.json` (revision, fields, criteria, wave log,
  byte estimates, sha256). Stop reason `target_reached` after two waves. The
  database-wide scan counted 14,406 yogurt, 10,923 breakfast-cereal and 3,348
  plant-based-milk candidates in 1,940 row groups. No code overlapped the base
  snapshot; the 12 historical row groups were skipped.
- Validation: 8 new tests (candidate rule, deterministic wave choice, eligibility
  reuse, committed expansion provenance/overlap/field checks, historical checksums)
  pass with the existing 32; `audit_data.py` with and without `--catalog`
  unchanged; base snapshot files not modified. Remote CI not known at commit time.
- Limitation: density-first selection concentrates on a few GS1 prefixes and
  manufacturers (French yogurt ranges, Kellogg's UK, Alpro Belgium); the expansion
  is mostly French-language. The next commit consumes the expansion in the
  comparable catalog and reports coverage per family and distinct groups.

### 2026-11-04 — Comparable catalog (step 3)

- Added `basket/comparable.py`: HTML/entity/allergen-marker cleaning that keeps
  every source language, per-100 nutrient extraction from the source `100g` key
  (verified to be grams even when the display unit is `mg`), plausibility bounds
  (0–100 g, 0–900 kcal) that set values to missing and record them, comparison
  unit from the recorded product unit only, environmental score in the fixed `fr`
  context with `world`, grade, Agribalyse version and `missing_key_data` kept,
  family assignment by category tags, Unicode-aware name+brand grouping, ordered
  exclusion reasons and a per-family minimum of 20 eligible products.
- Added `scripts/build_catalog.py`: writes `data/catalog.parquet` (3.3 MB, 12,288
  rows, 40 columns), `data/catalog_report.json` and `data/catalog_parquet_manifest.json`
  with a content hash over canonical record JSON; `--verify` rebuilds and compares.
  CI runs the verification. Pinned pandas 3.1.0 and pyarrow 26.0.0 in
  `requirements-app.txt`.
- Selected families after measuring coverage: yogurts, breakfast cereals and
  plant-based milk alternatives (matches the Session 2 benchmark plan). The report
  also lists seven candidate families that were not selected.
- Validation (local, Python 3.13 venv): 12 new unit tests pass with the existing 20;
  `build_catalog.py` then `--verify` passed; both `audit_data.py` checks unchanged.
  Found and fixed a grouping bug during review: non-Latin names (Cyrillic, Greek,
  Arabic) had collapsed into one 34-product group. Remote CI for this commit is
  not known at commit time; CI passed for the step-1 commit `1ee166a`.
- Limitations: the step-1 app still reads the raw snapshot; `sugars > carbohydrates`
  in 35 raw products is not flagged; mixed Agribalyse versions and `missing_key_data`
  are recorded, not resolved; near-duplicate detection uses exact normalized
  name+brand, so renamed variants are separate groups.

### 2026-10-28 — Work 3 benchmark plan

- Added `output/Session2/group_6_work_3_benchmark.docx`: a one-page English plan
  with a 30-request primary metric, held-out product groups, reviewer criteria and
  a category/score baseline. Step 12 remains unimplemented; no cases are scored.
- Raw-data screen found 93 yogurt, 29 breakfast-cereal and 20 plant-based milk
  alternative records with ingredients, g/ml product units, all three target
  nutrients and numeric `environmental_score_data.scores.fr`; these are not
  normalized eligibility counts. Family viability must be checked in step 3.
- Added the user's concrete-writing and restrained-formatting preference to AGENTS.md.
- Validation: checked raw counts; rendered and visually reviewed the single-page
  Word document; verified editable text and no tables. Runtime tests not needed.
- Preserved the user's existing document moves/edits and Word lock files without
  staging them. Next implementation task remains step 3.


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
