"""
Prepares the two CSVs that build_excel.py needs beyond what pipeline.py
already produces: raw per-arm counts (for live Excel formulas, since the
Python pipeline only exports rates) and a wide-format daily lift table
(for easy multi-series charting in Excel).

Run after src/generation/generate_data.py and src/pipeline.py:
    python excel/build_excel_inputs.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"


def main():
    assignments = pd.read_csv(RAW / "assignments.csv")
    events = pd.read_csv(RAW / "events.csv")
    results = pd.read_csv(PROCESSED / "experiment_results.csv")
    daily = pd.read_csv(PROCESSED / "daily_lift.csv")

    # metric definition divergence (active_user v1 vs v2 counts, all experiments)
    counts = events.groupby(["experiment_id", "user_id"]).agg(
        n_events=("event_id", "count"),
        n_core=("event_type", lambda s: s.isin(["engagement", "conversion"]).sum()),
    ).reset_index()
    v1 = counts[counts.n_events >= 1].groupby("experiment_id").size().rename("active_users_def_v1")
    v2 = counts[(counts.n_events >= 2) & (counts.n_core >= 1)].groupby("experiment_id").size().rename("active_users_def_v2")
    div = pd.concat([v1, v2], axis=1).reset_index()

    # raw per-arm counts (control_n/treatment_n/conversions/guardrail counts)
    alloc = assignments.groupby(["experiment_id", "variant"]).size().unstack(fill_value=0).reset_index()
    conv = events[events.event_type == "conversion"].groupby(
        ["experiment_id", "variant"])["user_id"].nunique().unstack(fill_value=0).reset_index()
    guard = events[events.event_type == "guardrail_complaint"].groupby(
        ["experiment_id", "variant"])["user_id"].nunique().unstack(fill_value=0).reset_index()

    raw = alloc.merge(conv, on="experiment_id", suffixes=("_n", "_conv"))
    raw = raw.merge(guard, on="experiment_id", suffixes=("", "_guard"))
    raw.columns = ["experiment_id", "control_n", "treatment_n",
                   "control_conversions", "treatment_conversions",
                   "control_guardrail_n", "treatment_guardrail_n"]
    raw = raw.merge(div, on="experiment_id")
    raw = raw.merge(
        results[["experiment_id", "experiment_name", "owner_team",
                  "required_sample_size_per_arm", "novelty_decay_pct_per_day",
                  "is_novelty_effect", "start_date", "end_date"]],
        on="experiment_id",
    )
    raw.to_csv(PROCESSED / "excel_raw_inputs.csv", index=False)

    wide = daily.pivot_table(index="day", columns="experiment_id", values="lift")
    wide.to_csv(PROCESSED / "daily_lift_wide.csv")

    print(f"Wrote {PROCESSED / 'excel_raw_inputs.csv'} ({len(raw)} rows)")
    print(f"Wrote {PROCESSED / 'daily_lift_wide.csv'} ({wide.shape})")


if __name__ == "__main__":
    main()
