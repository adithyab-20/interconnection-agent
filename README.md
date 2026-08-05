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
docker-compose.yml           # local Postgres service
.github/workflows/ci.yml     # push + pull_request CI
docs/                        # ADRs, specs, agent docs
CONTEXT.md                   # domain vocabulary
```

Test layout convention (unit next to the code, integration/e2e under `tests/`) is
documented in [`tests/README.md`](tests/README.md).
