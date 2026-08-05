# Claims are generated structured; prose is rendered from them, never parsed back

**Status:** accepted — Phase 4 design is frozen as of this ADR.

The original plan had the Assess node write prose and Tier 1 re-extract numbers from it.
That turns verification into an NLP problem whose characteristic failure is the *false
contradiction* — rounding ("~450 MW" vs 448.3), unit restatement (years vs days), and above
all derived values, which appear in no source row by construction and would flag as
contradicted despite being correct. Derived figures are most of what a risk assessment
actually says, so this would have pushed Tier 1 coverage down and inflated Tier 3, shrinking
the project's thesis.

We invert it. The Assess node emits structured claims only, each carrying its text, the
values it asserts, how each value was derived, and the source rows it cites. Tier 1 is then
a join and an arithmetic re-check — deterministic, exact pass/fail — and the final prose is
rendered by concatenating the text of claims that passed. A failed claim cannot appear as
verified, because the renderer reads the verification result.

## The derivation enum

`derivation` is a **closed set**: `direct`, `sum`, `count`, `median`, `ratio`. Each has
exactly one verifier function. Anything outside the enum is a hard fail. Tolerance is
per-unit and written into the README — MW to the nearest 10 or 5%, years to one decimal,
percentages to the whole point — because "within tolerance" is otherwise vibes with a table
of contents. `source` is likewise a closed enum: `caiso_raw | lbnl`, those exact strings
everywhere.

## Distribution stats are quoted, not re-derived

`median`, percentiles, and the outputs of the four domain analysis functions stay *in* the
enum, but their verifier is a **faithful-quotation check** — claim value equals function
return — not recomputation. Re-deriving them through Tier 1 would require a claim to cite
every row of the cohort (235 row IDs for a CAISO timeline) just so the verifier could redo
what tested code already did. That verifies the wrong party: the analysis functions are
deterministic, unit-tested code; the model is not.

## No free-hand row selection

Every tool result carries a `tool_call_id` and its full returned row-ID set, persisted in
the trace. Each claim value references the `tool_call_id` it derives from, and Tier 1
compares the cited rows against what that call actually returned — set equality for
`sum`/`count`/`median`/`ratio`, membership for `direct`. An agent citing 2 of 3 returned
rows and summing them correctly still fails. Paired with the rule that all narrowing happens
in SQL — the agent never mentally filters a broader result set — this makes free-hand row
selection structurally impossible rather than merely discouraged.

## The limit that remains, stated rather than hidden

Tier 1 proves arithmetic, provenance, and full coverage of the returned rows of the query a
claim derives from. It does **not** prove that query was the *right* query — wrong POI
argument, missing filter, wrong tool. Every number then verifies perfectly while the
assessment is about the wrong place. The offline retrieval eval (Eval 2) closes the
deterministically definable part of that gap; the two are complementary, not substitutes.
The irreducible residual is comparability judgment — whether this project is fairly compared
against that cohort at all — and that is the honest content of Tier 3.

## Rejected: promptfoo for judge calibration

Considered for running the Tier 2 judge against the hand-labeled set. Rejected: Tier 1 is
deterministic Python where it contributes nothing, the calibration run is ~40 lines of
pytest over a labeled CSV, and the labeled CSV — the actual work — is needed either way.
Adding a config DSL and a web UI whose defense is weaker than this project's Kafka defense
costs more credibility than it buys. Revisit only if several judge prompts or models need
systematic comparison across the label set.
