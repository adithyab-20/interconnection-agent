# Interconnection Due-Diligence

Assesses the interconnection risk of a proposed generation project by grounding every
factual claim in a specific row of public ISO queue data, and by stating plainly which
claims cannot be verified that way.

## Language

### Grid and geography

**ISO**:
The market operator that runs an interconnection queue — CAISO, PJM, MISO, ERCOT, SPP,
NYISO, ISO-NE. The coarsest scope a query can name.
_Avoid_: RTO, market, region (see Study Region)

**Study Region**:
A sub-ISO zone the operator uses to organise its studies, e.g. CAISO's "Northern",
"Fresno", "Eastern". Nested strictly inside one ISO. Only `caiso_raw` has this grain.
_Avoid_: region, zone, area

**Non-ISO Entity**:
A balancing authority in a territory with no organised market (LBNL's "West" and
"Southeast" catch-alls). It is not an ISO and must never be stored as one.
_Avoid_: non-ISO region

**POI (Point of Interconnection)**:
The substation or transmission line where a project physically connects to the grid.
Recorded twice: `poi_raw` (the operator's free text, verbatim) and `poi_normalized`
(after grouping rules).
_Avoid_: interconnection point, station, tie-in

### Project lifecycle

**Project**:
One interconnection request. Identified canonically by (`source`, `native_id`).

**Energization**:
The date a project actually began commercial operation. Distinct from the *proposed*
online date, which is a forecast and frequently wrong.
_Avoid_: completion, COD, going live

**Time-to-Energization**:
`actual_online_date − q_date`, computable only for projects that reached operation, and
therefore a **survivor statistic** — biased optimistic, since projects still crawling
through year nine are invisible to it. The caveat is emitted with the number, not left to
the model's discretion.

**Saturation**:
Pending MW at a POI relative to the MW historically energized there. Requires `caiso_raw`;
LBNL has no equivalent grain.

**Withdrawal**:
A request leaving the queue without energizing. The dominant outcome — most queued
projects withdraw.

**Vintage**:
The calendar year a project entered the queue (`q_date` year). The cohorting axis for
every rate, because older vintages have had more time to resolve.

**Resolved**:
A project that has reached a terminal outcome — energized or withdrawn. Projects still
active are *unresolved* and belong in neither numerator nor denominator of a rate.

**Resolved Withdrawal Rate**:
`withdrawn / (withdrawn + operational)` within a vintage, reported alongside the count
still unresolved. The pooled all-years version is biased low and is not used.
_Avoid_: withdrawal rate (unqualified)

### Data provenance

**Source**:
Which dataset a row came from: `caiso_raw` (the operator's own weekly workbook) or
`lbnl` (Berkeley Lab's pre-normalized national file). CAISO projects appear in **both**,
so the two are never aggregated together.

**Provenance**:
The specific source rows an analysis result was derived from — source, `native_id`, and
the field values used. Every analysis function returns this alongside its numbers.

**Claim**:
One factual assertion in a generated assessment, carrying its own verification status.
_Avoid_: statement, fact, finding
