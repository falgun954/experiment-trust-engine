# Metric Lineage: `active_user`

This document exists because "active user" is the single most commonly
redefined metric in any analytics org, and disagreements about it silently
undermine experiment results. Every version below is traceable to the
exact SQL/DAX that computes it and the exact date range it applied to.

## Version history

| Version | Logic | Source of truth |
|---|---|---|
| v1 | Any user with ≥ 1 tracked event in the exposure window | `sql/views/analysis_views.sql :: v_user_event_counts`, filter `n_events >= 1` |
| v2 | User with ≥ 2 tracked events **and** ≥ 1 core action event (engagement or conversion) | `sql/views/analysis_views.sql :: v_user_event_counts`, filter `n_events >= 2 AND n_core_events >= 1` |

Per-experiment effective windows are stored in `dim_metric_definition`
(`data/raw/metric_definitions.csv`) — every experiment that ran across a
definition change has both rows with non-overlapping `effective_start`/
`effective_end` dates.

## Why this matters (EXP-005 case study)

`EXP-005 (active_user_definition_change_test)` deliberately changes the
`active_user` definition partway through the experiment. Querying
"active users" for this experiment without checking which definition
version applied to which half of the data produces a number that mixes
two incompatible logics — this is exactly the kind of silent
inconsistency that causes cross-team metric disputes in production.

Query `sql/analytics/trust_analytics.sql :: Q4` quantifies the divergence
directly: how many users would be counted as "active" under v1 vs. v2 for
every experiment, not just the one where it was intentionally changed —
because in practice, unannounced definition drift is the norm, not the
exception.

## How to extend this

In a production system, this table would be populated automatically from
a metrics catalog / semantic layer (e.g., dbt metrics, LookML) rather than
hand-maintained, and the divergence check (Q4) would run as a scheduled
CI job that alerts analytics engineering when two definitions of the same
metric diverge by more than a threshold.
