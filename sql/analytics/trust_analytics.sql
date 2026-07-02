-- Experiment Trust Engine — Analytics Queries
-- Demonstrates window functions, CTEs, and ranking on top of the views.
-- Run against data/warehouse.db (SQLite) or any Postgres warehouse using
-- the same DDL/views.

-- =====================================================================
-- Q1. Trust Score leaderboard — rank experiments, flag the worst offenders
-- =====================================================================
SELECT
    experiment_id,
    experiment_name,
    owner_team,
    trust_score,
    verdict,
    RANK() OVER (ORDER BY trust_score ASC) AS worst_trust_rank,
    RANK() OVER (PARTITION BY owner_team ORDER BY trust_score DESC) AS rank_within_team
FROM fact_trust_score
ORDER BY trust_score ASC;

-- =====================================================================
-- Q2. Team-level governance health — % of each team's experiments that
--     would have been WRONGLY called a "win" without the trust layer
-- =====================================================================
SELECT
    owner_team,
    COUNT(*) AS total_experiments,
    SUM(CASE WHEN is_significant = 1 THEN 1 ELSE 0 END) AS statistically_significant,
    SUM(CASE WHEN is_significant = 1 AND verdict != 'TRUST' THEN 1 ELSE 0 END)
        AS significant_but_untrustworthy,
    ROUND(100.0 * SUM(CASE WHEN is_significant = 1 AND verdict != 'TRUST' THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_significant = 1 THEN 1 ELSE 0 END), 0), 1)
        AS pct_significant_results_actually_untrustworthy
FROM fact_trust_score
GROUP BY owner_team
ORDER BY pct_significant_results_actually_untrustworthy DESC;

-- =====================================================================
-- Q3. Lift decay curve — running average lift by day, per experiment,
--     to visualize novelty effects (window function: moving average)
-- =====================================================================
SELECT
    experiment_id,
    day,
    lift,
    AVG(lift) OVER (
        PARTITION BY experiment_id
        ORDER BY day
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ) AS lift_3day_moving_avg,
    lift - FIRST_VALUE(lift) OVER (
        PARTITION BY experiment_id ORDER BY day
    ) AS lift_change_from_day_zero
FROM fact_daily_lift
ORDER BY experiment_id, day;

-- =====================================================================
-- Q4. Metric definition divergence report — the governance signature query.
--     Shows exactly how much an "active user" count would swing depending
--     on which definition a team happened to query with.
-- =====================================================================
SELECT
    d.experiment_id,
    e.experiment_name,
    d.active_users_def_v1,
    d.active_users_def_v2,
    (d.active_users_def_v1 - d.active_users_def_v2) AS absolute_divergence,
    ROUND(100.0 * ABS(d.active_users_def_v1 - d.active_users_def_v2)
        / NULLIF(d.active_users_def_v1, 0), 2) AS pct_divergence
FROM v_metric_definition_divergence d
JOIN dim_experiment e ON e.experiment_id = d.experiment_id
ORDER BY pct_divergence DESC;

-- =====================================================================
-- Q5. SRM audit trail — every experiment's observed vs expected allocation,
--     with the exact chi-square/p-value a reviewer would need to sign off
-- =====================================================================
SELECT
    experiment_id,
    control_n,
    treatment_n,
    ROUND(1.0 * treatment_n / (control_n + treatment_n), 4) AS observed_treatment_ratio,
    CASE
        WHEN ABS(1.0 * treatment_n / (control_n + treatment_n) - 0.5) > 0.02
        THEN 'INVESTIGATE'
        ELSE 'OK'
    END AS allocation_flag
FROM v_allocation_pivot
ORDER BY ABS(1.0 * treatment_n / (control_n + treatment_n) - 0.5) DESC;
