"""
Statistical engine for the Experiment Trust Engine.

This module is the "why trust this result" layer. It is intentionally kept
independent of pandas plumbing so each function is a pure, testable
statistical primitive — this is also what gets mirrored 1:1 in DAX
(see dax/measures.md) so the Power BI report and this Python module always
agree on methodology.

Functions
---------
srm_chi_square(control_n, treatment_n, expected_ratio=0.5)
    Detects Sample Ratio Mismatch via a chi-square goodness-of-fit test.

two_proportion_ztest(control_conversions, control_n, treatment_conversions, treatment_n)
    Standard two-proportion z-test with confidence interval on the lift.

novelty_effect_score(daily_lift_series)
    Quantifies whether treatment lift is decaying over time (novelty effect)
    by regressing lift against days-since-start.

trust_score(...)
    Composite 0-100 score combining SRM health, metric-definition agreement,
    guardrail health, and sample size adequacy.
"""

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class SRMResult:
    chi_square: float
    p_value: float
    is_srm: bool
    observed_ratio: float


def srm_chi_square(control_n: int, treatment_n: int, expected_ratio: float = 0.5,
                    alpha: float = 0.001) -> SRMResult:
    """
    Sample Ratio Mismatch test.

    Uses alpha=0.001 (not 0.05) by convention in the experimentation
    industry (see Microsoft/Booking.com SRM papers) because a 5% false
    positive rate would flag a huge fraction of healthy experiments given
    how many are run.
    """
    total = control_n + treatment_n
    expected_control = total * expected_ratio
    expected_treatment = total * (1 - expected_ratio)

    chi_sq = ((control_n - expected_control) ** 2 / expected_control +
              (treatment_n - expected_treatment) ** 2 / expected_treatment)
    p_value = 1 - stats.chi2.cdf(chi_sq, df=1)

    return SRMResult(
        chi_square=round(chi_sq, 4),
        p_value=round(p_value, 6),
        is_srm=p_value < alpha,
        observed_ratio=round(treatment_n / total, 4),
    )


@dataclass
class ZTestResult:
    control_rate: float
    treatment_rate: float
    absolute_lift: float
    relative_lift_pct: float
    z_stat: float
    p_value: float
    ci_lower: float
    ci_upper: float
    is_significant: bool


def two_proportion_ztest(control_conversions: int, control_n: int,
                          treatment_conversions: int, treatment_n: int,
                          alpha: float = 0.05) -> ZTestResult:
    p1 = control_conversions / control_n
    p2 = treatment_conversions / treatment_n
    p_pool = (control_conversions + treatment_conversions) / (control_n + treatment_n)

    se_pool = np.sqrt(p_pool * (1 - p_pool) * (1 / control_n + 1 / treatment_n))
    z = (p2 - p1) / se_pool if se_pool > 0 else 0.0
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))

    # CI on the absolute difference using unpooled SE (standard approach for CIs)
    se_diff = np.sqrt(p1 * (1 - p1) / control_n + p2 * (1 - p2) / treatment_n)
    z_crit = stats.norm.ppf(1 - alpha / 2)
    diff = p2 - p1
    ci_lower = diff - z_crit * se_diff
    ci_upper = diff + z_crit * se_diff

    return ZTestResult(
        control_rate=round(p1, 5),
        treatment_rate=round(p2, 5),
        absolute_lift=round(diff, 5),
        relative_lift_pct=round((diff / p1) * 100, 3) if p1 > 0 else 0.0,
        z_stat=round(z, 4),
        p_value=round(p_value, 6),
        ci_lower=round(ci_lower, 5),
        ci_upper=round(ci_upper, 5),
        is_significant=p_value < alpha,
    )


def novelty_effect_score(day_indices: np.ndarray, daily_lift: np.ndarray) -> dict:
    """
    Fits daily treatment lift ~ day_index. A meaningfully negative slope
    relative to the average lift indicates the effect is decaying
    (novelty effect) rather than being a stable, trustworthy treatment
    effect.
    """
    if len(day_indices) < 3 or np.all(daily_lift == daily_lift[0]):
        return dict(slope=0.0, decay_pct=0.0, is_novelty_effect=False)

    slope, intercept, r_value, p_value, std_err = stats.linregress(day_indices, daily_lift)
    avg_lift = np.mean(daily_lift)
    # Decay expressed as % of average lift lost per day
    decay_pct = (abs(slope) / abs(avg_lift) * 100) if avg_lift != 0 else 0.0

    return dict(
        slope=round(float(slope), 6),
        r_squared=round(float(r_value ** 2), 4),
        p_value=round(float(p_value), 6),
        decay_pct_per_day=round(float(decay_pct), 3),
        is_novelty_effect=(slope < 0 and p_value < 0.05 and decay_pct > 2.0),
    )


def trust_score(srm: SRMResult, definition_agreement_pct: float,
                 guardrail_breached: bool, sample_size_adequate: bool,
                 novelty_detected: bool) -> dict:
    """
    Composite 0-100 Trust Score. Weights are documented in
    docs/trust_score_methodology.md — this is the single artifact meant to
    answer "should a decision-maker act on this experiment's result?"

    Components (100 pts total):
      - 30 pts: no SRM
      - 25 pts: metric definitions agree (>=90% => full credit, scaled below that)
      - 20 pts: no guardrail regression
      - 15 pts: sample size adequate for claimed effect size
      - 10 pts: no unresolved novelty effect
    """
    score = 0
    reasons = []

    if not srm.is_srm:
        score += 30
    else:
        reasons.append(f"SRM detected (p={srm.p_value}) — assignment is not trustworthy")

    def_score = min(definition_agreement_pct, 100) / 100 * 25
    score += def_score
    if definition_agreement_pct < 90:
        reasons.append(f"Metric definitions only agree {definition_agreement_pct:.1f}% of the time")

    if not guardrail_breached:
        score += 20
    else:
        reasons.append("Guardrail metric regressed in treatment")

    if sample_size_adequate:
        score += 15
    else:
        reasons.append("Sample size below the pre-registered minimum detectable effect threshold")

    if not novelty_detected:
        score += 10
    else:
        reasons.append("Treatment effect is decaying over time (novelty effect)")

    score = round(score, 1)
    if score >= 85:
        verdict = "TRUST"
    elif score >= 60:
        verdict = "TRUST WITH CAVEATS"
    else:
        verdict = "DO NOT TRUST"

    return dict(trust_score=score, verdict=verdict, reasons=reasons)
