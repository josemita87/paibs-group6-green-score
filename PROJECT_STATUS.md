# Project status

Last updated: 2026-11-27

This is the shared handoff for contributors and AI assistants. Read
[AGENTS.md](AGENTS.md) before editing and update this file in every commit.
The numbered roadmap is [docs/PIPELINE.md](docs/PIPELINE.md). Git is the authoritative
version history; this file explains what is ready and what to do next.

## Current focus

Steps 1–3 are implemented. Step 4 has a reproducible calibration pilot with 36
unlabeled pairs and a blind review form. Two independent human reviews are the
next dependency. No substitution model, optimizer or recommendation interface
has been implemented.

Earlier conversation called raw acquisition “step 1.” In the canonical pipeline
it is **step 2**. Use the document's 1–13 numbering from now on; do not rename steps.

## Roadmap

| Step | Deliverable | Status | Evidence or remaining work |
|---|---|---|---|
| 1 | User input | Done — minimal flow | `basket/` Pydantic models and catalog lookup, `app/streamlit_app.py`, `tests/test_basket.py`. Preferences and nutritional constraints are declared fields only (`declared_not_checked`); enforcement belongs to steps 9–10. |
| 2 | Acquire and version the product catalog | Done — raw sample + family expansion | `scripts/fetch_data.py --catalog` (base snapshot) and `scripts/expand_catalog.py` (1,678 candidate rows of the three families from the same revision), each with a manifest and audit/tests. |
| 3 | Build a comparable, usable catalog | Done — rebuilt with expansion | `basket/comparable.py`, `scripts/build_catalog.py`, `data/catalog.parquet` + report + manifest, `tests/test_comparable.py`. 1,684 eligible products in 1,556 groups across three families; CI verifies the committed outputs against a rebuild. |
| 4 | Create the substitution dataset | In progress — pilot ready | 36 calibration pairs, guidelines, Label Studio form and `scripts/review_agreement.py` to validate two exports and report agreement. Model-drafted labels for the 36 pairs are in `data/pilot_review_model.json`; a human review agreeing with them is reported but no reviewer export is in the repository. |
| 5 | Split the data before training | Not started | Freeze and verify group partitions; construct within-partition pairs/triplets. Input available: unreviewed alias proposal in `data/alias_report.json`. |
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
- Comparable catalog (`data/catalog.parquet`, 13,966 rows = 12,288 base + 1,678
  expansion, same revision): 1,684 eligible products in 1,556 distinct groups.
  Per family (products / distinct groups): yogurts 853 / 782 (847 `g`, 6 `ml`),
  breakfast cereals 479 / 430 (all `g`), plant-based milk alternatives 352 / 344
  (342 `ml`, 10 `g`). Before the expansion: 93 / 92, 29 / 29, 20 / 20. Agribalyse
  versions among eligible: 3.2 for 1,672, 3.1.1 for 12. Score context is `fr`
  (equals the exported score; `world` differs for 1,203 of 5,717 known scores);
  the source flags `missing_key_data` for 3,130 known scores. These are index
  comparisons, not emissions.
- Exclusions among the 1,678 expansion rows: missing ingredients 119, missing salt
  36, sugars 35, proteins 30, missing name 2. Remaining exclusions in the base
  snapshot are unchanged (no recorded g/ml unit 7,977; no known score 8,249).
- Diversity limits: eligible products are 1,304 French-language, 139 English,
  77 Spanish, 74 German, 54 Italian. Yogurts are dominated by Yoplait/Danone/
  Nestlé ranges, cereals by Kellogg's, plant-based milks by Alpro/Bjorg/Lima.
  Eligibility does not establish substitution compatibility; that is what step 4
  annotates.
- Alias proposal (`data/alias_report.json`, not reviewed): 81 clusters join 219 of
  the 1,556 eligible groups, leaving 1,418 split units (yogurts 673, breakfast
  cereals 411, plant-based milk alternatives 334). Sixty clusters hold two groups;
  the largest hold 14 (Nestlé Greek and vanilla yogurts) and 13 (Yoplait Yop
  drinks). Five of the 72 calibration groups have one alias each outside the
  reservation (alias group IDs 11965, 12838, 12849, 13250, 13320).
- Families not selected (dairy desserts, cheeses, biscuits, breads, sweet
  spreads, plant-based beverages, fruit juices) are still reported with base-sample
  counts only; they were not expanded.
- No substitution pairs have been labeled and no new model has been trained.
- Local data checks and remote CI passed for acquisition commit `2ecf444`.
- Historical experiments remain available under `archive/claim-audit-v1` and
  `archive/embeddings-v1`; their metrics are not Basket Optimizer results.

## Next action

Make the reported pilot review verifiable: add each reviewer's own export (or a
record naming them and saying whether they labeled before seeing the model's
labels) and run `python scripts/review_agreement.py <first>.json <second>.json`.
Decide how drinkable yogurts and cooking coconut milk are kept out of sampled
originals, since they caused six of the nine ambiguous pilot pairs.
Before generating model-development pairs, review the alias proposal in
`data/alias_report.json` together with the reviewers' “possible duplicate” flags:
accept or split the proposed clusters, decide the 12 cross-brand links, and choose
whether flavor variants of one product line may sit in different partitions. Then
freeze the remaining split units into disjoint partitions (step 5).

## Change log

### 2026-11-26 — Model-drafted pilot labels and reported human review (step 4)

- Reported by Joan on 2026-11-26: two people went over the 36 pairs and their
  labels coincide with the model's on every pair. This is recorded as reported.
  The repository holds no export from either reviewer, their identifiers are not
  recorded, it is not recorded whether they labeled before seeing the model's
  labels, and `scripts/review_agreement.py` has not been run on human exports.
- `data/pilot_review_model.json` holds one label and reason for each of the 36
  pilot pairs, written by an AI model (Claude Fable 5.2 through the Cursor agent)
  from the context, names and ingredient texts. Each annotation records that
  provenance in `completed_by`. The file uses the full-JSON export structure, so
  `scripts/review_agreement.py` can compare it with a human reviewer's export.
- Result: 25 acceptable, 9 ambiguous, 2 unacceptable. Five of the nine ambiguous
  pairs are plant-based milks, mostly canned cooking coconut milk as the original.
  Pair `…/8850813507010/8850367100019` (two “Kokosmilch” products) is marked
  “possible duplicate”.
- Validation: the file passes `parse_review` with no errors (36 pairs, one label
  and a nonempty reason each). No agreement was computed; there is no second review.
- Limitations: the label file is a model's review, not a human export. Until the
  two reviewers' own exports or a signed-off record are added, the human review
  rests on the report above and no measured agreement figure exists. The model
  had seen brand strings for a few of these products during the alias inspection.
  Step 4 stays in progress. Committed on 2026-11-27; no runtime code changed.
- Finding for scale-up: six of the nine ambiguous pairs arise because the original
  does not fit the stated use (three cooking coconut milks and a nata de coco soft
  drink among plant-based milks, two drinkable yogurts). Eligibility by category
  tag admits these products, so pair sampling needs a format check first.

### 2026-11-26 — Near-duplicate alias proposal (preparation for step 5)

- Added `scripts/inspect_aliases.py` and its output `data/alias_report.json`.
  Among eligible groups of one family it links groups that share a brand entry
  and have the same normalized name (48 group pairs), the same ingredient text of
  at least 40 normalized characters (94) or a name-token Jaccard of at least 0.8
  (51). Connected groups form 81 proposed clusters and 1,418 split units.
- Not linked: 212 same-name pairs with no shared brand entry (15 groups are
  named “Lait de coco”). Listed for a human decision without merging: 12
  identical-ingredient links between different brands.
- Calibration: five reserved groups have one alias each outside the reservation,
  for example “Choco Krispies” under `Kellogg's` and under `Kellogg's, Choco
  Krispies, …`. No pilot pair joins two linked groups, so the pilot is unchanged.
- Validation: 9 new tests (linking rules on synthetic groups; committed report
  reproducible under reversed row order, clusters disjoint and single-family,
  counts consistent, calibration aliases derived from clusters) pass with the
  other 52. `inspect_aliases.py --verify`, the pilot and catalog verifications and
  both raw audits pass locally. CI gained the report verification; its remote
  result is not known at commit time.
- Limitations: no person has reviewed the clusters. Merging is transitive and
  errs toward larger units: flavors of one line that declare the same ingredient
  text (“arôme naturel”) are joined, as in the Yop cluster. Flavor variants with
  different ingredient text mostly stay separate; 213 same-brand pairs sit at
  Jaccard 0.7 and 355 at 0.6. Renamed products with different brand entries and
  different ingredient text are not detected. `group_id` and the catalog are
  unchanged and no partition is frozen. Step 5 status is unchanged.

### 2026-11-26 — Review validation and agreement report (step 4)

- Added `scripts/review_agreement.py`. It reads two full-JSON Label Studio exports,
  joins them on `data.pair_id` and refuses to compute agreement unless both hold
  all 36 pairs with one submitted annotation, one label from the form and a
  nonempty reason, with task data matching the task file. It reports identical
  decisions, the 3×3 label table, Cohen's kappa, per-family counts, disagreements
  with both reasons and the pairs marked “possible duplicate” with their group IDs.
  It writes no final label; adjudication stays a human record.
- Control names and labels are read from `docs/annotation_form.xml`. The export
  structure was checked against the Label Studio export documentation.
- Validation: 8 new tests with synthetic in-memory exports (complete review, ten
  kinds of incomplete or invalid task, other export formats, kappa against a
  hand-computed value, report contents, command behavior) pass with the existing
  44. Remote CI for this commit is not known at commit time.
- Limitations: not run on a real Label Studio export, because no human review
  exists yet. Step 4 status is unchanged. No labels are stored in the repository.

### 2026-11-26 — Pilot committed after revalidation (step 4)

- Committed the 2026-11-24 pilot files unchanged. Step 4 status is unchanged:
  human reviews are still pending.
- Local validation repeated before committing: 44 tests passed, the pilot and
  comparable catalog verified against a rebuild, both raw audits were unchanged.
  Remote CI for this commit is not known at commit time.
- The 2026-11-10 risks document and the earlier document moves under `output/`
  remain uncommitted in the working tree; only the status entry is versioned.

### 2026-11-24 — Substitution annotation pilot (step 4)

- Prepared 12 directed pairs per family for the three benchmark uses. The 72
  eligible product groups cover 11 source languages. The blind review form
  requires a decision and a reason. Human labels and agreement are pending.
- Reserved calibration groups before pairing. Exclude those groups and their
  aliases from future model partitions and the separate 30-request benchmark.
  Step 5 remains open. Broader near-duplicate review is pending.
- Local validation: 44 tests passed, both raw audits passed, the committed
  coverage report matched and the comparable catalog and pilot rebuilds verified.
  The review form's structure and field bindings were checked locally. Live Label
  Studio import and remote CI have not been run for this change.

### 2026-11-10 — System risks and component status document

- Added the Session 2 risk and component handoff: four testable questions and the
  real, planned stub or pending status of all 13 steps. The two proposed stubs are
  not integrated. No implementation step advanced.
- Validation: checked the contents against the repository and classroom worksheets;
  verified all 13 entries and visually reviewed the one-page Word render.
  Runtime tests were not needed for this document-only addition.
- Next implementation task remains step 4: define annotation rules and prepare
  the first independently reviewed pilot pairs.


### 2026-11-04 — Comparable catalog rebuilt with the expansion (steps 2–3)

- `scripts/build_catalog.py` and `basket/catalog.py` now load the base snapshot and
  `data/catalog_expansion.jsonl.gz` together, verify each against its manifest,
  require the same revision and keep the first occurrence of a barcode (0 duplicate
  codes dropped). Records carry `source_snapshot`; the Parquet manifest lists both
  sources; the report adds rows/eligible per source, distinct eligible groups per
  family and per-family Agribalyse versions.
- Rebuilt `data/catalog.parquet` (13,966 rows, 4.0 MB), report and manifest.
  Coverage went from 142 eligible / 141 groups to 1,684 eligible / 1,556 groups;
  per family see “Available evidence”. Family definitions and eligibility rules
  are unchanged.
- Validation: 40 tests pass (step-1 loader test now derives the expected row count
  from the expansion manifest); `build_catalog.py` then `--verify` passed;
  `audit_data.py` with and without `--catalog` unchanged; base snapshot checksums
  unchanged. Remote CI for this commit is not known at commit time.
- Assessment: the expanded catalog is a practical basis for a first annotation
  pilot in all three families. Eligibility proves data completeness, not that any
  two products are substitutes. Unresolved: language and brand concentration
  described above; the step-1 app displays expansion products but still reads raw
  rows rather than `catalog.parquet`.

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
