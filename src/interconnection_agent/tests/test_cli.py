"""Unit tests for the CLI's pure rendering — no database, per the tests/ layout.

The county selection itself is an integration test (it reads a real view); rendering the
selected rows into text is pure, so it lives here alongside the other fast unit tests.
"""

from __future__ import annotations

import datetime

from interconnection_agent.cli import ActiveProject, format_projects


def _project(**overrides: object) -> ActiveProject:
    fields: dict[str, object] = {
        "native_id": "CAISO-0022",
        "county": "SOLANO",
        "study_region": "Northern",
        "raw_poi": "Birds Landing 230 kV",
        "utility": "PGAE",
        "q_date": datetime.date(2003, 11, 18),
        "proposed_online_date": datetime.date(2005, 6, 30),
    }
    fields.update(overrides)
    return ActiveProject(**fields)  # type: ignore[arg-type]


def test_format_renders_one_line_per_project() -> None:
    rendered = format_projects([_project()], county="SOLANO")
    lines = rendered.splitlines()
    assert len(lines) == 2  # one header line, one project line
    assert "CAISO-0022" in rendered
    assert "Birds Landing 230 kV" in rendered
    assert "SOLANO" in rendered


def test_format_reports_an_empty_county_rather_than_a_blank() -> None:
    # An analyst must get an explicit "no matching evidence", never a silent blank.
    rendered = format_projects([], county="NOWHERE")
    assert "No active" in rendered
    assert "NOWHERE" in rendered
