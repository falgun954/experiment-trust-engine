-- Experiment Trust Engine — Analysis Views
-- These views compute everything the Python trust engine and the Power BI
-- DAX layer both need: allocation counts (for SRM), conversion rates (for
-- the z-test), and metric-definition divergence (for the governance score).

-- ---------------------------------------------------------------------
-- 1. Allocation counts per experiment/variant — feeds SRM chi-square test
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_allocation_counts AS
SELECT
    experiment_id,
    variant,
    COUNT(*) AS n_users
FROM fact_assignment
GROUP BY experiment_id, variant;

CREATE VIEW IF NOT EXISTS v_allocation_pivot AS
SELECT
    experiment_id,
    SUM(CASE WHEN variant = 'control' THEN n_users ELSE 0 END)   AS control_n,
    SUM(CASE WHEN variant = 'treatment' THEN n_users ELSE 0 END) AS treatment_n
FROM v_allocation_counts
GROUP BY experiment_id;

-- ---------------------------------------------------------------------
-- 2. Conversion rate per experiment/variant — feeds the two-proportion z-test
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_conversions AS
SELECT
    fe.experiment_id,
    fe.variant,
    COUNT(DISTINCT fe.user_id) AS converted_users,
    SUM(fe.event_value)        AS total_conversion_value
FROM fact_event fe
WHERE fe.event_type = 'conversion'
GROUP BY fe.experiment_id, fe.variant;

CREATE VIEW IF NOT EXISTS v_conversion_summary AS
SELECT
    a.experiment_id,
    a.control_n,
    a.treatment_n,
    COALESCE(cc.converted_users, 0) AS control_conversions,
    COALESCE(ct.converted_users, 0) AS treatment_conversions,
    ROUND(1.0 * COALESCE(cc.converted_users, 0) / NULLIF(a.control_n, 0), 5)   AS control_conv_rate,
    ROUND(1.0 * COALESCE(ct.converted_users, 0) / NULLIF(a.treatment_n, 0), 5) AS treatment_conv_rate
FROM v_allocation_pivot a
LEFT JOIN v_conversions cc ON cc.experiment_id = a.experiment_id AND cc.variant = 'control'
LEFT JOIN v_conversions ct ON ct.experiment_id = a.experiment_id AND ct.variant = 'treatment';

-- ---------------------------------------------------------------------
-- 3. Guardrail metric rate per experiment/variant
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_guardrail_summary AS
SELECT
    a.experiment_id,
    ROUND(1.0 * COALESCE(SUM(CASE WHEN fe.variant = 'control' AND fe.event_type = 'guardrail_complaint'
        THEN 1 ELSE 0 END), 0) / NULLIF(a.control_n, 0), 5) AS control_guardrail_rate,
    ROUND(1.0 * COALESCE(SUM(CASE WHEN fe.variant = 'treatment' AND fe.event_type = 'guardrail_complaint'
        THEN 1 ELSE 0 END), 0) / NULLIF(a.treatment_n, 0), 5) AS treatment_guardrail_rate
FROM v_allocation_pivot a
LEFT JOIN fact_event fe ON fe.experiment_id = a.experiment_id
GROUP BY a.experiment_id, a.control_n, a.treatment_n;

-- ---------------------------------------------------------------------
-- 4. Metric definition divergence — the governance signature view.
--    Computes the SAME "active_user" metric under every definition version
--    that applied during the experiment, so divergence is directly queryable.
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_user_event_counts AS
SELECT
    experiment_id,
    user_id,
    COUNT(*) AS n_events,
    SUM(CASE WHEN event_type IN ('engagement', 'conversion') THEN 1 ELSE 0 END) AS n_core_events
FROM fact_event
GROUP BY experiment_id, user_id;

CREATE VIEW IF NOT EXISTS v_metric_definition_divergence AS
SELECT
    experiment_id,
    SUM(CASE WHEN n_events >= 1 THEN 1 ELSE 0 END) AS active_users_def_v1,
    SUM(CASE WHEN n_events >= 2 AND n_core_events >= 1 THEN 1 ELSE 0 END) AS active_users_def_v2
FROM v_user_event_counts
GROUP BY experiment_id;

-- ---------------------------------------------------------------------
-- 5. Daily lift — feeds novelty-effect regression (lift trend over time)
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_daily_conversion_rate AS
SELECT
    fe.experiment_id,
    fe.variant,
    DATE(fe.event_timestamp) AS event_date,
    COUNT(DISTINCT CASE WHEN fe.event_type = 'conversion' THEN fe.user_id END) AS conversions,
    COUNT(DISTINCT fe.user_id) AS active_users
FROM fact_event fe
GROUP BY fe.experiment_id, fe.variant, DATE(fe.event_timestamp);
