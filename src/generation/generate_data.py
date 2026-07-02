"""
Synthetic A/B experiment data generator for the Experiment Trust Engine.

Generates a realistic experimentation warehouse export:
    - experiments.csv        experiment metadata
    - users.csv              user dimension
    - assignments.csv        variant assignment log (bucketing)
    - events.csv             raw event stream (exposures, conversions, guardrail signals)
    - metric_definitions.csv metric definition version history (the governance angle)

Deliberately injects issues found in real experimentation platforms so the
downstream SQL/DAX layer has something real to detect:

    1. Sample Ratio Mismatch (SRM)   -> one experiment has a broken bucketer
    2. Metric definition drift        -> "active_user" logic changes mid-experiment
    3. Novelty effect                 -> treatment lift decays over time
    4. Guardrail regression           -> a "winning" experiment secretly hurts latency/complaints
    5. Underpowered experiment        -> too few users to trust the result at all

Run:
    python src/generation/generate_data.py
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

COUNTRIES = ["US", "UK", "DE", "IN", "BR", "JP"]
PLATFORMS = ["ios", "android", "web"]

# ---------------------------------------------------------------------------
# Experiment catalog — each row encodes one "issue archetype" we want the
# Trust Engine to be able to detect and score.
# ---------------------------------------------------------------------------
EXPERIMENTS = [
    dict(experiment_id="EXP-001", name="checkout_button_color", owner_team="growth",
         n_users=40000, srm=False, true_lift=0.06, novelty_decay=False,
         guardrail_hit=False, definition_change=False, duration_days=21),
    dict(experiment_id="EXP-002", name="onboarding_flow_v2", owner_team="growth",
         n_users=60000, srm=True, srm_ratio=0.56, true_lift=0.04, novelty_decay=False,
         guardrail_hit=False, definition_change=False, duration_days=21),
    dict(experiment_id="EXP-003", name="recommendation_ranker_v3", owner_team="ml-platform",
         n_users=90000, srm=False, true_lift=0.10, novelty_decay=True,
         guardrail_hit=False, definition_change=False, duration_days=28),
    dict(experiment_id="EXP-004", name="notification_frequency_increase", owner_team="growth",
         n_users=70000, srm=False, true_lift=0.05, novelty_decay=False,
         guardrail_hit=True, definition_change=False, duration_days=21),
    dict(experiment_id="EXP-005", name="active_user_definition_change_test", owner_team="analytics-eng",
         n_users=50000, srm=False, true_lift=0.03, novelty_decay=False,
         guardrail_hit=False, definition_change=True, duration_days=21),
    dict(experiment_id="EXP-006", name="pricing_page_redesign", owner_team="monetization",
         n_users=8000, srm=False, true_lift=0.08, novelty_decay=False,
         guardrail_hit=False, definition_change=False, duration_days=14),
    dict(experiment_id="EXP-007", name="search_autocomplete_v2", owner_team="search",
         n_users=85000, srm=False, true_lift=0.00, novelty_decay=False,
         guardrail_hit=False, definition_change=False, duration_days=21),
    dict(experiment_id="EXP-008", name="signup_form_shortening", owner_team="growth",
         n_users=55000, srm=True, srm_ratio=0.53, true_lift=0.07, novelty_decay=True,
         guardrail_hit=True, definition_change=False, duration_days=21),
]

BASE_DATE = datetime(2025, 1, 6)  # a Monday


def gen_experiments_table():
    rows = []
    for e in EXPERIMENTS:
        start = BASE_DATE + timedelta(days=random.randint(0, 200))
        end = start + timedelta(days=e["duration_days"])
        rows.append(dict(
            experiment_id=e["experiment_id"],
            experiment_name=e["name"],
            owner_team=e["owner_team"],
            hypothesis=f"Changing {e['name'].replace('_', ' ')} will improve the north-star metric",
            start_date=start.date().isoformat(),
            end_date=end.date().isoformat(),
            status="completed",
            planned_allocation="50/50",
        ))
    return pd.DataFrame(rows)


def gen_users_table(total_users):
    rows = []
    for i in range(total_users):
        signup = BASE_DATE - timedelta(days=random.randint(0, 720))
        rows.append(dict(
            user_id=f"U-{i:07d}",
            signup_date=signup.date().isoformat(),
            country=random.choices(COUNTRIES, weights=[35, 15, 12, 20, 10, 8])[0],
            platform=random.choices(PLATFORMS, weights=[40, 40, 20])[0],
        ))
    return pd.DataFrame(rows)


def assign_variant(n, srm, srm_ratio):
    """Return an array of 'control'/'treatment' honoring an optional SRM bias."""
    if srm:
        treat_share = srm_ratio
    else:
        treat_share = 0.5
    return np.where(np.random.random(n) < treat_share, "treatment", "control")


def gen_assignments_and_events(users_df):
    assignment_rows = []
    event_rows = []
    metric_def_rows = []
    event_id_counter = 0

    all_user_ids = users_df["user_id"].tolist()

    for e in EXPERIMENTS:
        exp_id = e["experiment_id"]
        n = e["n_users"]
        exp_users = np.random.choice(all_user_ids, size=n, replace=False)
        variants = assign_variant(n, e.get("srm", False), e.get("srm_ratio", 0.5))

        start = datetime.fromisoformat(
            [r for r in gen_experiments_table().to_dict("records") if r["experiment_id"] == exp_id][0]["start_date"]
        )

        # --- metric definition history (governance angle) ---
        if e["definition_change"]:
            metric_def_rows.append(dict(
                metric_name="active_user", experiment_id=exp_id, definition_version="v1",
                definition_logic="Any user with >= 1 tracked event in the exposure window",
                effective_start=start.date().isoformat(),
                effective_end=(start + timedelta(days=e["duration_days"] // 2)).date().isoformat(),
            ))
            metric_def_rows.append(dict(
                metric_name="active_user", experiment_id=exp_id, definition_version="v2",
                definition_logic="User with >= 2 tracked events AND >= 1 core action event",
                effective_start=(start + timedelta(days=e["duration_days"] // 2)).date().isoformat(),
                effective_end=(start + timedelta(days=e["duration_days"])).date().isoformat(),
            ))
        else:
            metric_def_rows.append(dict(
                metric_name="active_user", experiment_id=exp_id, definition_version="v1",
                definition_logic="Any user with >= 1 tracked event in the exposure window",
                effective_start=start.date().isoformat(),
                effective_end=(start + timedelta(days=e["duration_days"])).date().isoformat(),
            ))

        for uid, variant in zip(exp_users, variants):
            assign_day_offset = random.randint(0, max(e["duration_days"] - 1, 1))
            assign_date = start + timedelta(days=assign_day_offset)
            assignment_rows.append(dict(
                experiment_id=exp_id, user_id=uid, variant=variant,
                assignment_timestamp=assign_date.isoformat(),
            ))

            # base conversion probability
            base_p = 0.10
            lift = e["true_lift"] if variant == "treatment" else 0.0

            # novelty decay: lift shrinks the further into the experiment we are
            days_in = (assign_day_offset / max(e["duration_days"], 1))
            if e["novelty_decay"] and variant == "treatment":
                lift = lift * max(0.15, 1 - 1.3 * days_in)

            p_convert = min(max(base_p + lift, 0.001), 0.95)

            # exposure event always fires
            event_id_counter += 1
            event_rows.append(dict(
                event_id=event_id_counter, experiment_id=exp_id, user_id=uid, variant=variant,
                event_type="exposure", event_timestamp=assign_date.isoformat(), event_value=1,
            ))

            # possible extra engagement events (feeds active_user v2 definition)
            n_engagement_events = np.random.poisson(1.4 if variant == "treatment" else 1.2)
            for _ in range(n_engagement_events):
                event_id_counter += 1
                ts = assign_date + timedelta(hours=random.randint(1, 96))
                event_rows.append(dict(
                    event_id=event_id_counter, experiment_id=exp_id, user_id=uid, variant=variant,
                    event_type="engagement", event_timestamp=ts.isoformat(), event_value=1,
                ))

            # conversion event
            if np.random.random() < p_convert:
                event_id_counter += 1
                ts = assign_date + timedelta(hours=random.randint(1, 120))
                event_rows.append(dict(
                    event_id=event_id_counter, experiment_id=exp_id, user_id=uid, variant=variant,
                    event_type="conversion", event_timestamp=ts.isoformat(),
                    event_value=round(np.random.gamma(2.0, 15.0), 2),
                ))

            # guardrail signal: customer complaints / latency degradation
            guardrail_base = 0.02
            guardrail_bump = 0.025 if (e["guardrail_hit"] and variant == "treatment") else 0.0
            if np.random.random() < (guardrail_base + guardrail_bump):
                event_id_counter += 1
                ts = assign_date + timedelta(hours=random.randint(1, 120))
                event_rows.append(dict(
                    event_id=event_id_counter, experiment_id=exp_id, user_id=uid, variant=variant,
                    event_type="guardrail_complaint", event_timestamp=ts.isoformat(), event_value=1,
                ))

    return (
        pd.DataFrame(assignment_rows),
        pd.DataFrame(event_rows),
        pd.DataFrame(metric_def_rows),
    )


def main():
    total_users = 200_000
    print(f"Generating {total_users:,} users...")
    users_df = gen_users_table(total_users)

    print("Generating experiments table...")
    experiments_df = gen_experiments_table()

    print("Generating assignments + events (this simulates real bucketing/event logs)...")
    assignments_df, events_df, metric_defs_df = gen_assignments_and_events(users_df)

    print("Writing CSVs to data/raw/ ...")
    users_df.to_csv(RAW_DIR / "users.csv", index=False)
    experiments_df.to_csv(RAW_DIR / "experiments.csv", index=False)
    assignments_df.to_csv(RAW_DIR / "assignments.csv", index=False)
    events_df.to_csv(RAW_DIR / "events.csv", index=False)
    metric_defs_df.to_csv(RAW_DIR / "metric_definitions.csv", index=False)

    print("\nSummary:")
    print(f"  users:              {len(users_df):,}")
    print(f"  experiments:        {len(experiments_df):,}")
    print(f"  assignments:        {len(assignments_df):,}")
    print(f"  events:             {len(events_df):,}")
    print(f"  metric definitions: {len(metric_defs_df):,}")
    print("\nDone. Raw data is at data/raw/")


if __name__ == "__main__":
    main()
