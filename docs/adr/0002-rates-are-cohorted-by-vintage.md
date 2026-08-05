# Rates are cohorted by queue vintage, never pooled across all years

A pooled withdrawal rate over the whole table is biased low, because recent vintages
dominate the row count and have not had time to resolve. LBNL's raw status counts give
~63% withdrawn; the California Public Advocates report gives ~71% cumulative. That spread
is a methodology difference, not a data discrepancy — and comparing the two directly would
have made Phase 1's cross-validation flag a correct ingest as buggy.

We group projects by `q_date` year and report, per vintage, `withdrawn / (withdrawn +
operational)` — the resolved rate — alongside the count still unresolved. Headline figures
come from vintages old enough to be mostly resolved, with the cutoff stated.

## Consequences

`get_historical_timeline` carries the mirror-image bias: it measures only projects that
reached energization, so its median is the median *among successes*, not the expected wait
for a project entering the queue today. The function returns the survivor share alongside
the median so the caveat travels with the number instead of living in a README section
nobody reads.
