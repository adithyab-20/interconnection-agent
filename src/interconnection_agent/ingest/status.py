"""CAISO's status vocabulary -> the canonical status set, as explicit configuration.

Ticket #6 asks that the status mapping live where a reviewer can read it without opening
the ETL, and that any status which is not a clean rename be documented. This module is
that table: each CAISO ``Application Status`` string maps to exactly one canonical token
stored in ``projects.status``.

The mapping is one-to-one. Two entries keep the operator's own word (title-cased to match
the walking skeleton's ``Active``); one is a deliberate rename:

  * ``ACTIVE``    -> ``Active``       (identity)
  * ``WITHDRAWN`` -> ``Withdrawn``    (identity)
  * ``COMPLETED`` -> ``Operational``  (rename) — CAISO's "Completed" sheet is the set of
    energized projects. The canonical vocabulary names that state ``Operational``: it is
    the token ADR-0002's resolved withdrawal rate ``withdrawn / (withdrawn + operational)``
    is written against, so keeping one token in the database keeps that formula literal.
    The human-facing "completed" label is a presentation concern for the (not-yet-built)
    analysis layer to reapply, never a second stored status.

A row whose ``Application Status`` is absent from this table is dropped-with-reason rather
than guessed: a status CAISO has not shown before must be reviewed into this table before
its rows can land.
"""

from __future__ import annotations

# CAISO Application Status (upper-cased) -> canonical projects.status token.
STATUS_MAP: dict[str, str] = {
    "ACTIVE": "Active",
    "COMPLETED": "Operational",
    "WITHDRAWN": "Withdrawn",
}


def canonical_status(raw_status: str) -> str | None:
    """Return the canonical token for a CAISO status, or ``None`` if it is unmapped."""
    return STATUS_MAP.get(raw_status.upper())
