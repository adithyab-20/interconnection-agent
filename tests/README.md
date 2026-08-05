# Tests

Test layout convention for this repo:

- **Unit tests** live in each component's own `tests/` directory
  (`src/<component>/tests/test_<module>.py`, e.g.
  `src/interconnection_agent/tests/test_db.py`). They must be pure and fast —
  no database, no network.
- **Integration tests** live under `tests/integration/`, named `test_*.py`. They
  exercise real infrastructure — most importantly the Docker Compose Postgres
  (`docker compose up` first). No mocked database (see the spec's
  "Real Postgres, never a mocked DB").
- **End-to-end tests** live under `tests/e2e/`, named `test_*.py`. Full-stack runs
  (e.g. API request → worker → assessment) once those surfaces exist.

Run the whole suite with `uv run pytest`.
