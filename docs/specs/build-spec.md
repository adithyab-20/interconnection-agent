# Interconnection Due-Diligence Agent — Build Spec (for Claude Code)

Self-contained spec. Assume no prior context. Follow decisions here exactly; they were reached deliberately — do not "improve" the architecture without asking.

## 1. What this is

An LLM agent that assesses grid-interconnection risk for a proposed renewable energy site using public interconnection-queue data, where **every factual claim is traced to specific source rows and verified by code**. The thesis is *verification, not automation*: the differentiator is that the report's numbers are provably derived from cited data, not that an LLM wrote a report.

**Stack:** Python, FastAPI, Postgres, LangGraph, Anthropic Messages API, Celery + Redis, React/TypeScript dashboard, pytest, Docker Compose, GitHub Actions CI.

**Not RAG.** Data is structured and schema-known. Retrieval is tool-calling over parameterized SQL, never vector search. Fuzzy matching (`pg_trgm`/`rapidfuzz`) is an **offline alias-table-construction tool only** — it proposes candidate station-name groupings for human review. It is NEVER in the runtime query path: runtime joins are deterministic exact-match on `normalized_poi` against the checked-in alias table. (A probabilistic grouping at query time would make "which rows belong to this POI" nondeterministic, breaking Tier 1's set-equality checks and the mutation suite's hard-FAIL semantics.)

## 2. Data sources (frozen snapshots, committed to repo or pinned)

1. **CAISO Public Queue Report** (`publicqueuereport.xlsx`) — 3 tabs: active (~271), completed (~248), withdrawn (~1,760). Headers on row 4. Multi-fuel columns (Type/Fuel/MW 1–3). Free-text station/POI field requiring normalization. **Ingested by hand-rolled ETL** — this is the engineering showcase. Completed tab yields real time-to-energization (median ≈ 6.2 yrs).
2. **LBNL "Queued Up"** (`LBNL_Ix_Queue_Data_File_thru2025.xlsx`) — pre-normalized, all 9 ISO regions, 38,201 rows, has codebook. Loaded as the **national breadth layer** and used as an **independent cross-check** on CAISO-derived aggregates.
3. **Public Advocates report (PDF)** — independent CAISO stats (~71% withdrawn, ~20% completed) used only for cross-validation assertions in ETL tests, not loaded as a queryable source.

Cross-validation: after ETL, automated checks compare CAISO-raw aggregates against LBNL's CAISO subset and the Public Advocates figures within stated tolerances.

## 3. Schema decisions (non-negotiable)

- Split location into **`iso`** (grid operator) and **`study_region`** (sub-zone). Never a single `region` column.
- LBNL's non-ISO regions (West, Southeast): `iso = NULL` plus a `non_iso_entity` column. Never `iso = 'West'`.
- **Per-source Postgres views**: `caiso_projects`, `lbnl_projects`. All analysis goes through a view, so double-counting a project that appears in both sources is structurally impossible.
- Every analysis function takes a **required, non-defaulted `source` argument**.
- **Stable natural-key row IDs**: CAISO rows keyed by CAISO queue position (e.g. `CAISO-0123`); LBNL rows keyed by LBNL's own project identifier. Never surrogate auto-increment IDs — golden eval sets store these IDs and must survive ETL re-runs.
- Normalized POI stored in `normalized_poi`; the raw string is preserved in `raw_poi`. (These exact column names — pin them everywhere.)
- **Normalization workflow and stopping criterion:** rapidfuzz/pg_trgm propose candidate alias groups offline → human reviews them into a **checked-in alias table** (versioned, unit-tested) → ETL applies it. Rows with no reviewed alias get `normalized_poi = NULL` and a `poi_unmapped = true` flag — never a guessed match. **Stop when unmapped rows account for <2% of active-queue MW, or after the 1-day timebox, whichever first**; report the coverage number in the README. Analysis functions must surface unmapped-row counts in their outputs (an honest "N rows excluded, X MW") rather than silently dropping them.
- **Mapping cross-check:** LBNL's `poi_name` covers the same CAISO projects; add an ETL assertion comparing the alias table's groupings against LBNL's normalization for overlapping projects and reporting disagreements for review.

## 4. Agent architecture (LangGraph)

Nodes (roughly): Plan → Retrieve (SQL tools) → Analyze (trusted functions) → Assess → Verify (Tier 1) → Render.

- **Retrieve** calls parameterized SQL tools (POI lookup, county/study-region filter, ISO+status+technology filter, date/capacity filters). Each tool takes required `source`. **All narrowing happens in SQL**: if the agent wants "solar projects at this POI," it calls the tool with the solar filter — it never mentally filters a broader result set. Every tool result carries a `tool_call_id` and the full returned row-ID set, persisted in the trace.
- **Analyze — the domain layer, and the four named trusted functions are the product:**
  - `get_poi_context(source, poi)` — active/completed/withdrawn breakdown at a POI.
  - `get_historical_timeline(source, filters)` — time-to-energization distribution from completed projects, **always emitted with the survivor-statistic caveat** (only projects that finished are observable; the number is biased optimistic).
  - `get_withdrawal_rate(source, filters)` — **vintage-cohorted** (rate computed per queue-entry cohort, since recent cohorts haven't had time to withdraw; a naive pooled rate is biased low).
  - `get_local_saturation(source, poi)` — pending MW at the POI relative to historically completed MW there (this signal requires CAISO-raw; it's why the hand-rolled ETL is load-bearing).
  - Plus generic distribution statistics (median, percentiles). All are **trusted, separately unit-tested functions**; the LLM calls them and faithfully quotes their outputs — it never re-derives any of these from raw rows. These four functions carry the domain judgment; without them this is a generic SQL agent with citations.
- **Assess** emits **structured claims**, not prose. Each value references the `tool_call_id` it derives from:

```json
{
  "claims": [
    {
      "text": "Active projects at MOSS LANDING total 2,450 MW.",
      "values": [
        {
          "value": 2450,
          "unit": "MW",
          "derivation": "sum",
          "source_row_ids": ["CAISO-0012", "CAISO-0018", "CAISO-0023"],
          "tool_call_id": "tc_004",
          "source": "caiso_raw"
        }
      ]
    }
  ]
}
```

- `derivation` is a **closed enum**: `direct | sum | count | median | ratio`. One verifier per derivation type. For `median` and the four domain functions' outputs, verification = trusted-function output + a faithful-quotation check (value in claim equals function return), not re-derivation.
- `source` is a **closed enum**: `caiso_raw | lbnl`. Use these exact strings everywhere — claim schema, mutation suite, views mapping, docs.
- **Render** produces prose only from verified claims. Prose is downstream of verification, never re-parsed.

## 5. Verification tiers (runtime, per assessment)

- **Tier 1 (code, no LLM):** for each value, join `source_row_ids` against the DB, apply the derivation-specific verifier, compare within a **per-unit tolerance table** (explicit, versioned). Because claims are structured, Tier 1 is a join — never prose re-parsing.
- **Tier 1 completeness check (runtime):** for each value, compare `source_row_ids` against the row set the referenced `tool_call_id` actually returned (from the persisted trace). Set-derived derivations (`sum`/`count`/`median`/`ratio`) require **set equality**; `direct` requires membership. This makes free-hand row selection structurally impossible — an agent that cites 2 of 3 returned rows and sums them correctly still FAILS. Cost: one set comparison per value.
- **Tier 2 (LLM-as-judge):** qualitative claims only (uncertainty handling, causal overstatement, evidence alignment, recommendation coherence — separate pass/fail dimensions, judge may return UNKNOWN). Judge is **calibrated, not trained**: agreement with ~30 human labels is measured and reported as a number. A smaller/cheaper judge model is acceptable if it passes calibration. Judge few-shot examples must be **disjoint** from the calibration set.
- **Tier 3 (human):** reasoning quality is not fully auto-verifiable. Stated as an honest limitation.

**Tier 1 boundary (state in README):** Tier 1 proves arithmetic + provenance + that the claim faithfully covers the full result set of the query it derives from. It does NOT prove that query was the *right* query (wrong POI argument, missing filter, wrong tool). That gap is closed offline by the retrieval eval (Eval 2) — the runtime completeness check and Eval 2 are complementary, not substitutes.

## 6. Offline eval suite (distinct from runtime verification)

Runtime checks ask "can I trust this specific report?" Evals ask "across known cases, how reliable is the agent, and did a change regress it?" Three eval artifacts, kept in separate directories:

```
evals/
├── golden/            # ~30 cases → Evals 1 & 2 (tests the AGENT)
│   ├── cases/*.yaml
│   └── sql/*.sql      # expected-answer queries, auditable
├── judge_calibration/ # ~30 human-labeled reasoning samples → Eval 3 (tests the JUDGE)
│   └── labels.json
├── verifier_mutations/ # generated valid/invalid claim mutations (tests TIER 1)
├── graders/           # arithmetic.py, provenance.py, retrieval.py, judge.py
└── run_evals.py       # pytest-based harness
```

### Eval 1 — Factual claim correctness (code grader)
Run agent on golden case → extract structured claims → independently recompute expected values from the case's **expected-answer queries** / precomputed golden answers → compare value, unit, derivation, row IDs. Metrics: claim verification rate, unsupported-claim rate, arithmetic error rate, missing-citation rate, wrong-unit rate, whole-report pass rate. The grader must NOT call the runtime Tier 1 verifier — independent recomputation only.

**Independence rule (the reason these queries exist).** Expected-answer queries are plain Postgres, written by hand from the prompt's meaning — never by calling the agent's own analysis or retrieval functions. If the expected value came from the same code being tested, a bug would appear on both sides and the test would pass while both were wrong, proving only that a function equals itself. This duplication is deliberate; DRY is the wrong instinct here. Do not "fix" it later.

### Eval 2 — Retrieval correctness (code grader)
Compare agent's cited row-ID set to the golden expected set: exact-set match, precision, recall. Only for cases where the correct set is deterministically definable (POI, county, status, technology, date, capacity filters). NOT applicable to fuzzy "comparable projects" queries — state this limitation.

### Eval 3 — Judge calibration
Run the Tier 2 judge on the ~30 human-labeled samples (labels span: well-supported, overstated causality, correct uncertainty, overconfident, contradictory, insufficient-evidence). Report overall agreement and a **pooled false-accept rate** with n stated explicitly. False accepts (bad reasoning → PASS) are the dangerous failure; never report accuracy alone. This dataset is separate from the golden set — do not conflate them.

**Report per-category counts, not per-category rates.** Six label categories over ~30 samples is ~5 each, where one label flip moves a "rate" by 20 points. A table of raw counts per category plus one pooled rate is the honest presentation; per-category percentages at this n invite a reviewer to find the hole for you.

### Verifier mutation suite (unit/property tests for Tier 1)
Generate valid claims plus corrupted mutations; measure Tier 1's false-accept and false-reject rates.
- Must PASS: equivalent decimals, rounding within tolerance, reordered row IDs, correct direct quotation.
- Must FAIL: value off beyond tolerance; missing/extra source row; **cited set is a strict subset of the tool-returned set with arithmetic internally consistent** (the completeness check's target case); MW↔GW without conversion; derivation label mismatch (claims `sum`, is `ratio`); LBNL row cited under `source="caiso_raw"`; CAISO+LBNL copies of same project mixed; withdrawn row in an active-status claim; value with empty `source_row_ids`; `tool_call_id` referencing a call absent from the trace.
Frame in README as unit/property testing of a deterministic component.

### Golden set construction (the method — do this, don't hand-inspect 38k rows)
1. Freeze dataset snapshots + ETL version + normalization mapping version; record in each case's metadata.
2. Explore the DB with SQL to find good real entities (e.g. POIs with 3–15 projects; mixes of active/withdrawn; multi-technology; spelling variants; single-project POIs; guaranteed-empty filters).
3. Write the user prompt. Keep a deliberate mix: some fully explicit prompts ("projects whose normalized POI exactly matches X, status Active") and some natural-but-deterministic prompts ("How saturated is the queue at Moss Landing?") that force the agent to interpret correctly. Revise any ambiguous prompt until two knowledgeable readers would agree on the row set.
4. Write the **expected-answer query** by hand (never the agent's retrieval functions — shared bug = false PASS). Save row IDs and derived values (count, sum, etc.) into the YAML case; commit the SQL file.
5. **Manually validate each expected-answer query once**: does the SQL match the prompt's meaning, are the rows actually relevant, any null/naming traps, is another reasonable interpretation possible?
6. Case category targets (~30 total): 5 exact POI, 4 POI normalization, 3 county/study-region, 3 technology+status, 2 date/capacity, 3 combined filters, 2 empty-result, 2 source-boundary, **6 domain-analysis** (vintage-cohorted withdrawal rate; survivor-caveated timeline; POI saturation ratio; a CAISO-vs-LBNL cross-check case; one where the caveat itself is the expected output). Domain cases grade both the numeric outputs (against expected-answer queries that replicate the cohort/saturation logic independently) and the presence of the required caveats in the qualitative labels. Without these six, the evals certify a generic SQL agent, not the domain product. Include negative cases deliberately — empty-result cases test that the agent says "no matching evidence" instead of broadening or inventing.
7. Build in three passes: 10 straightforward → 10 combined-filter → 10 edge cases (aliases, similar station names, nulls, hybrid solar+storage / multi-fuel columns, CAISO/LBNL overlap, non-ISO LBNL entities, withdrawn-vs-active confusion).

Known benign circularity to note in README: normalization cases test that the agent *uses* the normalized field; they can't detect a wrong mapping (agent and expected-answer query would share it). Mapping correctness is covered by normalizer unit tests + one-time manual inspection. Source-boundary cases mostly pass by construction (views + required `source`); keep them as regression guards on that guarantee.

### CI cadence
- Every PR: 30 golden cases × 1 trial, deterministic graders only; verifier mutation suite; ETL cross-validation checks.
- Nightly / pre-release: 30 × 3 trials (report pass@1 and pass^3 — consistency matters for a verification product, but don't over-interpret gaps at n=30), plus judge run. **Off by default** — this is ~90 agent runs plus a judge pass per night, the single largest recurring cost in the project. Enable it deliberately once the spend cap in §8 is set and verified, not as part of initial CI setup.
- Eval environment: Docker Compose test Postgres seeded from the frozen files via the ETL — no separate snapshot machinery.
- Failed production-style traces get converted into new eval cases (one README sentence; don't build flywheel tooling now).

## 7. Build order (priority-sequenced — do not gold-plate later phases before earlier ones ship)

1. **Phase 1 — ETL:** hand-rolled CAISO ingest (3 tabs, header row 4, multi-fuel columns), POI alias table (offline fuzzy proposal → human review → checked in; UNMAPPED bucket; <2%-of-active-MW or 1-day stopping criterion; LBNL `poi_name` cross-check), LBNL load per codebook, natural-key IDs, cross-validation assertions vs LBNL + Public Advocates.
2. **Phase 2 — Schema & access layer:** tables, `iso`/`study_region` split, non-ISO handling, per-source views, SQL tool functions with required `source` arg and `tool_call_id`+row-set trace persistence.
3. **Phase 3 — Agent skeleton + domain functions:** LangGraph graph, SQL tools, then the **four domain analysis functions** (`get_poi_context`, `get_historical_timeline`, `get_withdrawal_rate`, `get_local_saturation`) unit-tested first — these working with provenance are the core deliverable — plus generic stats, Anthropic API calls, Celery task wrapper, minimal FastAPI endpoints.
4. **Phase 4 — Structured claims + Tier 1:** claim schema (incl. `tool_call_id`, `source` enum), derivation enum, per-derivation verifiers, completeness check against trace, tolerance table, prose rendering from verified claims.
5. **Phase 5 — Evals 1 & 2 + mutation suite:** harness, graders, first 10 golden cases; wire into CI; grow to 30. (Highest ROI — this is the project's credibility.)
6. **Phase 6 — Tier 2 judge + Eval 3:** only once the agent produces stable qualitative output. Rubric with separate dimensions, UNKNOWN allowed, then hand-label ~30 samples and measure agreement.
7. **Phase 7 — Dashboard + monitoring:** React/TS report view showing each claim with its verification status, cited rows (click-through to source data), and the measured judge-agreement number. Eval results summary page. **Monitoring (minimal but real, earns the resume keyword):** structured JSON logging throughout; per-assessment metrics persisted (latency, token cost, Tier 1 pass rate, Tier 2 outcomes, claims per report, unmapped-row exclusions); LangGraph traces stored and viewable; a simple metrics panel in the dashboard. No Prometheus/Grafana unless time permits.

## 8. Secrets and cost

This is a single-developer project on a personal API account. Both of these are cheap to set up and expensive to discover late.

- **Secrets:** API key in `.env`, never committed; `.env.example` checked in with empty values. Run a secret scan before the repo goes public.
- **Spend cap:** set a hard monthly cap in the Anthropic console *before* the first agent run. This is the backstop that makes every other control optional rather than load-bearing.
- **Per-request caps:** max tokens and max graph turns per assessment, enforced in code. An agent that loops is a bill, not just a bug.
- **CI spend:** PR-run evals (30 × 1, deterministic graders) are the affordable tier. The nightly 30 × 3 plus judge run is not on by default — see §6 CI cadence.
- **If the demo is publicly reachable:** rate-limit by IP via Redis, and add a kill switch that serves canned responses. Auth is deliberately out of scope (single-user demo; an auth provider here would demonstrate configuration, not engineering).

## 9. README must state honestly

- Tier 1 proves arithmetic + provenance + full coverage of each query's returned rows (runtime completeness check); it does not prove the query itself was right — Eval 2 covers the deterministic part of that gap offline. Complementary, not substitutes.
- Time-to-energization is a survivor statistic (biased optimistic); withdrawal rates are vintage-cohorted because pooled rates are biased low. These caveats are emitted by the analysis functions themselves, not left to the LLM's discretion.
- POI normalization coverage: X% of active-queue MW mapped; unmapped rows are flagged and excluded transparently, never guessed.
- Judge is calibrated against N human labels with X% agreement and Y% false-accept rate — measured, not trained.
- 30 golden cases guide development and catch regressions; they do not prove universal reliability.
- Retrieval eval covers only deterministically definable queries; "comparable projects" retrieval is not auto-evaluated.
- Reasoning quality ultimately requires human review (Tier 3).

### Why an agent and not a script — state this position explicitly

The architecture here deliberately shrinks the LLM's role: SQL does the narrowing, unit-tested functions do the analysis, code does the verification, and the renderer writes the prose from verified claims. A reviewer will notice and ask what's left. Answer it first, in these terms:

> The model resolves a natural-language site description into tool parameters, and synthesizes calibrated uncertainty across several function outputs into readable prose. It does **not** select rows, compute statistics, or decide what counts as verified — those are code, because they're the parts that must be right. LangGraph earns its place through the verification gate that runs on every assessment and through nodes that are independently testable, not through dynamic routing; with this few tools, routing would be trivial and claiming otherwise would be overselling it.

The shrinking LLM surface is a *result* of the verification thesis, not a weakness in it. Framed that way it's the strongest thing in the design; left unaddressed, it's the first question that lands badly.
