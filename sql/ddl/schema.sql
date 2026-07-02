-- Experiment Trust Engine — Warehouse DDL
-- Compatible with PostgreSQL / SQLite (used here) / Synapse with minor type tweaks.

CREATE TABLE IF NOT EXISTS dim_experiment (
    experiment_id           TEXT PRIMARY KEY,
    experiment_name         TEXT NOT NULL,
    owner_team              TEXT NOT NULL,
    hypothesis              TEXT,
    start_date              DATE NOT NULL,
    end_date                DATE NOT NULL,
    status                  TEXT NOT NULL,
    planned_allocation      TEXT
);

CREATE TABLE IF NOT EXISTS dim_user (
    user_id                 TEXT PRIMARY KEY,
    signup_date             DATE NOT NULL,
    country                 TEXT NOT NULL,
    platform                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_assignment (
    experiment_id           TEXT NOT NULL REFERENCES dim_experiment(experiment_id),
    user_id                 TEXT NOT NULL REFERENCES dim_user(user_id),
    variant                 TEXT NOT NULL CHECK (variant IN ('control', 'treatment')),
    assignment_timestamp    TIMESTAMP NOT NULL,
    PRIMARY KEY (experiment_id, user_id)
);

CREATE TABLE IF NOT EXISTS fact_event (
    event_id                BIGINT PRIMARY KEY,
    experiment_id           TEXT NOT NULL REFERENCES dim_experiment(experiment_id),
    user_id                 TEXT NOT NULL REFERENCES dim_user(user_id),
    variant                 TEXT NOT NULL,
    event_type              TEXT NOT NULL CHECK (event_type IN
                             ('exposure', 'engagement', 'conversion', 'guardrail_complaint')),
    event_timestamp         TIMESTAMP NOT NULL,
    event_value             NUMERIC
);

-- The governance table: every version of every metric definition, scoped
-- per experiment, with the exact effective window it applied.
CREATE TABLE IF NOT EXISTS dim_metric_definition (
    metric_name             TEXT NOT NULL,
    experiment_id           TEXT NOT NULL REFERENCES dim_experiment(experiment_id),
    definition_version      TEXT NOT NULL,
    definition_logic        TEXT NOT NULL,
    effective_start         DATE NOT NULL,
    effective_end           DATE NOT NULL,
    PRIMARY KEY (metric_name, experiment_id, definition_version)
);

CREATE INDEX IF NOT EXISTS idx_event_experiment ON fact_event(experiment_id);
CREATE INDEX IF NOT EXISTS idx_event_user ON fact_event(user_id);
CREATE INDEX IF NOT EXISTS idx_assignment_experiment ON fact_assignment(experiment_id);
