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

Step 3 is one command. Name each export after its reviewer, for example
`ana.json` and `ben.json`, and run it before the two reviewers talk:

```sh
python scripts/review_agreement.py ana.json ben.json --report pilot_agreement.json
python scripts/review_agreement.py ana.json ben.json --tasks data/pairs.json   # the 300 sampled pairs
```

With `--tasks data/pairs.json` the same checks run against the 300 sampled pairs,
and the report adds identical-decision counts per partition and per sampling
strategy. Label Studio imports a list of tasks, so import the `tasks` list of
`data/pairs.json`, not the whole file. If an export declares a model as its
annotator, the report names that reviewer and states that the figure is not
agreement between two people. The script cannot prove that an undeclared export
was made by a person.

`data/pairs_review_model.json` is such a file for the 300 sampled pairs: a model
drafted every label and reason. `data/pairs_review_record.json` records that one
person reports having checked the draft and that nothing changed. A second
reviewer who wants a measurable agreement figure should label the 300 pairs
without opening that file, then run the command above against it.

It refuses to compute anything unless both exports hold all 36 pairs with exactly
one submitted annotation, one label and a nonempty reason each, and unless the
task data still match the task file. It then prints the identical-decision count,
the three-by-three label table, Cohen's kappa, per-family counts, every
disagreement with both reasons, and the pairs either reviewer marked “possible
duplicate” with their group IDs. It does not write final labels. Label Studio
omits unreviewed tasks from an export by default, so a missing pair means it was
not reviewed. Full exports include each reviewer's Label Studio user ID; decide
as a team where the exports are stored before adding them to the repository.

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
`data/alias_report.json` (from `scripts/inspect_aliases.py`) currently proposes
five such aliases, one each for five of the 72 reserved groups; they are listed
under `calibration`. No pilot pair joins two groups that the report links.
`data/partitions.json` places the reserved groups and those aliases in a
`calibration` partition and the remaining groups in train, validation and test.
`scripts/build_pairs.py` generates those further pairs inside one partition at a
time and writes them to `data/pairs.json` in this same form.
`scripts/build_anchored_pairs.py` writes `data/anchored_pairs.json`, in which each
anchor product meets up to four candidates so that labels can form triplets; label
that file in the same way, with `--tasks data/anchored_pairs.json` for the check. Pilot agreement measures reviewer consistency on this
deliberately diverse sample.
