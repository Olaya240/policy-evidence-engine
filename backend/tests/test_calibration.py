"""Split-conformal prediction sets for the stance decision — ct3 audit workstream 5.

`Decision.confidence` is `abs(score)`, a magnitude of group imbalance. It is not a
frequency, and `ct3/audit/CONFIDENCE-CALIBRATION.md` records where it is read as
one. This file tests the replacement that *is* a frequency claim: a set of stances
with a finite-sample coverage guarantee at a stated `alpha`.

The generator below is the load-bearing assumption, so it is stated rather than
hidden. `synthetic_rows` draws features i.i.d. from a fixed distribution and then
draws the label from a fixed softmax of a fixed linear rule. Successive rows are
independent and identically distributed **by construction**, so the calibration
rows and the evaluation rows are exchangeable, which is exactly the condition the
split-conformal guarantee needs. That is why the coverage numbers below land on
`1 - alpha`: the test verifies the implementation against a world where the
assumption holds. It says nothing about whether the assumption holds for review
evidence, where it need not.

The four claims this file makes, in the order the audit cites them:

1. `test_empirical_coverage_at_three_levels` — measured coverage on held-out rows
   is at least `1 - alpha - 0.02` for `alpha` in {0.05, 0.1, 0.2}, with `n` and the
   achieved coverage printed.
2. `test_set_size_is_monotone_in_alpha` and `test_set_is_never_empty` — sets grow
   as `alpha` shrinks, are nested across levels, and are never empty.
3. `test_evaluating_on_fitted_rows_raises` — `fit` then `evaluate` on the same
   rows raises, because coverage measured there is not coverage.
4. `test_small_calibration_sample_yields_the_full_label_space` — `n < 1/alpha`
   gives the full label space and does not crash.

Run, verbatim (the `-s` matters: the numbers are printed, not asserted away):

    cd /home/alex/policy-evidence-fix/backend && \
      PYTHONPATH=. /home/alex/policy-evidence-latest/.venv/bin/python \
      -m pytest -q -s tests/test_calibration.py
"""

from __future__ import annotations

import math
import random

import pytest

from app.calibration import (
    CalibrationLeakageError,
    ConformalStancePredictor,
    STANCE_LABELS,
    conformal_quantile,
    is_certifiable,
    quantile_rank,
    split_rows,
)
from app.models import Stance

# ---------------------------------------------------------------------------
# The synthetic generator: i.i.d. from a fixed rule, so exchangeable by
# construction. Nothing here is fitted; these are the true data-generating
# parameters, and the score function has to learn them from rows.
# ---------------------------------------------------------------------------

TRUE_WEIGHTS = (
    (1.8, -0.9, 0.3),  # SUPPORTS
    (-1.6, 1.1, -0.2),  # CONTRADICTS
    (-0.2, -0.2, 1.4),  # NEUTRAL
)
TRUE_BIASES = (0.0, 0.0, 0.0)

POOL_SIZE = 3000
EVAL_TOLERANCE = 0.02


def _softmax(values):
    largest = max(values)
    exponentials = [math.exp(value - largest) for value in values]
    total = sum(exponentials)
    return [value / total for value in exponentials]


def synthetic_rows(count, *, seed):
    """`count` i.i.d. `(features, label)` rows from a fixed generating rule.

    The seed fixes the whole stream, so the sample is identical on every run and
    every platform. Independence between rows is what makes the calibration and
    evaluation parts exchangeable; no property of the label rule is doing that
    work, so a different rule would test the same thing.
    """
    rng = random.Random(seed)
    rows = []
    for _ in range(count):
        features = tuple(rng.uniform(-1.0, 1.0) for _ in TRUE_BIASES)
        logits = [
            TRUE_BIASES[index]
            + sum(TRUE_WEIGHTS[index][i] * features[i] for i in range(len(features)))
            for index in range(len(STANCE_LABELS))
        ]
        probabilities = _softmax(logits)
        draw = rng.random()
        cumulative = 0.0
        label = STANCE_LABELS[-1]
        for index, probability in enumerate(probabilities):
            cumulative += probability
            if draw < cumulative:
                label = STANCE_LABELS[index]
                break
        rows.append((features, label))
    return rows


# One pool, split once, so "held out" is a structural fact rather than a comment.
POOL = synthetic_rows(POOL_SIZE, seed=20260601)
FIT_ROWS, EVAL_ROWS = split_rows(POOL, fraction=2 / 3, seed=17)


@pytest.fixture(scope="module")
def predictor():
    """One fit for the whole module: the scored function does not depend on alpha."""
    return ConformalStancePredictor().fit(FIT_ROWS, calibration_fraction=0.5, seed=0)


# ---------------------------------------------------------------------------
# 0. The label space is the stance decision's label space
# ---------------------------------------------------------------------------

def test_label_space_matches_the_stance_enum():
    """`STANCE_LABELS` is kept as plain strings so the module imports without
    pydantic; this pins it to `app.models.Stance` so a fourth stance cannot be
    added without `app/calibration.py` being revisited."""
    assert STANCE_LABELS == tuple(stance.value for stance in Stance)


def test_the_score_function_is_a_distribution_and_is_deterministic(predictor):
    """`p(label | features)` sums to 1 and two fits on the same rows agree
    exactly: no RNG, no shuffling, no early stopping in the fit."""
    probabilities = predictor.predict_proba((0.25, -0.5, 0.1))
    assert set(probabilities) == set(STANCE_LABELS)
    assert all(0.0 <= value <= 1.0 for value in probabilities.values())
    assert math.isclose(sum(probabilities.values()), 1.0, rel_tol=0.0, abs_tol=1e-12)

    again = ConformalStancePredictor().fit(FIT_ROWS[:200], calibration_fraction=0.5, seed=3)
    twice = ConformalStancePredictor().fit(FIT_ROWS[:200], calibration_fraction=0.5, seed=3)
    assert again.predict_proba((0.25, -0.5, 0.1)) == twice.predict_proba((0.25, -0.5, 0.1))


# ---------------------------------------------------------------------------
# 1. Empirical coverage on held-out rows
# ---------------------------------------------------------------------------

def test_empirical_coverage_at_three_levels(predictor):
    """Coverage on rows `fit` never saw is at least `1 - alpha - tolerance`.

    The guarantee is marginal — over the draw of calibration *and* test data — so
    a single evaluation draw can sit slightly below `1 - alpha`; the tolerance is
    the finite-sample slack, not a weakening of the claim. 1000 evaluation rows
    put the standard error of a 0.95 proportion near 0.007, so 0.02 is roughly
    three standard errors.

    `mean_set_size < 3` keeps this from passing trivially: a method that always
    returned the full label space would also cover everything, and would be
    useless. The printout is the table `ct3/audit/CONFORMAL-CALIBRATION.md` cites.
    """
    print()
    print(f"  rows: pool={len(POOL)} fit={len(FIT_ROWS)} held_out={len(EVAL_ROWS)}")
    for alpha in (0.05, 0.1, 0.2):
        report = predictor.evaluate(EVAL_ROWS, alpha)
        print(
            f"  alpha={alpha:<5} n_cal={report.n_calibration:<5} "
            f"n_eval={report.n_evaluated:<5} coverage={report.coverage:.4f} "
            f"target={1 - alpha:.2f} mean_set={report.mean_set_size:.3f} "
            f"max_set={report.max_set_size} quantile={report.quantile:.4f}"
        )

        assert report.full_label_space is False, alpha
        assert report.quantile < math.inf
        assert report.coverage >= (1.0 - alpha) - EVAL_TOLERANCE, (
            alpha,
            report.coverage,
        )
        # Not vacuous: the sets are informative at every level tested.
        assert report.mean_set_size < len(STANCE_LABELS), alpha
        assert report.max_set_size <= len(STANCE_LABELS), alpha


def test_a_higher_alpha_needs_a_smaller_threshold(predictor):
    """The threshold falls as `alpha` rises, which is what makes sets shrink."""
    thresholds = [predictor.conformal_quantile(alpha) for alpha in (0.02, 0.05, 0.1, 0.2, 0.5)]
    assert thresholds == sorted(thresholds, reverse=True)
    assert len(set(thresholds)) == len(thresholds)


# ---------------------------------------------------------------------------
# 2. Set size: monotone in alpha, nested, never empty
# ---------------------------------------------------------------------------

def test_set_size_is_monotone_in_alpha(predictor):
    """Smaller `alpha` (stronger guarantee) never yields a smaller set, per row
    and on average, and at least one level is strictly wider than another."""
    alphas = (0.02, 0.05, 0.1, 0.2, 0.5)
    sizes = {alpha: [] for alpha in alphas}
    for features, _label in EVAL_ROWS:
        for alpha in alphas:
            sizes[alpha].append(len(predictor.predict_set(features, alpha)))

    means = {alpha: sum(values) / len(values) for alpha, values in sizes.items()}
    print()
    for alpha in alphas:
        print(f"  alpha={alpha:<5} mean_set={means[alpha]:.3f}")
    assert all(means[small] >= means[large] for small, large in zip(alphas, alphas[1:]))
    assert means[0.02] > means[0.5], "the levels tested must actually differ"

    # Per row, not just on average: the sets are nested, so this is exact.
    for index, (features, _label) in enumerate(EVAL_ROWS[:200]):
        previous = set(predictor.predict_set(features, alphas[0]))
        for alpha in alphas[1:]:
            current = set(predictor.predict_set(features, alpha))
            assert current <= previous, (index, alpha)
            previous = current


def test_set_is_never_empty(predictor):
    """Every set contains at least one label, at every level, including levels so
    high that the filtered set would be empty without the documented fallback."""
    for features, _label in EVAL_ROWS[:300]:
        for alpha in (0.001, 0.01, 0.05, 0.1, 0.2, 0.5, 0.9):
            prediction = predictor.predict_set(features, alpha)
            assert prediction, (features, alpha)
            assert len(prediction) == len(set(prediction))
            assert set(prediction) <= set(STANCE_LABELS)
            assert set(prediction) == set(
                label for label in STANCE_LABELS if label in prediction
            ), "labels stay in the declared order"


def test_at_least_one_label_survives_at_a_level_above_one_half(predictor):
    """A 50% guarantee should not need the whole label space on a generator the
    score function can partly separate; asserting the bound keeps this honest
    about being a *set* method and not a constant."""
    report = predictor.evaluate(EVAL_ROWS, 0.5)
    assert report.coverage >= 0.5 - EVAL_TOLERANCE
    assert report.mean_set_size < 2.5


# ---------------------------------------------------------------------------
# 3. Refusing to evaluate on the rows it fitted on
# ---------------------------------------------------------------------------

def test_evaluating_on_fitted_rows_raises(predictor):
    """The mistake that makes a coverage number meaningless is reusing the fit
    rows; the API raises instead of reporting an inflated number."""
    with pytest.raises(CalibrationLeakageError) as caught:
        predictor.evaluate(FIT_ROWS, 0.1)
    assert "coverage measured on fitted rows is not a coverage measurement" in str(
        caught.value
    )
    assert isinstance(caught.value, ValueError)


def test_a_single_fitted_row_in_the_evaluation_set_raises(predictor):
    """Contamination is detected per row, not only when the whole list repeats."""
    contaminated = EVAL_ROWS[:50] + [FIT_ROWS[7]]
    with pytest.raises(CalibrationLeakageError):
        predictor.evaluate(contaminated, 0.1)


def test_disjoint_rows_are_accepted(predictor):
    """The guard is not a blanket refusal: rows from the held-out part evaluate."""
    report = predictor.evaluate(EVAL_ROWS[:20], 0.1)
    assert report.n_evaluated == 20


def test_evaluate_before_fit_raises():
    with pytest.raises(ValueError):
        ConformalStancePredictor().evaluate(EVAL_ROWS[:5], 0.1)


def test_split_rows_returns_disjoint_parts():
    """The split the leakage guard leans on is disjoint by construction, and the
    same seed reproduces it."""
    left, right = split_rows(POOL[:10], fraction=0.5, seed=5)
    assert len(left) + len(right) == 10
    assert set(left).isdisjoint(set(right))
    assert split_rows(POOL[:10], fraction=0.5, seed=5) == (left, right)


# ---------------------------------------------------------------------------
# 4. Quantile boundaries
# ---------------------------------------------------------------------------

def test_quantile_is_the_finite_sample_rank():
    """`k = ceil((n + 1)(1 - alpha))`, and the threshold is the k-th smallest."""
    scores = [index / 100.0 for index in range(19)]  # n = 19
    assert quantile_rank(19, 0.1) == 18
    assert conformal_quantile(scores, 0.1) == scores[17]
    assert quantile_rank(19, 0.05) == 19
    assert conformal_quantile(scores, 0.05) == scores[18]
    assert quantile_rank(19, 0.2) == 16
    assert conformal_quantile(scores, 0.2) == scores[15]
    # The threshold is always an observed score, never an interpolation.
    assert conformal_quantile(scores, 0.1) in scores


def test_rank_that_exceeds_n_is_reported_as_infinity():
    """`n < 1/alpha` cannot certify the level; the quantile says so instead of
    extrapolating past the largest observed score."""
    for n, alpha in ((10, 0.05), (8, 0.1), (1, 0.3), (1, 0.5), (4, 0.2)):
        expected_rank = math.ceil((n + 1) * (1.0 - alpha))
        assert quantile_rank(n, alpha) == expected_rank
        if expected_rank > n:
            assert is_certifiable(n, alpha) is False
            scores = [index / 100.0 for index in range(n)]
            assert conformal_quantile(scores, alpha) == math.inf
        else:
            assert is_certifiable(n, alpha) is True


def test_small_calibration_sample_yields_the_full_label_space():
    """A predictor fitted on 8 rows calibrates on 4 of them; at alpha = 0.05 that
    cannot certify anything, so predictions are the full label space and nothing
    crashes."""
    small = synthetic_rows(8, seed=4242)
    fitted = ConformalStancePredictor().fit(small, calibration_fraction=0.5, seed=0)
    assert fitted.n_calibration == 4
    assert fitted.conformal_quantile(0.05) == math.inf

    held_out = synthetic_rows(25, seed=99)
    assert set(held_out).isdisjoint(set(small))
    for features, _label in held_out:
        assert fitted.predict_set(features, 0.05) == STANCE_LABELS

    report = fitted.evaluate(held_out, 0.05)
    assert report.full_label_space is True
    assert report.quantile == math.inf
    assert report.coverage == 1.0
    assert report.mean_set_size == float(len(STANCE_LABELS))


def test_degenerate_alpha_and_empty_calibration_are_refused():
    """`alpha` outside (0, 1) is a caller error, and an empty calibration sample is
    a caller error — not a certified full label space."""
    for alpha in (0.0, 1.0, -0.1, 1.5, float("nan")):
        with pytest.raises(ValueError):
            conformal_quantile([0.1, 0.2], alpha)
        with pytest.raises(ValueError):
            is_certifiable(10, alpha)
    with pytest.raises(ValueError):
        conformal_quantile([], 0.1)
