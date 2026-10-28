# AI layers: proposal and supplied experiment notes

Added on 28 October 2026 from the supplied conversation notes.

Status: this document preserves a proposal and historical progress notes, not a
verified execution log. The deterministic claim auditor is present at commit
`58de594`. The embedding pipeline, fine-tuned transformer and Ollama adjudicator
are proposed work; this documentation commit does not implement them or validate
the technical estimates below. The selected next step in the notes is embeddings.

## Original supplied text

Layer 1 — Embeddings (PyTorch, via sentence-transformers)

Job: match ingredient text to allergen and claim concepts across languages.

This is where deep learning genuinely wins, and you can prove it. A keyword list for “milk” misses lactosérum, caseinato, whey powder, lactose. A multilingual embedding model puts them all near each other without you writing a dictionary. paraphrase-multilingual-MiniLM-L12-v2 is ~120 MB, runs on CPU, embeds your 12k products in a couple of minutes.

Proof it earned its place: recall of hidden allergens vs a hand-written keyword list, on the same 100 hand-checked products. If embeddings don’t beat the list, say so — that’s your second honest negative result and it costs you nothing.

Layer 2 — Fine-tuned transformer (PyTorch proper)

Job: the category consistency model, replacing TF-IDF + logistic regression.

Fine-tune MiniLM for a few epochs on your category data. On an M-series Mac with MPS this is minutes, not hours.

Proof: head-to-head against the TF-IDF model on the identical split. You already have the incumbent and the harness — this is the cleanest experiment in the whole project, and either outcome is publishable in your write-up. (“A 22M-parameter transformer beat / did not beat character n-grams on 400 examples” is a genuinely interesting finding at this data size.)

Layer 3 — Local LLM (Ollama)

Job: explanation and adjudication — not detection.

This distinction is the one that’ll impress. The deterministic detectors decide what is flagged; the LLM writes why, in a sentence a volunteer can act on: “Tagged vegan, but the ingredient list contains ‘lactosérum’ (whey), a dairy derivative.”

Two rules that make it defensible:

Structured output only — JSON schema, fixed fields. Ollama supports a format schema.
Grounding check — any ingredient the model cites must appear verbatim in the source text, verified by substring match in code. If it doesn’t, you discard the output and count it as a hallucination.

Proof: agreement with your hand labels on 50 cases, plus a measured hallucination rate. Nobody in that room will have a measured hallucination rate.

Use the small model (ornith:9b) for bulk and the 27B for a spot-check sample — comparing the two is itself a nice result.

The table that makes it a PAIBS project

Component	Simple version	AI version	Winner
Allergen matching	keyword list	multilingual embeddings	measure it
Category consistency	TF-IDF + logreg	fine-tuned MiniLM	measure it
Explanation	fixed template	local LLM	measure agreement + hallucinations

Three ablations, three honest answers. That’s the whole course in one table.

Practicalities: cache embeddings to disk (compute once, commit the vectors), and gate the LLM step behind a flag with cached outputs committed — CI can’t pull Ollama models, and you want that green badge to stay green.

Start with Layer 1. It’s the smallest change, it’s the one most likely to produce a real jump, and it makes Layer 3 possible by giving you flagged cases worth explaining.

Want me to scaffold Layer 1 — embedding pipeline, keyword baseline and the comparison harness — in the existing repo?

Fields check done: the sample has labels_tags and ingredients_text, but no allergen tags — so allergen misdeclaration needs a re-fetch. What is checkable right now: 227 vegan, 285 vegetarian, 489 no-gluten, 87 no-lactose, 57 no-palm-oil products that also carry ingredient text. That’s ~1,145 claims to audit. Building the keyword baseline on that first.

The one failure is my test expectation, not the code — “porc” matched before “gélatine”, and both are correct meat hits. Letting the case accept either.

66 flags from 1,145 claims. The number means nothing until I look at them — checking the vegan and palm-oil ones by hand now.

This is the real finding, and it’s a precision problem: nearly every vegan flag is a “may contain traces of milk” allergen warning, not an ingredient — which is perfectly legitimate on a vegan product. Same with German “ohne Fleisch” (without meat). The naive baseline is mostly wrong, which is exactly what the AI layer has to fix. Making the baseline honest first.

Two of those three are still false positives — a German “Kann … enthalten” warning without the word Spuren, and “ferments de yaourt végétalien”. Fixing both.

Pushed — commit 58de594, CI green.

What’s now in the repo: contradictions.py, a deterministic claim auditor. It checks every product whose label claims vegan, vegetarian, gluten-free, lactose-free or palm-oil-free against its own ingredient list, across five languages.

And it found real things. Five candidate label errors in a live public database:

a gluten-free soy sauce whose ingredients are “soy bean, corn, wheat”
a gluten-free cracker whose first ingredient is “harina de trigo integral 85%”
a gluten-free beer whose ingredient text literally says “CONTAINS BARLEY”
a gluten-free brioche at 53% wheat flour, and one more with wheat in damaged text

That’s your demo. You point at the screen and read the ingredient list out loud.

The more interesting part is what it got wrong. The first run raised 66 flags, and when I read them, almost all were “may contain traces of milk” — a cross-contamination warning, which is entirely normal on a vegan product — plus negations like “ohne Fleisch” and “fără gluten”. The naive version was mostly false positives. Filtering those clauses drops it to 39 flags, and vegan went from 17 flags to 1.

And the failure that’s left is the thesis for your next layer. All 27 lactose flags are aged hard cheeses — Gruyère, Grana Padano, Appenzeller, Pecorino. They list milk, they claim lactose-free, and both are correct, because aged cheese is naturally almost lactose-free. Same with the wheatgrass juice (grass, not grain) and the gluten-removed beer. No term list can resolve those. They need domain knowledge — which is precisely the job you’d hand an LLM, and now you have a measured baseline to judge it against.

So the ablation table from earlier is no longer hypothetical: 66 flags naive → 39 with context modelling → 5 candidate errors, 4 domain ambiguities, 3 false positives after a hand review that’s written down in results/contradictions_desk_review.csv.

24 self-checks cover the tricky strings (cocoa butter isn’t dairy, coconut milk isn’t dairy, maltodextrin isn’t gluten, corn semolina isn’t wheat) and they run in CI alongside the original eight.

One caveat worth keeping in the write-up: these are review requests, not confirmed errors — the ingredient text itself can be wrong or OCR-damaged, and one of the three false positives was exactly that (“vegetable fat” broken into “vegetc ble”).

Pushed a claim-audit baseline that checks vegan, gluten-free and similar label claims against the product's own ingredient list. It found 5 candidate real label errors in the sample, and CI is green on commit 58de594. The embedding and Ollama layers are not built yet.
Build the embedding layer next, or the Ollama adjudicator?
Embeddings next

Embeddings next

Starting the install in the background while I write the experiment.

Install torch and sentence-transformers in a venv

Design the cross-lingual experiment

Run it and compare against the keyword baseline

Hand-check what embeddings found alone

Write up and push
