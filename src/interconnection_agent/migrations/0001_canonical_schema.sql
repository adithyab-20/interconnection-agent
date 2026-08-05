-- The canonical schema (ADR-0001). One projects table plus a project_resources
-- child table, addressed by natural keys, with a per-source view for each dataset.

-- source is a closed enum: caiso_raw (the operator's own weekly workbook) or lbnl
-- (Berkeley Lab's national file). CAISO projects appear in both. Exact strings,
-- everywhere (claim schema, mutation suite, docs).
CREATE TYPE source AS ENUM ('caiso_raw', 'lbnl');

-- Row identity is the natural key (source, native_id) — CAISO's queue position,
-- LBNL's own identifier. Never a surrogate auto-increment: golden eval cases store
-- these ids and must survive an ETL re-run (which upserts on this key).
CREATE TABLE projects (
    source               source NOT NULL,
    native_id            text   NOT NULL,
    status               text,

    -- Lifecycle dates. q_date is the queue-entry date (vintage axis); the online
    -- dates are proposed (a forecast) vs actual (energization); ia_date is the
    -- interconnection-agreement date.
    q_date               date,
    proposed_online_date date,
    actual_online_date   date,
    withdrawn_date       date,
    ia_date              date,

    -- Geography. iso and study_region are SEPARATE levels of a hierarchy and must
    -- never be collapsed into one column. study_region is NULL for LBNL rows, which
    -- have no sub-ISO grain. non_iso_entity holds LBNL's West/Southeast catch-alls,
    -- which are balancing areas, not operators, and get iso = NULL.
    county               text,
    state                text,
    iso                  text,
    study_region         text,
    non_iso_entity       text,

    -- Point of interconnection, kept twice: the operator's verbatim string and the
    -- reviewed normalized form. Rows with no reviewed alias are flagged rather than
    -- guessed — normalized_poi NULL, poi_unmapped true.
    raw_poi              text,
    normalized_poi       text,
    poi_unmapped         boolean NOT NULL DEFAULT false,

    utility              text,

    PRIMARY KEY (source, native_id)
);

-- Up to three (type, MW) pairs per project (hybrids: solar + storage). Child rows
-- rather than repeated columns. Keyed naturally too, on the parent key plus type.
CREATE TABLE project_resources (
    source    source NOT NULL,
    native_id text   NOT NULL,
    type      text   NOT NULL,
    mw        double precision,

    PRIMARY KEY (source, native_id, type),
    FOREIGN KEY (source, native_id) REFERENCES projects (source, native_id) ON DELETE CASCADE
);

-- Per-source views. All analysis reads a view, never the base table, so a query
-- that forgets `WHERE source = ...` cannot double-count a project present in both
-- datasets. A check constraint cannot catch a forgotten WHERE; a baked-in filter
-- can. The single deliberate base-table reader is Phase 1 cross-validation.
CREATE VIEW caiso_projects AS SELECT * FROM projects WHERE source = 'caiso_raw';
CREATE VIEW lbnl_projects  AS SELECT * FROM projects WHERE source = 'lbnl';
