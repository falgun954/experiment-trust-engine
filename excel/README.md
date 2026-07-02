# Excel Edition — Experiment Trust Engine

`Experiment_Trust_Engine.xlsx` is a fully live, formula-driven rebuild of
the Power BI report. It exists because Power BI Desktop requires local
admin rights that weren't available on the build machine — everything in
this workbook is a **real Excel formula**, not a pasted value, so it
recalculates if you edit `Raw_Inputs`.

## Why this isn't a downgrade

Every statistical calculation from `dax/measures.md` is reproduced as a
native Excel formula on the `Trust_Engine` sheet:

| Check | DAX (Power BI) | Excel equivalent |
|---|---|---|
| SRM p-value | `CHISQ.DIST.RT` | `CHIDIST` (identical result, universally supported) |
| Z-test p-value | `NORM.S.DIST(x, TRUE)` | `NORMSDIST(x)` (identical result) |
| Trust Score composite | DAX measure with `VAR`/`RETURN` | Same weighted-sum logic across named columns |

This means the Excel model is a **direct, verifiable port** of the same
methodology — not a simplified mockup. 348 formulas, zero errors
(validated with LibreOffice recalculation).

## Sheets

| Sheet | Contents |
|---|---|
| `README` | Overview + color legend |
| `Dashboard` | KPI cards (all `COUNTIF`/`AVERAGE` formulas) + Trust Score bar chart + novelty-decay line chart |
| `Trust_Engine` | Every SRM/z-test/CI/trust-score formula, one row per experiment |
| `Raw_Inputs` | Hardcoded counts (blue font, sourced from the synthetic event log) |
| `Daily_Lift` | Day-by-day lift per experiment, feeds the novelty chart |
| `Metric_Lineage` | Metric definition version history |

## One methodology difference worth knowing

The Excel model computes **metric-definition agreement live for every
experiment** (comparing `active_users_def_v1` vs `def_v2` counts
directly), the same way the SQL governance view and DAX page do. The
original Python `pipeline.py` report used a simplified version that only
computed real divergence for the one experiment with an official
definition-version change, defaulting others to 100% agreement. This
means Excel's Trust Scores are slightly different (and arguably more
consistent with the rest of the project) — both are legitimate; the
difference is documented here rather than hidden.

## Regenerating

If you regenerate the underlying data (`python src/pipeline.py`), rerun:

```bash
python src/generation/generate_data.py
python src/pipeline.py
python excel/build_excel_inputs.py   # produces data/processed/excel_raw_inputs.csv, daily_lift_wide.csv
python excel/build_excel.py
```

## Migrating to Power BI later

Once Power BI Desktop is available (see `powerbi/BUILD_INSTRUCTIONS.md`),
this workbook can be imported directly: **Get Data → Excel** pointed at
`Raw_Inputs`, `Daily_Lift`, and `Metric_Lineage`, then paste the DAX from
`dax/measures.md` — same tables, same logic, same column names.
