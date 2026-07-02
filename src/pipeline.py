"""
Runs the full trust-engine analysis over every experiment in data/raw/ and
writes analysis-ready tables to data/processed/:

    experiment_results.csv   one row per experiment: SRM, lift, CI, trust score
    daily_lift.csv           daily treatment lift per experiment (novelty detection input)
    metric_definition_diff.csv  active_user counts under v1 vs v2 definitions where applicable

Run:
    python src/pipeline.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

from stats.trust_engine import (
    novelty_effect_score,
    srm_chi_square,
    trust_score,
    two_proportion_ztest,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

MIN_DETECTABLE_EFFECT = 0.02  # 2 percentage points, the org's standard MDE


def load_raw():
    return (
        pd.read_csv(RAW / "experiments.csv"),
        pd.read_csv(RAW / "assignments.csv"),
        pd.read_csv(RAW / "events.csv", parse_dates=["event_timestamp"]),
        pd.read_csv(RAW / "metric_definitions.csv"),
    )


def required_sample_size(baseline_p=0.10, mde=MIN_DETECTABLE_EFFECT, alpha=0.05, power=0.8):
    """Rough two-proportion sample size formula, per arm."""
    from scipy import stats as sstats
    z_alpha = sstats.norm.ppf(1 - alpha / 2)
    z_beta = sstats.norm.ppf(power)
    p1 = baseline_p
    p2 = baseline_p + mde
    p_bar = (p1 + p2) / 2
    n = ((z_alpha * np.sqrt(2 * p_bar * (1 - p_bar)) +
          z_beta * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / (p2 - p1) ** 2
    return int(np.ceil(n))


def analyze_experiment(exp_id, assignments, events, metric_defs):
    a = assignments[assignments.experiment_id == exp_id]
    e = events[events.experiment_id == exp_id]

    control_n = (a.variant == "control").sum()
    treatment_n = (a.variant == "treatment").sum()

    srm = srm_chi_square(control_n, treatment_n)

    conversions = e[e.event_type == "conversion"]
    control_conv = conversions[conversions.variant == "control"].user_id.nunique()
    treatment_conv = conversions[conversions.variant == "treatment"].user_id.nunique()

    ztest = two_proportion_ztest(control_conv, control_n, treatment_conv, treatment_n)

    # --- novelty effect: daily lift over the experiment's lifetime ---
    e = e.copy()
    e["day"] = (e.event_timestamp - e.event_timestamp.min()).dt.days
    daily_rows = []
    for day in sorted(e.day.unique()):
        day_events = e[e.day <= day]
        day_conv = day_events[day_events.event_type == "conversion"]
        c_n = a[a.variant == "control"].shape[0]
        t_n = a[a.variant == "treatment"].shape[0]
        c_conv = day_conv[day_conv.variant == "control"].user_id.nunique()
        t_conv = day_conv[day_conv.variant == "treatment"].user_id.nunique()
        if c_n and t_n:
            daily_rows.append(dict(
                experiment_id=exp_id, day=day,
                control_rate=c_conv / c_n, treatment_rate=t_conv / t_n,
                lift=(t_conv / t_n) - (c_conv / c_n),
            ))
    daily_df = pd.DataFrame(daily_rows)
    if len(daily_df) >= 3:
        novelty = novelty_effect_score(daily_df.day.values, daily_df.lift.values)
    else:
        novelty = dict(slope=0.0, decay_pct_per_day=0.0, is_novelty_effect=False)

    # --- guardrail check ---
    guardrails = e[e.event_type == "guardrail_complaint"]
    c_guard = guardrails[guardrails.variant == "control"].user_id.nunique() / max(control_n, 1)
    t_guard = guardrails[guardrails.variant == "treatment"].user_id.nunique() / max(treatment_n, 1)
    guardrail_ztest = two_proportion_ztest(
        guardrails[guardrails.variant == "control"].user_id.nunique(), control_n,
        guardrails[guardrails.variant == "treatment"].user_id.nunique(), treatment_n,
    )
    guardrail_breached = guardrail_ztest.is_significant and t_guard > c_guard

    # --- metric definition agreement ---
    defs = metric_defs[metric_defs.experiment_id == exp_id]
    if len(defs) > 1:
        # active_user v1: >=1 event; v2: >=2 events AND >=1 engagement/conversion event
        counts = e.groupby("user_id").agg(
            n_events=("event_id", "count"),
            n_core=("event_type", lambda s: (s.isin(["engagement", "conversion"])).sum()),
        )
        v1_active = (counts.n_events >= 1).sum()
        v2_active = ((counts.n_events >= 2) & (counts.n_core >= 1)).sum()
        agreement_pct = (min(v1_active, v2_active) / max(v1_active, v2_active) * 100) if max(v1_active, v2_active) else 100.0
    else:
        v1_active, v2_active, agreement_pct = None, None, 100.0

    req_n = required_sample_size()
    sample_adequate = min(control_n, treatment_n) >= req_n

    ts = trust_score(
        srm=srm,
        definition_agreement_pct=agreement_pct,
        guardrail_breached=guardrail_breached,
        sample_size_adequate=sample_adequate,
        novelty_detected=novelty["is_novelty_effect"],
    )

    result = dict(
        experiment_id=exp_id,
        control_n=control_n, treatment_n=treatment_n,
        srm_chi_square=srm.chi_square, srm_p_value=srm.p_value, is_srm=srm.is_srm,
        control_conv_rate=ztest.control_rate, treatment_conv_rate=ztest.treatment_rate,
        absolute_lift=ztest.absolute_lift, relative_lift_pct=ztest.relative_lift_pct,
        p_value=ztest.p_value, ci_lower=ztest.ci_lower, ci_upper=ztest.ci_upper,
        is_significant=ztest.is_significant,
        novelty_decay_pct_per_day=novelty.get("decay_pct_per_day", 0.0),
        is_novelty_effect=novelty["is_novelty_effect"],
        guardrail_control_rate=round(c_guard, 5), guardrail_treatment_rate=round(t_guard, 5),
        guardrail_breached=guardrail_breached,
        metric_definition_agreement_pct=round(agreement_pct, 2),
        required_sample_size_per_arm=req_n,
        sample_size_adequate=sample_adequate,
        trust_score=ts["trust_score"], verdict=ts["verdict"],
        trust_reasons="; ".join(ts["reasons"]) if ts["reasons"] else "No issues detected",
    )
    return result, daily_df


def main():
    experiments, assignments, events, metric_defs = load_raw()

    all_results = []
    all_daily = []
    for exp_id in experiments.experiment_id:
        print(f"Analyzing {exp_id}...")
        result, daily_df = analyze_experiment(exp_id, assignments, events, metric_defs)
        all_results.append(result)
        all_daily.append(daily_df)

    results_df = pd.DataFrame(all_results)
    daily_df = pd.concat(all_daily, ignore_index=True)

    results_df = results_df.merge(
        experiments[["experiment_id", "experiment_name", "owner_team", "start_date", "end_date"]],
        on="experiment_id",
    )

    results_df.to_csv(PROCESSED / "experiment_results.csv", index=False)
    daily_df.to_csv(PROCESSED / "daily_lift.csv", index=False)

    print("\n=== Trust Score Summary ===")
    print(results_df[["experiment_id", "experiment_name", "trust_score", "verdict"]].to_string(index=False))
    print(f"\nWrote {PROCESSED / 'experiment_results.csv'}")
    print(f"Wrote {PROCESSED / 'daily_lift.csv'}")


if __name__ == "__main__":
    main()
