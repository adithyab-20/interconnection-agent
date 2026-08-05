# Spec: Verified Interconnection Assessment — Vertical Slice

**Scope:** Phases 1–4 of `build-spec.md`, plus the first 10 golden
cases. JSON/CLI output; no dashboard. This is the demoable milestone agreed in grilling —
the point at which the project is coherent enough to show someone.

**Governing decisions:** ADR-0001 (location hierarchy, per-source views), ADR-0002 (vintage
cohorting), ADR-0003 (structured claims, Tier 1). Vocabulary per `CONTEXT.md`.

---

## Problem Statement

A siting analyst evaluating a proposed generation project needs to know what the
interconnection queue implies about its risk: how crowded the relevant POI already is, how
long comparable projects historically took to reach energization, and how often projects
like it withdraw instead of getting built.

That information is public — every ISO publishes its queue — but it is not usable as
published. CAISO's workbook spreads projects across three sheets with headers on row 4, up to
three fuel types per row, and a free-text station field where the same substation appears as
"Devers Substation 230kV Bus" and "Devers Substation 230 kV". Answering even a simple question
means hours of spreadsheet work, and the analysis that follows is where the real errors hide:
a raw count of projects ahead of you overstates competition because most will withdraw, a
pooled withdrawal rate is biased low because recent vintages haven't had time to resolve, and
a median time-to-energization is a survivor statistic that only sees the projects that made it.

An LLM will happily answer all of these questions in fluent prose, and some of the numbers
will be invented. For a decision with capital behind it, a confident paragraph whose figures
cannot be traced to a specific row is worse than no answer, because it is indistinguishable
from a correct one.

## Solution

An agent that produces an interconnection-risk assessment in which **every factual claim is
tied to the specific source rows it came from, and checked by code before it reaches the
reader.**

The design inverts the usual arrangement. The model does not write prose that is later
checked; it emits **structured claims**, each carrying its values, how each value was derived,
and the rows it cites. Deterministic code then verifies each claim — the cited rows exist, the
stated derivation reproduces the number, and the citation covers the *full* result set of the
query it came from — and prose is rendered only from claims that passed. A claim that fails
cannot appear as verified, because the renderer reads the verification result.

Domain judgment lives in tested Python, not in the prompt. Withdrawal rates are cohorted by
vintage; time-to-energization carries its survivor caveat; saturation is pending MW against
historically energized MW. These caveats are emitted *by the analysis functions*, so the model
cannot smooth them away.

Where verification genuinely cannot reach, the output says so rather than implying coverage it
doesn't have.

## User Stories

**Analyst — getting an answer**

1. As a siting analyst, I want to ask about a named POI in plain language, so that I don't have to know the queue's internal identifiers.
2. As a siting analyst, I want a breakdown of active, completed, and withdrawn projects at a POI, so that I can see the competitive picture rather than a single count.
3. As a siting analyst, I want total pending MW at a POI compared against MW historically energized there, so that I can judge saturation against what the local grid has actually absorbed.
4. As a siting analyst, I want the historical distribution of time-to-energization for comparable projects, so that I can set expectations from evidence instead of the operator's proposed dates.
5. As a siting analyst, I want that distribution as a median with p25/p75, so that I can see the spread rather than a single misleading average.
6. As a siting analyst, I want a withdrawal rate for comparable projects, so that I can discount the queue ahead of me by how much of it will never get built.
7. As a siting analyst, I want CAISO-specific and national figures side by side, so that I can tell local conditions apart from the national picture.
8. As a siting analyst, I want to ask about a county or study region when I don't have a specific POI, so that early-stage siting is still supported.
9. As a siting analyst, I want an assessment that reads as connected prose rather than a table dump, so that I can use it directly in a memo.

**Analyst — trusting the answer**

10. As a siting analyst, I want every number to carry the rows it came from, so that I can check any figure myself.
11. As a siting analyst, I want each claim marked verified, unverified, or contradicted, so that I know which parts I can rely on.
12. As a siting analyst, I want to expand a verified claim and see the actual source rows, so that verification is something I can inspect rather than a badge I have to trust.
13. As a siting analyst, I want a claim whose arithmetic doesn't reproduce to be withheld rather than shown with a warning, so that a wrong number never reaches a memo.
14. As a siting analyst, I want to know when a figure rests on few observations, so that I don't over-read a median drawn from a handful of projects.
15. As a siting analyst, I want time-to-energization always labelled as a survivor statistic, so that I understand it is biased optimistic.
16. As a siting analyst, I want withdrawal rates reported per vintage with the unresolved count, so that I'm not handed a pooled rate that understates the true one.
17. As a siting analyst, I want projects whose POI could not be normalized to be counted and disclosed, so that a quiet exclusion doesn't distort a saturation figure.
18. As a siting analyst, I want an explicit "no matching evidence" when a query has no rows, so that the agent doesn't broaden my question or invent an answer.
19. As a siting analyst, I want to know which claims need human review, so that I can route them to someone with domain expertise.
20. As a siting analyst, I want to know that the tool covers generation interconnection only, so that I don't mistake it for load-side analysis.

**Developer — data**

21. As a developer, I want CAISO's three sheets ingested into one canonical `projects` table, so that downstream code sees one shape.
22. As a developer, I want up to three (type, MW) pairs stored as child rows, so that hybrid projects aren't crammed into repeated columns.
23. As a developer, I want `iso` and `study_region` as separate columns, so that a national comparison and a sub-CAISO comparison are visibly different scopes.
24. As a developer, I want LBNL's West/Southeast rows stored with `iso = NULL` and a `non_iso_entity`, so that a non-ISO catch-all is never mistaken for an operator.
25. As a developer, I want the raw station string preserved beside its normalized form, so that provenance can always show the original cell.
26. As a developer, I want POI aliases resolved through a checked-in, human-reviewed table, so that grouping is deterministic and auditable.
27. As a developer, I want fuzzy matching confined to offline alias proposal, so that no probabilistic join ever runs beneath a verification claim.
28. As a developer, I want unmappable POIs flagged rather than guessed, so that coverage is a reported number instead of a hidden assumption.
29. As a developer, I want ingest keyed on natural IDs, so that re-running never duplicates and stored eval row IDs survive.
30. As a developer, I want per-source views enforcing the source filter, so that a forgotten `WHERE` cannot double-count CAISO projects present in both datasets.
31. As a developer, I want every ingest run to report rows ingested, dropped, and unmapped with reasons, so that fidelity is measured rather than assumed.
32. As a developer, I want my CAISO-derived rates checked against LBNL and Public Advocates during the build, so that a divergence surfaces as a failing test.
33. As a developer, I want the status vocabulary mapped in explicit configuration, so that a reviewer can challenge the mapping without reading ETL code.

**Developer — agent and verification**

34. As a developer, I want all narrowing done in SQL, so that the agent never filters a broad result set in its head and then cites a self-selected subset.
35. As a developer, I want every tool call to persist its ID and full returned row set, so that verification can check citations against what was actually returned.
36. As a developer, I want the model to emit structured claims rather than prose, so that verification is a join instead of an NLP problem.
37. As a developer, I want `derivation` restricted to a closed enum with one verifier each, so that an unrecognized derivation is a hard failure rather than a silent pass.
38. As a developer, I want a per-unit tolerance table in version control, so that "within tolerance" is a specification and not a judgment call.
39. As a developer, I want rounding and unit restatement to pass verification, so that natural phrasing isn't punished as contradiction.
40. As a developer, I want derived figures like sums and ratios to be verifiable, so that the most common claims aren't pushed into the unverified bucket.
41. As a developer, I want distribution statistics quoted from tested functions rather than re-derived, so that verification checks the model's faithfulness instead of re-testing my own code.
42. As a developer, I want set-equality enforced between cited rows and the tool's returned rows, so that omitting a row fails even when the arithmetic is internally consistent.
43. As a developer, I want prose rendered only from verified claims, so that an unverified figure cannot reach the reader as prose.
44. As a developer, I want the analysis functions unit-tested before any agent wiring, so that a downstream bug is never chasing an upstream one.
45. As a developer, I want a mutation suite of corrupted claims, so that I can measure the verifier's false-accept and false-reject rates instead of asserting it works.
46. As a developer, I want ten golden cases with independently written expected values, so that a shared bug cannot produce a passing test.
47. As a developer, I want evals runnable in CI on every PR, so that a regression is caught by the build rather than by me noticing.
48. As a developer, I want token and turn caps per assessment, so that a looping agent is a failed request rather than a bill.
49. As a developer, I want a spend cap set before the first agent run, so that cost is bounded by configuration rather than vigilance.
50. As a developer, I want structured logs and per-assessment metrics, so that latency, cost, and pass rates are observable from the start.

**Reviewer**

51. As a reviewer, I want the README to state exactly what verification does and does not prove, so that I can judge the claim rather than take it on faith.
52. As a reviewer, I want measured numbers with commands to reproduce them, so that I can distinguish measurement from estimate.
53. As a reviewer, I want the reasoning behind excluded technologies recorded, so that I can see scope as judgment rather than omission.
54. As a reviewer, I want the ETL's normalization rules documented, so that I can assess the hardest part of the data work.
55. As a reviewer, I want the "why an agent and not a script" position stated explicitly, so that the shrinking LLM role reads as design intent.

## Implementation Decisions

**Modules**

- **`ingest`** — CAISO reader (three sheets, header row 4) and LBNL reader (`03. Complete Queue Data`, header row 2), both mapping into the canonical schema. Returns an `IngestReport` with per-source counts of rows read, written, dropped-with-reason, and unmapped POI MW.
- **`poi`** — alias-table application. Deterministic exact-match lookup at runtime. The offline proposal tool (rapidfuzz/`pg_trgm`) is a separate developer-facing script, not importable by runtime code.
- **`analysis`** — the four domain functions plus generic distribution statistics. Each returns `(result, provenance, caveats)`.
- **`agent`** — LangGraph graph: Plan → Retrieve → Analyze → Assess → Verify → Render.
- **`verify`** — Tier 1. Pure function of `(claims, trace, db)`; no model, no network.
- **`api`** — FastAPI `POST /assess` → job ID, `GET /assess/{job_id}` → status and result. Celery worker executes the graph.

**Schema** (per ADR-0001)

- `projects`: `source`, `native_id`, `status`, `q_date`, `proposed_online_date`, `actual_online_date`, `withdrawn_date`, `ia_date`, `county`, `state`, `iso`, `study_region`, `non_iso_entity`, `raw_poi`, `normalized_poi`, `poi_unmapped`, `utility`.
- `project_resources`: child rows of `(project, type, mw)` — handles hybrids without repeated columns.
- Row IDs are natural keys (`CAISO-0123`; LBNL's own identifier). Never surrogate auto-increment — golden cases store these and must survive re-ingest.
- Views `caiso_projects` and `lbnl_projects` bake in `WHERE source = ...`. All analysis queries a view. The cross-validation check is the single deliberate exception and reads the base table.
- `source` is a closed enum: `caiso_raw | lbnl`. Exact strings everywhere.

**Analysis contracts** (per ADR-0002)

- `source` is required and non-defaulted on all four functions.
- `get_withdrawal_rate` returns per-vintage `withdrawn / (withdrawn + operational)` plus the unresolved count. The pooled all-years rate is not offered.
- `get_historical_timeline` returns median and p25/p75 and always includes the survivor caveat in its return value.
- `get_local_saturation` requires `caiso_raw`; LBNL lacks the grain. Requesting it with `source=lbnl` is an error, not an empty result — an empty result would read as "no congestion here", which is the opposite of the truth.
- Every function surfaces excluded unmapped rows as counts and MW.

**Claim contract** (per ADR-0003)

- Assess emits structured claims only. Each value carries `value`, `unit`, `derivation`, `source_row_ids`, `tool_call_id`, `source`.
- `derivation` closed enum: `direct | sum | count | median | ratio`, one verifier each. Unrecognized → hard fail.
- `median` and the four domain functions' outputs verify by faithful-quotation against the function's return, not recomputation.
- Tolerance table is per-unit, versioned, in the repo.
- Completeness: cited rows compared against the referenced `tool_call_id`'s returned set — set equality for `sum`/`count`/`median`/`ratio`, membership for `direct`.
- Render concatenates text from passing claims only.

**Retrieval**

- Parameterized SQL tools with required `source`. Every call persists `tool_call_id` and its full returned row-ID set to the trace.
- All narrowing happens in SQL; the agent never post-filters a broader result set.

**POI normalization stopping criterion**

Offline fuzzy proposal → human review → checked-in versioned alias table → ETL applies it.
Unmatched rows get `normalized_poi = NULL`, `poi_unmapped = true` — never a guessed match.
Stop at <2% of active-queue MW unmapped or a one-day timebox, whichever comes first; the
resulting coverage percentage is a README number. An ETL assertion compares alias groupings
against LBNL's `poi_name` for overlapping projects and reports disagreements for review.

**Cost controls**

`.env` with a checked-in `.env.example`; secret scan before the repo goes public. Spend cap
set in the Anthropic console before the first agent run. Per-request token and turn caps in
code. PR evals run the affordable tier only; the nightly multi-trial run stays off until the
cap is verified.

## Testing Decisions

**What makes a good test here.** Tests assert on externally observable behavior — the
contents of the database after ingest, the values and caveats a function returns, the
pass/fail decision of the verifier, the claims a run produces. They do not assert on
intermediate call sequences, prompt text, or internal structure. The verifier is the one place
where near-exhaustive coverage is warranted, because it is the component the project's thesis
rests on and it is fully deterministic.

**Seams** (confirmed with the developer)

1. **ETL** — `run_ingest(workbook_paths, db) → IngestReport`, against a real Postgres seeded from the frozen workbooks. Asserts canonical row counts, multi-fuel child rows, `iso`/`study_region` assignment, non-ISO handling, idempotency across re-runs, and unmapped-POI accounting. Cross-validation against LBNL and Public Advocates lives here as assertions with stated tolerances.
2. **Analysis functions** — called directly against a seeded DB. Asserts vintage cohorting produces per-vintage rates with unresolved counts, that the survivor caveat is present *in the return value*, that saturation rejects `source=lbnl`, and that unmapped exclusions are reported.
3. **Tier 1 verifier** — `verify(claims, trace, db) → VerificationResult`, with hand-constructed claims and corrupted mutations. Must-pass: equivalent decimals, in-tolerance rounding, reordered row IDs, correct direct quotation. Must-fail: value beyond tolerance; missing or extra row; **strict subset of the returned set with internally consistent arithmetic**; MW↔GW without conversion; derivation label mismatch; LBNL row cited under `caiso_raw`; both sources' copies of one project mixed; withdrawn row in an active-status claim; empty `source_row_ids`; `tool_call_id` absent from the trace. Reports false-accept and false-reject rates.
4. **Agent end-to-end** — `run_assessment(prompt) → claims + verification result` on 10 golden cases. Claim-correctness and retrieval-correctness graders read **the same run artifact**; the agent is not executed twice.

**Independence rule.** Expected values for golden cases are written as plain Postgres queries,
authored by hand from the prompt's meaning. Graders must not import the analysis functions or
call the runtime verifier — a shared bug would appear on both sides and pass, proving only
that a function equals itself. This duplication is deliberate; DRY is the wrong instinct here,
and the rule is recorded so nobody "fixes" it later.

**Real Postgres, never a mocked DB.** ADR-0001's no-double-counting guarantee is enforced by
the views themselves. Mocking the database would leave that guarantee untested exactly where
it matters. Docker Compose test instance, seeded through the real ETL — no separate snapshot
machinery.

**Thin coverage** at the API boundary: one test that `POST /assess` returns a job ID and `GET`
eventually yields the report, with the graph stubbed.

**Prior art:** none — greenfield repo. These seams establish the conventions.

## Out of Scope

- **Dashboard** (spec Phase 7) — JSON/CLI output only in this slice.
- **Tier 2 judge and its calibration set** (Phase 6) — requires stable qualitative output first.
- **Golden cases 11–30** — this slice builds the harness and the first ten.
- **Monitoring beyond structured logging** — no metrics panel, no Prometheus/Grafana.
- **Load / data-center interconnection** — generation only; stated in the README.
- **Permitting, zoning, environmental constraints, real-time telemetry, paid data.**
- **ISOs beyond CAISO as hand-rolled ETL** — LBNL supplies national breadth.
- **Kafka** — one pipeline, one consumer, no component asking "what happened, in order".
- **Auth provider** — single-user demo; rate limiting and a spend cap do the job.
- **Next.js, Kubernetes.**
- **promptfoo** — pytest over a labeled CSV measures the same number without a config DSL.
- **Vector search / RAG** — data is structured and schema-known.
- **Runtime fuzzy matching** — offline alias proposal only.

## Further Notes

**Guard the retrofit-expensive decisions.** Five things are cheap now and painful later: the
`iso`/`study_region` split, natural-key row IDs, per-source views with required `source`,
`tool_call_id` plus returned-row-set tracing, and structured claims from the start. ETL
messiness, tolerance values, and prompt wording can all be fixed later.

**The shrinking LLM role is the design, not a gap.** SQL narrows, tested functions analyze,
code verifies, the renderer writes. What remains for the model is resolving a natural-language
site description into tool parameters and synthesizing calibrated uncertainty into prose. The
README should state this before a reviewer asks.

**Known benign circularity.** POI normalization cases test that the agent *uses* the normalized
field; they cannot detect a wrong mapping, since agent and expected-answer query share it.
Mapping correctness is covered by normalizer unit tests and one-time manual inspection.
Source-boundary cases largely pass by construction (views plus required `source`) — keep them
as regression guards on that guarantee.

**Judge calibration reporting** (when Phase 6 arrives): per-category counts plus one pooled
false-accept rate with n stated. Per-category rates at n≈5 are noise.

**Terminology.** Earlier drafts called the independently written expected-value queries "oracle
SQL". That reads as Oracle Database and has been dropped — they are plain Postgres queries.
The word "oracle" is reserved for the LBNL / Public Advocates cross-check sense.
