# DAX Measure Library — Experiment Trust Engine

Every measure below mirrors a function in `src/stats/trust_engine.py` or a
view in `sql/views/analysis_views.sql` **exactly**, so the Power BI report,
the SQL layer, and the Python validation layer can never silently disagree.
This file doubles as the "metric lineage" documentation piece.

Import `data/processed/experiment_results.csv` and `data/processed/daily_lift.csv`
as tables (`FactTrustScore`, `FactDailyLift`), alongside the raw dimension
tables, then build the measures below.

---

## 1. Allocation / SRM measures

```dax
Control N =
SUM ( FactTrustScore[control_n] )

Treatment N =
SUM ( FactTrustScore[treatment_n] )

Observed Treatment Ratio =
DIVIDE ( [Treatment N], [Control N] + [Treatment N] )

-- Chi-square goodness of fit against a 50/50 expected split
SRM Chi Square =
VAR TotalN = [Control N] + [Treatment N]
VAR ExpectedEach = TotalN / 2
VAR ChiControl = DIVIDE ( ( [Control N] - ExpectedEach ) ^ 2, ExpectedEach )
VAR ChiTreatment = DIVIDE ( ( [Treatment N] - ExpectedEach ) ^ 2, ExpectedEach )
RETURN
    ChiControl + ChiTreatment

-- Approximate p-value via CHISQ.DIST.RT (df = 1)
SRM P Value =
CHISQ.DIST.RT ( [SRM Chi Square], 1 )

Is SRM =
IF ( [SRM P Value] < 0.001, 1, 0 )   -- alpha = 0.001 per SRM industry convention
```

## 2. Two-proportion z-test measures

```dax
Control Conversions =
SUM ( FactTrustScore[control_conversions] )   -- or COUNT DISTINCT from FactEvent

Treatment Conversions =
SUM ( FactTrustScore[treatment_conversions] )

Control Conv Rate =
DIVIDE ( [Control Conversions], [Control N] )

Treatment Conv Rate =
DIVIDE ( [Treatment Conversions], [Treatment N] )

Absolute Lift =
[Treatment Conv Rate] - [Control Conv Rate]

Relative Lift % =
DIVIDE ( [Absolute Lift], [Control Conv Rate] ) * 100

Pooled Rate =
DIVIDE ( [Control Conversions] + [Treatment Conversions], [Control N] + [Treatment N] )

Pooled SE =
SQRT (
    [Pooled Rate] * ( 1 - [Pooled Rate] )
    * ( DIVIDE ( 1, [Control N] ) + DIVIDE ( 1, [Treatment N] ) )
)

Z Stat =
DIVIDE ( [Absolute Lift], [Pooled SE] )

P Value =
2 * ( 1 - NORM.S.DIST ( ABS ( [Z Stat] ), TRUE ) )

Is Significant =
IF ( [P Value] < 0.05, 1, 0 )

-- 95% CI on the absolute lift (unpooled SE, standard for CIs)
Unpooled SE =
SQRT (
    DIVIDE ( [Control Conv Rate] * ( 1 - [Control Conv Rate] ), [Control N] )
    + DIVIDE ( [Treatment Conv Rate] * ( 1 - [Treatment Conv Rate] ), [Treatment N] )
)

CI Lower =
[Absolute Lift] - 1.96 * [Unpooled SE]

CI Upper =
[Absolute Lift] + 1.96 * [Unpooled SE]
```

## 3. Novelty effect measures (built on `FactDailyLift`)

```dax
Lift 3Day Moving Avg =
AVERAGEX (
    WINDOW ( -2, REL, 0, REL, ALLEXCEPT ( FactDailyLift, FactDailyLift[experiment_id] ), ORDERBY ( FactDailyLift[day] ) ),
    FactDailyLift[lift]
)

-- Slope of lift vs. day using the standard linear regression formula
Novelty Slope =
VAR N = COUNTROWS ( FactDailyLift )
VAR SumX = SUM ( FactDailyLift[day] )
VAR SumY = SUM ( FactDailyLift[lift] )
VAR SumXY = SUMX ( FactDailyLift, FactDailyLift[day] * FactDailyLift[lift] )
VAR SumX2 = SUMX ( FactDailyLift, FactDailyLift[day] ^ 2 )
RETURN
    DIVIDE ( N * SumXY - SumX * SumY, N * SumX2 - SumX ^ 2 )

Is Novelty Effect =
VAR AvgLift = AVERAGE ( FactDailyLift[lift] )
VAR DecayPct = DIVIDE ( ABS ( [Novelty Slope] ), ABS ( AvgLift ) ) * 100
RETURN
    IF ( [Novelty Slope] < 0 && DecayPct > 2, 1, 0 )
```

## 4. Guardrail measures

```dax
Control Guardrail Rate =
DIVIDE ( SUM ( FactTrustScore[guardrail_control_rate] ), 1 )   -- precomputed upstream

Treatment Guardrail Rate =
DIVIDE ( SUM ( FactTrustScore[guardrail_treatment_rate] ), 1 )

Guardrail Breached =
IF ( [Treatment Guardrail Rate] > [Control Guardrail Rate], 1, 0 )
```

## 5. Metric definition governance measures

```dax
Active Users Def V1 =
SUM ( FactMetricDivergence[active_users_def_v1] )

Active Users Def V2 =
SUM ( FactMetricDivergence[active_users_def_v2] )

Definition Agreement % =
VAR Bigger = MAX ( [Active Users Def V1], [Active Users Def V2] )
VAR Smaller = MIN ( [Active Users Def V1], [Active Users Def V2] )
RETURN
    DIVIDE ( Smaller, Bigger ) * 100
```

## 6. The Trust Score — the single composite measure

```dax
Trust Score =
VAR SrmPts = IF ( [Is SRM] = 0, 30, 0 )
VAR DefPts = MIN ( [Definition Agreement %], 100 ) / 100 * 25
VAR GuardrailPts = IF ( [Guardrail Breached] = 0, 20, 0 )
VAR SampleSizePts = IF ( MIN ( [Control N], [Treatment N] ) >= [Required Sample Size Per Arm], 15, 0 )
VAR NoveltyPts = IF ( [Is Novelty Effect] = 0, 10, 0 )
RETURN
    SrmPts + DefPts + GuardrailPts + SampleSizePts + NoveltyPts

Trust Verdict =
SWITCH (
    TRUE (),
    [Trust Score] >= 85, "TRUST",
    [Trust Score] >= 60, "TRUST WITH CAVEATS",
    "DO NOT TRUST"
)

-- Required sample size per arm, precomputed in Python (src/pipeline.py::required_sample_size)
-- and loaded as a column since DAX has no native inverse-normal power calc.
Required Sample Size Per Arm =
SUM ( FactTrustScore[required_sample_size_per_arm] )
```

## 7. Report-level rollups

```dax
% Experiments Trustworthy =
DIVIDE (
    CALCULATE ( COUNTROWS ( FactTrustScore ), FactTrustScore[verdict] = "TRUST" ),
    COUNTROWS ( FactTrustScore )
) * 100

Experiments Flagged Do Not Trust =
CALCULATE ( COUNTROWS ( FactTrustScore ), FactTrustScore[verdict] = "DO NOT TRUST" )

Avg Trust Score By Team =
AVERAGEX ( VALUES ( FactTrustScore[owner_team] ), [Trust Score] )
```

---

## Design notes for the report build

- **Trust Score card** should be the first visual on the Experiment Overview
  page — treat it like a health-check gauge (red < 60, amber 60-84, green ≥ 85).
- **Metric Definition Comparison page**: build a clustered bar chart of
  `Active Users Def V1` vs `Active Users Def V2` per experiment, sorted by
  `Definition Agreement %` ascending — the divergence should be visually
  obvious without reading numbers.
- **Statistical Deep-Dive page**: plot `CI Lower`/`CI Upper` as an error-bar
  chart around `Absolute Lift`, and add a table with `SRM Chi Square`,
  `SRM P Value`, `Is Novelty Effect` so a reviewer can audit the exact math.
- **Metric Lineage page**: a plain table sourced from `dim_metric_definition`
  showing `definition_logic`, `effective_start`, `effective_end` per
  metric/experiment — this is documentation-as-a-dashboard-page, which is
  the governance differentiator.
