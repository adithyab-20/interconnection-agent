# interconnection-agent

An agent that produces an interconnection-risk assessment for a proposed generation
project, in which **every factual claim is tied to the specific source rows it came from and
checked by code before it reaches the reader.** It grounds each number in public ISO
interconnection-queue data and states plainly which claims cannot be verified that way.

The thesis is *verification, not automation*: the differentiator is that the report's numbers
are provably derived from cited data, not that an LLM wrote a report. See `CONTEXT.md` for the
domain vocabulary, `docs/adr/` for the governing decisions, and
`docs/specs/vertical-slice.md` for the current build scope.

> **Scope:** generation interconnection only — not load / data-center interconnection.

## Status

This is the project **skeleton** (issue #2): a Postgres brought up with Docker Compose, a
pytest suite that runs against it, and green CI on every push and pull request. No
domain-specific behavior exists yet — this is the harness every later ticket lands in.

## Requirements

- [Docker](https://www.docker.com/) (for the Postgres service)
- [uv](https://docs.astral.sh/uv/) (Python dependency management; installs the right Python too)

## Bring the stack up and run the tests

```bash
# 1. Start Postgres (host port 5433 -> container 5432; see below).
docker compose up -d

# 2. Install dependencies into a local virtualenv.
uv sync

# 3. Run the test suite against that database.
uv run pytest
```

When you're done:

```bash
docker compose down          # stop Postgres, keep the data volume
docker compose down -v       # ...or also remove the data volume
```

### Database configuration

The application reads the Postgres DSN from the `DATABASE_URL` environment variable and falls
back to the local Compose database when it is unset, so the steps above need no configuration.
Copy `.env.example` to `.env` to override it.

The Compose service publishes Postgres on **host port 5433** (mapped to the container's 5432)
so it does not collide with a Postgres you may already have installed locally on 5432. CI uses
the same 5433 mapping, so the default DSN resolves identically there.

## Developer checks

The same checks CI runs on every push and pull request (see `.github/workflows/ci.yml`):

```bash
uv run ruff check           # lint
uv run ruff format --check  # formatting
uv run mypy                 # type check (strict)
uv run pytest               # tests (needs Postgres up)
```

## Layout

```
src/interconnection_agent/        # application package
src/interconnection_agent/tests/  # unit tests for this component (pure, no DB)
tests/integration/                # integration tests (real Postgres via Compose)
tests/e2e/                        # end-to-end tests (full-stack; none yet)
data/                        # frozen source workbooks + third-party attribution
docker-compose.yml           # local Postgres service
.github/workflows/ci.yml     # push + pull_request CI
docs/                        # ADRs, specs, agent docs
CONTEXT.md                   # domain vocabulary
```

Test layout convention (unit next to the code, integration/e2e under `tests/`) is
documented in [`tests/README.md`](tests/README.md).

## POI normalization & coverage

CAISO's station field is free text: the same substation appears as "Whirlwind Substation
230kV", "WHIRLWIND Substation 230 kV", and "Whirlwind Sub 230kV bus". Projects are grouped
to a point of interconnection in two **deterministic** steps, so no probabilistic join ever
runs beneath a verified claim:

1. **Normalizer** (`interconnection_agent.poi.normalize`) — collapses only *mechanical*
   variation: unicode compatibility forms (NFKC), case, whitespace, the `230kV` / `230 kV`
   spelling, and hyphen spacing. It deliberately keeps descriptors like "Substation",
   "Line", and "Bus", and never merges voltage levels — a 230 kV bus and a 500 kV bus at
   one site are different POIs.
2. **Reviewed alias table** (`src/interconnection_agent/poi/aliases.csv`, versioned) — maps
   each normalized key to a canonical POI name by **exact match**. This is where genuine
   synonyms, typos ("Vota-South" → "Volta-South"), and suffix variants are grouped. A string
   with no reviewed entry resolves to `normalized_poi = NULL`, `poi_unmapped = true` — it is
   counted, never guessed.

Fuzzy matching is confined to the offline proposal tool
(`scripts/propose_poi_aliases.py`, `rapidfuzz`), which suggests candidate groups for human
review and is **not importable by runtime code** (guarded by
`test_poi_offline_only.py`).

**Measured coverage (active sheet, report dated 07/24/2026):** of 270 active projects
(76,287 MW), **2 projects / 1,100 MW — 1.44% of active-queue MW — are unmapped**, both
because their POI is merely *conceptual* or *proposed* (no established substation, so no
energized history to ground a saturation figure). That clears the project's stopping
criterion of <2% of active-queue MW unmapped. Reproduce it with:

```bash
# Needs Postgres up (see above); prints the coverage line as it ingests.
PYTHONPATH=src uv run python -m interconnection_agent.cli ingest data/publicqueuereport.xlsx
```

The reviewed groupings are cross-checked against LBNL's independent `poi_name` for the
overlapping CAISO projects; disagreements are reported for review by
`tests/integration/test_poi_lbnl_crosscheck.py`.

## Data & attribution

The `data/` directory holds the frozen public datasets this project ingests — CAISO's
Public Queue Report and LBNL's "Queued Up" file. They are used for educational and research
purposes and fall outside this repository's software license; each source's credit and terms
are recorded in [`data/README.md`](data/README.md). Neither CAISO, LBNL, nor GridTracker
endorses this project.
