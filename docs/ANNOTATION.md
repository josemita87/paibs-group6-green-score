# Substitution pilot

Two people independently review the same 36 directed pairs, 12 per family.
For each pair, decide whether someone could use the candidate in place of the
original for the stated purpose, keeping the same portion and preparation.

| Family | Use for this pilot | Evidence to look for |
|---|---|---|
| Yogurts | Eat with a spoon at breakfast, 100 g | A spoonable yogurt can fit even if the flavor differs. Check whether either product is described as a drink. |
| Breakfast cereals | Serve in a bowl with cold milk, 100 g | Flakes and muesli can both fit. Check for bars or products that require cooking. |
| Plant-based milk alternatives | Pour over cereal, 100 ml | Check for a ready-to-pour drink. Coconut milk sold as a cooking ingredient can share a name with a cereal drink. |

## Record a decision

Read both names and ingredient lists. Decide in the direction shown. Choose one
label and give one concrete reason referencing the products and their use.

| Label | When to use it | Example reason |
|---|---|---|
| acceptable | Both products clearly fit the stated use with the same preparation. | “Both are ready-to-eat flakes that can be served with cold milk.” |
| unacceptable | The original fits, and specific evidence shows the candidate would require a different use or preparation. | “The original is spoonable. The candidate is explicitly a yogurt drink.” |
| ambiguous | The original itself conflicts with the context, the format is unclear, the evidence conflicts, or you cannot interpret the text reliably. | “The name says coconut milk and the ingredients give no indication whether it is a drink or cooking cream.” |

Judge ordinary use. A different flavor, brand, language or plant base alone does
not establish incompatibility. Personal taste, allergy suitability, protein and
environmental improvement are outside this judgment. If the texts appear to
describe the same commercial product or a pack-size variant, mark the reason
“possible duplicate” and describe the evidence. The coordinator should inspect
the grouping before using those examples.

## Run the independent review

1. Use the same [task file](../data/annotation_pilot.json) in two separate local
   Label Studio projects. Apply the [labeling interface](annotation_form.xml) to
   each. Give each reviewer only their own project and these instructions.
2. Review all 36 tasks independently and export the full JSON from each project.
   Keep each export with its reviewer identifier. Join using `data.pair_id`,
   which is shared across projects even when their internal task IDs differ.
3. Check for exactly one label and a nonempty reason per reviewer and pair.
   Record the count of identical decisions out of 36 and a three-by-three label
   table before discussion. Retain both original exports.
4. Resolve disagreement together, keeping the final decision and reason in a
   separate record keyed by pair ID. Retain unresolved cases as ambiguous.
   Revise the guidelines where a rule produced recurring disagreement.

## Sampling and use

The generator verifies the complete Parquet contents against the step-3
manifest. Within each family and pilot unit, it takes the lowest eligible barcode
per group and reserves 24 distinct groups for calibration before forming pairs.
It balances five common source languages and a sixth bucket for other languages,
then favors less-used normalized brand strings. A stable barcode hash breaks
ties. Six pairs per family are chosen greedily by the highest Jaccard overlap
of name tokens among the remaining groups. The remaining groups are paired in
selection order. Neither strategy assigns a label.

Use these tasks for guideline calibration only. The union of `original_group_id`
and `candidate_group_id` in the task file is the calibration reservation for
this catalog fingerprint. Exclude these groups and any subsequently identified
aliases from model splits and the separate 30-request classroom benchmark.
Before scaling up, inspect renamed near-duplicates and freeze the remaining
groups into train, validation and test partitions. Generate all further pairs
within those partitions. Pilot agreement measures reviewer consistency on this
deliberately diverse sample.
