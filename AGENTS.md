# Contributor instructions

These instructions apply to the whole repository and to both AI assistants and
human developers. Keep code, documentation, UI text and commit messages in English.

## Before starting work

1. Read `PROJECT_STATUS.md`, `docs/PIPELINE.md` and the relevant code.
2. Inspect the Git working tree and recent commits. Preserve other contributors'
   changes; do not overwrite or revert work you did not create.
3. State a short implementation plan before editing. Keep the scope small.
4. Use the numbered steps in `docs/PIPELINE.md` as the shared roadmap. Work on the
   earliest unfinished step unless the user assigns another scope. Explain and
   record dependency-driven exceptions rather than silently renumbering steps.

## Every commit must update project status

Update `PROJECT_STATUS.md` in the SAME commit as the work, including documentation,
maintenance and fixes. Do this before committing, not as a later follow-up.

- Keep the current focus, step statuses and next action accurate.
- Add a dated entry to the change log: what changed, affected step(s), validation
  actually performed, and any remaining limitation or blocker.
- Distinguish planned work, implementation, local checks and remote CI results.
  Never claim tests passed or CI succeeded without observed evidence.
- A documentation change does not complete an implementation step. State when
  runtime tests were not needed or were not run.
- Do not put the current commit's hash inside its own status update. Git provides
  the exact version history; use hashes only for already-existing commits.
- If a step does not advance, record the maintenance or coordination change and
  leave its status unchanged.

Before pushing, review the final diff, run checks appropriate to the change and
ensure every new authored commit includes its status update. Fetch remote changes
and reconcile both code and status when another contributor has advanced the
branch. Preserve relevant entries from both sides; do not force-push shared history.

Keep commits focused, minimal and in English. Keep `PROJECT_STATUS.md` concise:
use it for the current handoff and short change entries, not full transcripts.
Record completed work and validation before ending a handoff, including uncommitted
work when a commit has not been requested. Do not invent contributor ownership.

## Data and evaluation

Preserve the pinned historical snapshot and provenance. Raw field coverage is not
validated product eligibility. Do not present proposed models or experiments as
implemented or evaluated. Group products and near-duplicate variants before
constructing annotation pairs so that train/test leakage cannot be introduced.

## Project documents

Write concrete observations, decisions, numbers and next actions. Avoid generic
filler, slogans, decorative callouts and repetitive summary tables. Prefer plain
paragraphs and restrained headings. Use a table only when readers need to compare
actual values or repeated records. Keep classroom documents in `output/Session2/`
unless the user specifies another location. Distinguish plans from measured results.
