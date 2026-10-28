# Basket Optimizer: end-to-end pipeline

The proposed system combines two technical components: a model fine-tuned to
recognize acceptable product substitutes and a mathematical optimizer that selects
changes for the complete basket. Both can run locally without a chat API.

**Current status:** raw catalog acquisition (step 2) and the basket input flow
(step 1: product selection, quantities, units, locks, change limit, declared
preference and constraint fields, validation) are implemented. The repository
contains the original sample, an expanded catalog, coverage report, data
verification/download scripts, the `basket` package, a Streamlit input screen and
design documentation. The comparable catalog, training pipeline, recommender,
optimizer and recommendation interface below are proposed work, not implemented
features or measured results.

## 1. User input

The user builds a basket by searching for products or entering barcodes, adds
quantities and selects constraints:

- Change at most three products.
- Maintain a minimum total protein level.
- Stay below selected sugar or salt limits.
- Respect supported dietary preferences.
- Keep particular products unchanged.

The system returns a revised basket, proposed substitutions and measured
differences. For the MVP, select three product families with comparable uses after
checking data coverage, for example breakfast drinks, yogurts and cereals.

**Tools:** Streamlit for the interface; Pydantic for input validation.

## 2. Acquire and version the product catalog

Use Open Food Facts product data:

| Data | Purpose |
|---|---|
| Barcode, name and brand | Product identification |
| Ingredients and language | Model input |
| Categories | Candidate filtering |
| Nutrients per 100 g or 100 ml | Nutritional constraints |
| Environmental score and its context | Environmental comparison |
| Dietary labels and supporting fields | Preference filters |
| Units and product quantities | Comparable calculations |
| Source revision and retrieval date | Reproducibility |

**Tools:** Python, fsspec, PyArrow and pandas. Store prepared tables as Parquet and
provenance as JSON.

The original sample contains 12,288 products without nutrient or quantity fields.
The expanded raw catalog now adds these fields for the same products and pinned
source revision. Reproduce it with `python scripts/fetch_data.py --catalog` and
inspect `data/catalog_audit.json` for measured field coverage. Missing source values
remain missing. The historical snapshot is unchanged; neither sample is
representative of the OFF catalog. Normalization and eligibility are the next step.

Prices and store stock require another source and are outside the first version.
A declared country does not establish in-store availability.

**Output:** a versioned raw dataset and its manifest.

## 3. Build a comparable, usable catalog

- Clean HTML and formatting while preserving source text and languages.
- Standardize nutrient names and measurement units.
- Identify duplicate products and near-duplicate variants.
- Keep missing values explicitly missing; do not replace unknown values with zero.
- Select families with enough complete products.
- Separate incompatible comparison units.
- Record why a product is excluded.

For the first version, substitutions retain the same quantity within compatible
units. Do not automatically replace 500 ml of a drink with 500 g of a solid.

Use published environmental scores in a consistent context, with higher values
representing a better indicator. Do not train another predictor of that score.
A missing score prevents recommending a change on environmental improvement
grounds. Score differences do not represent percentage emission reductions or
kilograms of CO2.

**Tools:** pandas, NumPy, Pydantic and custom Python normalization functions.

**Output:** `catalog.parquet` and a coverage report.

## 4. Create the substitution dataset

This is the main source of project-specific supervision. Annotators assess
product pairs in a defined usage context:

| Original | Candidate | Context | Label |
|---|---|---|---|
| Plain yogurt A | Plain yogurt B | Breakfast bowl | Acceptable |
| Plain yogurt A | Yogurt drink | Breakfast bowl | Requires judgment |
| Plain yogurt A | Cooking cream | Breakfast bowl | Unacceptable |

These are illustrative annotations, not collected findings. Labels are acceptable
substitute, unacceptable substitute, or ambiguous/insufficient information.
Record the reason, context and annotator. A shared category can suggest a pair
for annotation; it cannot establish its label.

Initial target: 600–1,000 annotated pairs across the selected families. Two people
independently annotate a shared subset, then resolve disagreements. This is a
proposed workload, not data already collected.

Include hard negatives: products with similar names or ingredients that serve
different purposes. Avoid accidentally treating valid substitutes as negatives.
One thousand pair labels do not automatically produce one thousand valid triplets:
each triplet needs an acceptable and an unacceptable candidate for the same
original product and context.

**Tools:** a small Streamlit annotation screen, CSV or Parquet storage, and
scikit-learn for agreement statistics.

**Output:** annotated pairs and annotation guidelines.

## 5. Split the data before training

Group duplicates and close variants, then split product groups into training,
validation and test partitions BEFORE constructing pairs and triplets. No product
or near-duplicate may cross partitions.

- Training data updates model weights.
- Validation data selects hyperparameters and acceptance thresholds.
- Test data measures final performance after decisions are fixed.

Mine negatives only within training data. Reserve a human-labeled test set without
weak labels. A random split of pair rows would allow the same product to leak into
training and test data.

**Tools:** scikit-learn group splitting and explicit overlap checks.

**Output:** saved product partitions, training triplets and a held-out human-labeled
evaluation set.

## 6. Establish the baselines

| Baseline | Method |
|---|---|
| Category and rules | Retrieve products in a narrow category and apply compatibility filters |
| TF-IDF | Rank product text using character n-gram similarity |
| Frozen encoder | Rank with a pretrained encoder without updating its weights |

Apply the same eligibility filters and evaluation cases to each. This establishes
whether fine-tuning actually helps.

**Tools:** scikit-learn, NumPy and Sentence Transformers.

**Output:** baseline rankings and evaluation metrics.

## 7. Fine-tune the substitution encoder

Candidate starting model:
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

Represent each product using its name, ingredients and defined usage context.
Both products pass through the same encoder. Categories may filter candidates but
must not reveal artificial training labels. Train with triplets:

```text
Anchor:   the original product
Positive: an acceptable substitute
Negative: an unacceptable substitute
```

The objective brings the anchor closer to the positive and farther from the
negative. Hard negatives look similar in text but serve a different purpose.
This updates the encoder's weights. Compare against frozen embeddings to measure
the contribution of training.

**Tools:**

- PyTorch for model training.
- Sentence Transformers for the encoder and training loop.
- Hugging Face Datasets for training examples.
- SentenceTransformerTrainer.
- TripletLoss, with a deliberately selected distance metric and validation-tuned margin.
- TensorBoard for loss curves and validation metrics.

Select epochs, margin and acceptance thresholds on validation data, never on the
test set. Save trained weights, configuration, base-model revision, random seed,
partitions and training logs. Do not equate similarity with taste preference
without user data. Limited labels may limit the benefit; measure rather than
assume that fine-tuning wins.

**Output:** trained encoder and reproducible training artifacts.

## 8. Encode and index the catalog

Run the trained encoder over eligible products and cache normalized vectors.
At recommendation time:

1. Encode the original product in its usage context.
2. Compute cosine similarity against eligible candidates.
3. Retrieve the highest-ranking alternatives.

**Tools:** Sentence Transformers and NumPy. Exact vector search is sufficient for
the initial catalog. Add FAISS only if catalog size or latency measurements justify it.

**Output:** cached embeddings, product-to-vector mapping and model version.
Similarity is a ranking signal, not an acceptance probability.

## 9. Filter and accept candidates

Apply explicit checks for compatible usage and units, required nutritional and
environmental data, supported dietary preferences, user exclusions and a
validation-selected similarity threshold.

Always include the original product as an option. If no acceptable alternative
exists, keep it and explain the abstention. The model handles substitution
similarity; deterministic checks enforce requirements. Dietary preferences require
sufficient explicit evidence. Missing allergen information does not demonstrate
safety; the MVP does not certify medical or allergy suitability.

**Tools:** Python rules, Pydantic and pandas/NumPy.

**Output:** a small eligible candidate set for each basket position.

## 10. Optimize the complete basket

Define binary decision variables `x[i,j]`: one when candidate j is selected for
basket position i, zero otherwise. Require:

- Exactly one selected product per basket position.
- At most K substitutions.
- Locked products remain unchanged.
- Selected nutritional limits hold.
- Only eligible substitutes can be selected.

Maximize improvement in the basket environmental indicator with an explicit
penalty for changes. Use comparable quantities for the experimental aggregate.
Nutrient totals use actual basket quantities:

```text
protein contribution = (quantity consumed / 100) * protein per 100 units
```

Quantity and nutrient measurement units must match. Do not mix incompatible units.

**Tool:** OR-Tools CP-SAT. Scale decimal coefficients appropriately for its integer
formulation. Report these outcomes distinctly:

- Optimal solution found.
- Feasible solution found within the time limit.
- Constraints proven infeasible.
- No solution established within the time limit.

Only report optimality when the solver proves it. If constraints are infeasible,
let the user revise them; do not silently relax them.

**Output:** selected basket, objective value, constraint totals and solver status.
The environmental aggregate is an experimental basket index, not an official
footprint. Its changes are not kilograms of CO2 or percentages of emission reduction.

## 11. Present the recommendation

| Original product | Proposed substitute | Reason | Measured differences |
|---|---|---|---|
| Product A | Product B | Accepted substitute for the selected use | Environmental score and nutrient differences |

Also show the number of substitutions, before-and-after basket totals, constraint
compliance, missing information, abstentions and data provenance. Users can reject
a substitution or lock a product and run the optimizer again.

**Tools:** Streamlit, pandas and Plotly. Explanations use templates populated with
calculated values. An LLM is unnecessary for this step.

## 12. Evaluate the model and optimizer separately

Freeze the test set and evaluation rules before measurement.

Substitution metrics:

- Human-judged precision@3.
- Coverage: how often acceptable alternatives can be offered.
- Abstention rate.
- Results by product family and language.
- Triplet ranking accuracy as a training diagnostic.

Recall@k requires a sufficiently annotated candidate pool. Unreviewed candidates
cannot automatically count as incorrect or true negatives.

Optimization metrics:

- Constraint compliance.
- Index improvement among accepted substitutions.
- Number of changes.
- Runtime.
- Solver status and optimality gap where available.
- User acceptance of the revised basket.

| Experiment | Question |
|---|---|
| Rules vs frozen encoder | Does pretrained representation help? |
| TF-IDF vs frozen/fine-tuned encoder | Does semantic representation outperform text overlap? |
| Frozen vs fine-tuned encoder | Does our training improve substitution quality? |
| Greedy vs optimizer, same candidates | Does whole-basket optimization help? |

Evaluate held-out baskets with explicit quantities and infeasible cases. Report
test size and uncertainty as well as results by family. Compare the optimizer
against exhaustive enumeration for tiny baskets. Add a user acceptance study.
Retain negative results; there are no measured results for this direction yet.

**Tools:** scikit-learn, NumPy, pandas, pytest and Plotly.

**Output:** reproducible metrics, plots and error analysis.

## 13. Reproducibility and delivery

Save dataset versions/checksums, annotation guidelines and labels, product-group
partitions, model configuration/weights, evaluation configuration, results and
software dependency versions.

**Tools:** Git, GitHub, GitHub Actions, pytest and pinned Python dependencies.
GitHub Actions runs small integrity and correctness checks. Full training is a
separate reproducible command, not a requirement on every commit. Store large
trained artifacts as release assets or in a model repository instead of repeatedly
committing them to ordinary Git history.

## Complete proposed tool stack

| Responsibility | Tool |
|---|---|
| Main implementation | Python |
| Data retrieval | fsspec, PyArrow |
| Data preparation and storage | pandas, NumPy, Parquet |
| Validation | Pydantic |
| Annotation interface | Streamlit |
| Baselines and grouped splitting | scikit-learn |
| Deep learning | PyTorch |
| Encoder and fine-tuning | Sentence Transformers |
| Training dataset handling | Hugging Face Datasets |
| Training monitoring | TensorBoard |
| Candidate search | NumPy cosine similarity; FAISS only if needed |
| Basket optimization | OR-Tools CP-SAT |
| User interface | Streamlit |
| Charts | Plotly |
| Tests | pytest |
| Version control and automated checks | Git, GitHub, GitHub Actions |

Project-specific work comprises the substitution dataset, compatibility rules,
training setup, evaluation design, basket optimization formulation and user workflow.

## Implementation order

Use steps 1–13 above as the canonical numbering and work through them in order,
skipping completed steps. Consult [PROJECT_STATUS.md](../PROJECT_STATUS.md) for the
current handoff and update it in every commit as required by
[AGENTS.md](../AGENTS.md).

Raw catalog acquisition (step 2) was completed first. Step 1 is next, followed by
step 3. Establish product groups before building annotation pairs in step 4, then
freeze and verify the partitions in step 5. Reproducibility checks run throughout;
step 13 also covers final delivery. Explain and record other dependency-driven
exceptions in the status tracker rather than renumbering steps.

## Technical references

- [Sentence Transformers: triplet loss](https://sbert.net/docs/package_reference/sentence_transformer/losses.html).
- [Sentence Transformers: training workflow](https://sbert.net/docs/sentence_transformer/training_overview.html).
- [Sentence Transformers: evaluation tools](https://sbert.net/docs/package_reference/sentence_transformer/evaluation.html).
- [OR-Tools: CP-SAT optimization](https://developers.google.com/optimization/cp/cp_solver/).
