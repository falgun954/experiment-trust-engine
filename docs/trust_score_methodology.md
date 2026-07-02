# Trust Score Methodology

## The problem this solves

At scale, "the experiment was statistically significant" is not the same
question as "should we act on this result." A result can be significant
and still be wrong to trust because:

- The bucketer is broken (Sample Ratio Mismatch)
- Two teams would compute the headline metric differently and get
  different answers (metric definition drift)
- The effect is real but decaying — a launch decision based on week-1
  data would overstate the long-run impact (novelty effect)
- The "win" quietly broke something else (guardrail regression)
- The experiment never had enough power to detect the effect it claims
  to have found (underpowered)

The Trust Score compresses all five checks into one number so a
non-statistician (a PM, an exec) can see at a glance whether a result is
safe to act on, while a reviewer can drill into exactly which check failed.

## Component weights (100 points total)

| Component | Points | Why this weight |
|---|---|---|
| No SRM | 30 | SRM invalidates randomization entirely — every other number downstream is unreliable if this fails. Highest weight. |
| Metric definition agreement | 25 | If the "same" metric can mean two different things, the result isn't reproducible across teams — a governance failure, not just a stats failure. |
| No guardrail regression | 20 | A win that silently causes harm elsewhere is a real launch risk, not a technicality. |
| Sample size adequacy | 15 | An underpowered "significant" result is often a false positive dressed up as a finding. |
| No novelty effect | 10 | Real but decaying effects are still real — lowest weight because it degrades confidence in *magnitude*, not in whether an effect exists at all. |

## Verdict thresholds

- **TRUST (≥ 85):** No material issues. Safe to make a launch decision on.
- **TRUST WITH CAVEATS (60–84):** At least one real but non-fatal issue.
  Still actionable, but the caveat should travel with the decision (e.g.
  "ship it, but re-validate the guardrail post-launch").
- **DO NOT TRUST (< 60):** Multiple structural problems. The headline
  result should not be used to make a decision without re-running or
  deeply investigating the experiment.

## Why alpha = 0.001 for SRM (not 0.05)

This follows the convention used in published SRM literature from large
experimentation platforms (Microsoft, Booking.com): at company scale,
thousands of experiments run per year, and a 5% false-positive rate on
the SRM check alone would flag a large number of perfectly healthy
experiments, causing alert fatigue. A stricter threshold (0.001) keeps
the check sensitive to genuine bucketing bugs without crying wolf.

## Known limitations (worth stating out loud in an interview)

- The novelty-effect regression uses a simple linear trend on daily lift;
  a production system would likely use a more robust time-series method
  (e.g., a Bayesian state-space model) to avoid false positives from
  day-to-day noise on small experiments.
- The required-sample-size calculation assumes a fixed baseline
  conversion rate and MDE; a production version would pull the
  pre-registered MDE from the experiment design doc rather than a
  hardcoded constant.
- Guardrail "breach" here is a single binary metric; production systems
  typically monitor a portfolio of guardrails with multiple-comparison
  correction.
