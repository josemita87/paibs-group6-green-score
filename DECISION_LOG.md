# Decision log

## 27 October 2026 — Scope and evidence

- Start from the supplied Group 6 Green-Score proposal. Use eCampus Group 6 as the formal identifier. Live roster lists Adria Anglada, Joan Batllo, Josep Cubedo and Natan Viejo. Miro's column is visually Team 5 and also contains Teo; enrolment needs clarification.
- Miro shows five ideas and a note “discussing with Team 10”. No substantive feedback is attributed to that team in this package.
- Select Green-Score Filler and Data Cleaner for this preparation, without reconstructing a historical vote. Data Cleaner is narrowed to learned category consistency rather than an unbounded error detector.

## 27 October 2026 — Data

- Use official OFF Parquet revision 89cfb571db20b1f1b246f27cab71837fc96225b1; 12 row groups, seed 20261027; 12,288 products. Preserve the compressed snapshot and raw SHA256.
- The sample is clustered by barcode order. Do not generalize its coverage rates to all OFF products.
- Numeric labels: 4,039; eligible regression records: 1,629. Ingredients and categories are less available on the unlabelled population. All eligible regression targets use explicit scores.fr.
- Preserve valid zero, negative scores and scores above 100. Exclude not-applicable cases from training. Never use score-derived metadata as an input feature.

## 27 October 2026 — Initial score experiment

- Fixed character TF-IDF and Ridge alpha 10. Group exact ingredient and normalized name-plus-brand matches before splitting. Train 1056, calibration 233, test 340.
- Category baseline 12.69 MAE; combined model 15.87; categories masked 21.31. The model does not add value over this category baseline.
- The continuation gate stated for this preparation is a meaningful baseline improvement, illustrated as 10%, plus an actionable missing-data workflow. It is not a preregistered experiment or a course grading threshold. The negative result fails even a simple positive-improvement requirement.
- Preserve the negative experiment. Do not tune against this test set and report the same test as untouched validation.

## 27 October 2026 — Refined category experiment

- Predict a recorded category from ingredients, with no category input. Logistic regression C 4; classes need eight training examples.
- Supported classes 20; supported-test top-1 77.9% but only 32.6% label coverage. All-test top-1 25.4%.
- Fixed threshold 0.50: 123 accepted all-class test predictions, 65.9% agreement with recorded labels. High apparent supported-class accuracy is not broad reliability.
- This is recorded-label evaluation. Incorrect source labels, unsupported classes and changing data can invalidate it. Broad categories and case differences need a better canonical target definition in the next iteration.

## 27 October 2026 — Review workflow

- Desk-review 20 randomly selected pre-filter suggestions against cached ingredient and product text. Outcomes: 4 plausible new categories, 8 already recorded, 5 too broad, 2 ambiguous, 1 implausible.
- These are assisted desk judgments, not human contributor validation, photo verification, official taxonomy confirmation or successful official recalculation.
- Suppress top candidates already recorded and generic groceries. The final queue contains 131 suggestions. Post-filter precision has not been estimated; do not transfer the pre-filter desk rate to this queue.
- No automatic OFF writes or numerical score filling. Ask contributors to verify evidence and mapping. A local, rough interface is sufficient for Session 2.

## Next evidence

Recover actual peer feedback; confirm owner availability and member experience; verify real photos and taxonomy for a fresh review batch; test a revised canonical category task with a new evaluation design; maintain real member contributions. Do not backfill imaginary history.

## 27 October 2026 — Simple-rule diagnostic

A three-condition ingredient rule scores 22.7% on supported labels and 7.8% across all test labels, versus classifier 77.9% and 25.4%. The rule was added after the initial results and is explicitly post hoc. It supplies a simple alternative for discussion; it does not validate missing-category corrections.
