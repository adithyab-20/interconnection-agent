# Two-column location hierarchy, and per-source views instead of a shared table

The two datasets use the word "region" for different levels of a hierarchy: LBNL means the
market operator (CAISO, PJM), CAISO's own workbook means a sub-ISO study zone (Northern,
Fresno). Storing both in one `region` column would make `GROUP BY region` mix levels and
would quietly corrupt the project's headline local-vs-national comparison. We store `iso`
and `study_region` as separate columns, with `study_region` NULL for LBNL rows, which have
no sub-ISO grain.

LBNL's `region` field is itself mixed — it holds the seven ISO names plus "West" and
"Southeast", which are non-ISO catch-alls rather than operators. Those rows get `iso = NULL`
and the balancing-area name from LBNL's `entity` field in a separate `non_iso_entity`
column, so the same level-mixing bug is not rebuilt one tier down.

## Consequences

CAISO projects appear in **both** sources, so any aggregate that forgets `WHERE source = ...`
silently double-counts them. A check constraint cannot catch a forgotten `WHERE`, so we
create two views — `caiso_projects` and `lbnl_projects` — each baking in its own filter.
All analysis functions query the views and never the base table, making a cross-source
aggregate physically impossible. The single deliberate exception is the Phase 1
cross-validation step, which reads the base table precisely because it wants both sources
at once.

Analysis functions take `source` as a required, non-defaulted parameter. A default is how a
silent double-count ships six months later.
