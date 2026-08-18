# Interconnection Agent Resources

## Knowledge

- [Build specification](docs/specs/build-spec.md)
  Authoritative product architecture, data sources, verification tiers, evaluation strategy, and build order. Use before planning implementation.
- [Vertical-slice specification](docs/specs/vertical-slice.md)
  Defines the first demoable milestone and its test seams. Use to decide whether a ticket belongs in the current scope.
- [Domain vocabulary](CONTEXT.md)
  Canonical meanings for POI, saturation, vintage, resolved withdrawal rate, and provenance. Use when naming schemas, functions, and outputs.
- [ADR 0001](docs/adr/0001-two-column-location-hierarchy-and-per-source-views.md)
  Explains the location hierarchy and why analysis must use source-specific views.
- [ADR 0002](docs/adr/0002-rates-are-cohorted-by-vintage.md)
  Explains vintage-cohorted withdrawal rates and the survivor bias in time-to-energization.
- [ADR 0003](docs/adr/0003-claims-are-generated-structured-not-parsed-from-prose.md)
  Defines structured claims, deterministic Tier 1 verification, trace completeness, and the verification boundary.

## Wisdom (Communities)

- Project pull-request review and issue discussion
  Use for challenging data mappings, expected-answer SQL, and domain assumptions before they become permanent interfaces.
