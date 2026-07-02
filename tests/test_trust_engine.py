"""
Unit tests for src/stats/trust_engine.py.

Run: pytest tests/ -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stats.trust_engine import (
    novelty_effect_score,
    srm_chi_square,
    trust_score,
    two_proportion_ztest,
)


class TestSRM:
    def test_balanced_allocation_is_not_srm(self):
        result = srm_chi_square(control_n=10000, treatment_n=10005)
        assert result.is_srm is False

    def test_obvious_bias_is_srm(self):
        result = srm_chi_square(control_n=8000, treatment_n=12000)
        assert result.is_srm is True
        assert result.p_value < 0.001

    def test_observed_ratio_computed_correctly(self):
        result = srm_chi_square(control_n=5000, treatment_n=5000)
        assert result.observed_ratio == pytest.approx(0.5, abs=1e-6)


class TestZTest:
    def test_identical_rates_not_significant(self):
        result = two_proportion_ztest(1000, 10000, 1000, 10000)
        assert result.is_significant is False
        assert result.absolute_lift == pytest.approx(0.0, abs=1e-9)

    def test_large_true_lift_is_significant(self):
        result = two_proportion_ztest(1000, 10000, 1500, 10000)
        assert result.is_significant is True
        assert result.absolute_lift > 0

    def test_confidence_interval_contains_point_estimate(self):
        result = two_proportion_ztest(800, 10000, 1000, 10000)
        assert result.ci_lower <= result.absolute_lift <= result.ci_upper


class TestNoveltyEffect:
    def test_flat_lift_is_not_novelty(self):
        days = np.arange(10)
        lift = np.full(10, 0.05)
        result = novelty_effect_score(days, lift)
        assert result["is_novelty_effect"] is False

    def test_decaying_lift_is_novelty(self):
        days = np.arange(14)
        lift = 0.10 * np.exp(-0.3 * days)
        result = novelty_effect_score(days, lift)
        assert result["is_novelty_effect"] is True
        assert result["slope"] < 0


class TestTrustScore:
    def test_clean_experiment_scores_100(self):
        from stats.trust_engine import SRMResult
        clean_srm = SRMResult(chi_square=0.1, p_value=0.9, is_srm=False, observed_ratio=0.5)
        result = trust_score(
            srm=clean_srm, definition_agreement_pct=100.0,
            guardrail_breached=False, sample_size_adequate=True, novelty_detected=False,
        )
        assert result["trust_score"] == 100.0
        assert result["verdict"] == "TRUST"

    def test_srm_plus_guardrail_scores_low(self):
        from stats.trust_engine import SRMResult
        bad_srm = SRMResult(chi_square=50.0, p_value=0.00001, is_srm=True, observed_ratio=0.6)
        result = trust_score(
            srm=bad_srm, definition_agreement_pct=100.0,
            guardrail_breached=True, sample_size_adequate=True, novelty_detected=True,
        )
        assert result["trust_score"] < 60
        assert result["verdict"] == "DO NOT TRUST"
        assert len(result["reasons"]) == 3  # SRM, guardrail, novelty

    def test_reasons_list_empty_when_clean(self):
        from stats.trust_engine import SRMResult
        clean_srm = SRMResult(chi_square=0.1, p_value=0.9, is_srm=False, observed_ratio=0.5)
        result = trust_score(
            srm=clean_srm, definition_agreement_pct=95.0,
            guardrail_breached=False, sample_size_adequate=True, novelty_detected=False,
        )
        assert result["reasons"] == []
