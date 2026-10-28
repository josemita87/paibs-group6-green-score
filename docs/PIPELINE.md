# Proposed technical pipeline

## Product and scope

Input: basket products, comparable quantities, preferences and a maximum of K
changes. Output: concrete substitutions, verifiable differences and the option
to keep each original product. Target user: a person planning their grocery shopping.

MVP: three product families with comparable uses, selected after auditing coverage;
for example, breakfast drinks, yogurts and cereals. Sharing a category does not
necessarily make two products substitutes. A declared country does not establish
in-store availability. Exclude budget constraints until prices include units,
dates and sources.

## 1. Catalog and data

Keep the historical snapshot unchanged. Prepare a new versioned dataset that adds
nutrients per 100 g/100 ml, units, quantities and evidence for preference filters.
Preserve provenance, missing values and the context of each score. Do not replace
unknown values with zero. Compare solids and liquids using compatible units.
The current sample lacks `nutriments`: this blocks the nutritional MVP; nutritional
constraints are not implemented yet.

Use published environmental scores in a consistent context, with higher values
representing a better indicator. Do not train another predictor of that score.
A missing score prevents recommending a change on environmental improvement
grounds. Do not interpret score differences as percentage emission reductions
or kilograms of CO2.

## 2. Substitution dataset: project-specific supervision

Annotate product A/product B pairs as acceptable substitutes, unacceptable
substitutes or ambiguous, recording the reason and usage context. Initial target:
600–1,000 pairs across the selected families. Two annotators label a shared subset
to measure agreement and resolve disagreements. This is a proposed workload,
not data already collected. Narrow categories can suggest pairs but are not ground truth.

Include hard negatives: products with similar names or ingredients that serve
different purposes. Avoid accidentally treating valid substitutes as negatives.
Split training, validation and test data by product groups and near-duplicate
variants BEFORE constructing pairs; no product or variant may cross partitions.
Mine negatives only within training data. Reserve a human-labeled test set without
weak labels.

## 3. Fine-tune the substitution model

Candidate starting point: `paraphrase-multilingual-MiniLM-L12-v2` through Sentence
Transformers/PyTorch. Input: name, ingredients and usage context. Categories may
filter candidates but must not reveal artificial training labels. Both products
use the same encoder.

Update its weights using triplets (product, acceptable substitute, hard negative)
with a contrastive objective or TripletLoss. The objective brings substitutes
closer and separates misleading matches. Compare against frozen embeddings to
measure the benefit of fine-tuning. Select the margin, epochs and acceptance
threshold on validation data, never on the test set. Save the base model revision,
weights, random seed, partitions and configuration. Do not equate similarity with
taste preference without user data.

## 4. Candidate retrieval and constraints

Precompute catalog embeddings. For each product, retrieve candidates by cosine
similarity and apply unit, usage, data coverage and preference filters. Exact
search is sufficient for a small catalog; a vector index is optional.

Select the similarity threshold on validation data to prioritize precision.
Abstain when evidence is insufficient. A dietary preference requires sufficient
explicit evidence; an allergen's absence from the text does not establish safety.
The MVP does not certify medical or allergy suitability.

## 5. Basket optimization

Binary variables x[i,j] select candidate j for product i. Include the original
product as a candidate. Require one selection per basket position and at most K
changes. Exclude unacceptable substitutes before optimization.

Initial objective: maximize environmental score improvement weighted by comparable
quantities, with an explicit penalty for changes. Present the aggregate as an
experimental basket index, not an official environmental footprint.

Optional constraints when data is complete: total protein >= a minimum and sugar
or salt <= selected limits. Convert per-100-g/ml values to basket quantities before
summing; do not mix incompatible units. Use integer programming, for example
OR-Tools CP-SAT with scaled integer coefficients. If constraints are infeasible,
report this and let the user revise them; do not silently relax them.

## 6. Results and explanations

Show the original product, substitute, comparable data, provenance, total changes
and reason for acceptance. Generate text from templates using calculated values.
An LLM is not required for training, recommendation, optimization or explanation.

## 7. Evaluation and ablations

Freeze the test set and evaluation rules before measurement. Compare three
systems on the same cases:

| System | What it measures |
|---|---|
| Same category + rules + best score | Simple baseline |
| Frozen encoder + optimizer | Contribution of pretrained representations |
| Fine-tuned encoder + optimizer | Contribution of project-specific fine-tuning |

Also compare greedy selection against the optimizer using identical candidates
to separate model improvements from algorithm improvements.

Metrics: human-judged substitution precision@3, recall@k when the candidate pool
has sufficient annotations, coverage/abstentions, constraint compliance, latency
and index improvement conditional on accepted substitutions. Evaluate held-out
baskets with explicit quantities and infeasible cases. Report results by family,
test size and uncertainty. Do not automatically treat unannotated candidates as
true negatives. Add a user acceptance study.

Training adds value only if it improves on the baseline; retain negative results.
There are no measured results for this new project direction yet.

## Implementation order

1. Audit and expand the catalog; select families with sufficient coverage.
2. Annotate pairs, fix partitions and build the baseline.
3. Evaluate the frozen encoder; fine-tune the encoder and compare.
4. Implement the optimizer and compare against greedy selection and exhaustive
   enumeration on small cases.
5. Build the demo and evaluate baskets with users.

## Technical references

- [Sentence Transformers: losses and triplet training](https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html).
- [OR-Tools: CP-SAT optimization](https://developers.google.com/optimization/cp/cp_solver).
