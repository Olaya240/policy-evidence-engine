"""Split-conformal prediction sets over the stance decision.

Why a set, and not a number
---------------------------

A claim carries ``Decision.confidence``, which is ``abs(Decision.score)`` — the
magnitude of a group imbalance over independent source groups. Nothing in that
arithmetic is a frequency, so "0.75 confidence" does not mean "right three times
in four", and ``ct3/audit/CONFIDENCE-CALIBRATION.md`` records the cases where it
is read as if it did. A number that has no frequency behind it cannot be turned
into one by relabelling it.

This module does the thing that sentence would need. Instead of a scalar it
returns a *set* of stances, with a guarantee stated in the only currency a finite
sample can pay: with probability at least ``1 - alpha`` over the draw of the
calibration and test data, the set contains the true stance. The set is allowed
to be all three labels; that answer ("I cannot tell") is the honest one and is
representable here, where a single label plus a fake probability is not.

The method, in the standard split-conformal form
------------------------------------------------

1. Fix the label space: the three ``app.models.Stance`` values, in the order
   :data:`STANCE_LABELS` (pinned against the enum by the test file).
2. Hold out a calibration sample disjoint from the data the score function was
   trained on. ``fit`` performs this split itself, with a fixed seed.
3. Define nonconformity ``A(x, y) = 1 - p(y | x)``: how badly the score function
   likes the true label. It is in ``[0, 1 - 1/K]``; lower is better.
4. Compute one nonconformity per calibration row.
5. Take the ``ceil((n + 1) * (1 - alpha)) / n`` empirical quantile of those ``n``
   scores — :func:`conformal_quantile`.
6. At prediction time, keep every label whose nonconformity is at or below that
   quantile. Labels with a small nonconformity are the plausible ones.
7. If the required rank exceeds ``n``, the sample cannot certify the requested
   level at all; the quantile is ``+inf`` and the set is the full label space.

Step 7 is the finite-sample correction and it is the whole point of using
``ceil((n + 1) * (1 - alpha))`` rather than the plain empirical quantile: it pays
for the test point not being in the calibration sample. With ``n = 10`` and
``alpha = 0.05`` the required rank is 11 of 10, so the honest answer is "I cannot
certify 95% from ten examples", not a threshold extrapolated past the largest
observed score.

The score function
------------------

:class:`StanceScoreFunction` is a multinomial logistic regression over the
feature vector, trained by full-batch gradient descent from a zero initialisation:
standardise each feature by the training mean and standard deviation, then
softmax over ``W x + b``. It is deliberately simple and **not tuned**. Conformal
validity does not depend on it — coverage holds for *any* score function, even a
bad one — the model only decides how large the sets are. A better model gives
tighter sets at the same ``alpha``; a worse one gives wider sets. That separation
is the reason to prefer this over a hand-set threshold: the guarantee is a
property of the construction, not of the model's accuracy.

What the guarantee is conditional on
------------------------------------

Exchangeability of the calibration rows and the test row — that they are i.i.d.
draws from one distribution, or at least that their joint distribution is
invariant under permutation. The synthetic generator in the test file satisfies
this by construction, which is exactly why its coverage numbers come out at
``1 - alpha``; real evidence review need not, and ``ct3/audit/CONFORMAL-CALIBRATION.md``
states that limit without softening it.

Labels here are the strings the caller supplies as the second element of a row.
That is what makes the audit blunt rather than decorative: if those labels are
written by an agent rather than a human reviewer, the set is guaranteed to cover
the *agent's* label, which is not the domain's truth.

Stdlib only: no numpy, no scipy, no sklearn. Quantiles are computed here.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

# The stance label space, in the order `app.models.Stance` declares its members.
# Kept as plain strings so this module imports without pydantic and can be
# exercised on its own; `tests/test_calibration.py` pins the correspondence, so a
# fourth stance cannot appear in the API without this module being revisited.
STANCE_LABELS: tuple[str, ...] = ("SUPPORTS", "CONTRADICTS", "NEUTRAL")


class CalibrationLeakageError(ValueError):
    """Raised when rows used to fit are also used to measure coverage.

    A coverage number computed on fitted rows is not a coverage number: the
    quantile was chosen to fit those rows, so the measurement can only go up.
    This is the failure the rest of the module exists to make impossible to do by
    accident, so it is an exception rather than a warning.
    """


class NotFittedError(ValueError):
    """Raised when a prediction or evaluation is attempted before ``fit``."""


# ---------------------------------------------------------------------------
# Finite-sample quantile
# ---------------------------------------------------------------------------


def quantile_rank(n: int, alpha: float) -> int:
    """Rank ``k = ceil((n + 1) * (1 - alpha))``, or ``n + 1`` when uncertifiable.

    ``k`` is the position (1-based) of the threshold in the sorted calibration
    scores. ``k > n`` means the requested level cannot be certified from ``n``
    rows; the returned ``n + 1`` is the signal for that, not a value to read from
    the sample.

    The arithmetic is done in float, as ``alpha`` arrives as a float. A rounding
    at an exact boundary can only *raise* ``k`` by one, which enlarges the set and
    therefore preserves the guarantee; it can never break it.
    """
    _check_alpha(alpha)
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    return math.ceil((n + 1) * (1.0 - alpha))


def conformal_quantile(scores: Sequence[float], alpha: float) -> float:
    """The split-conformal threshold at level ``alpha``.

    With ``n = len(scores)`` and ``k = ceil((n + 1) * (1 - alpha))``, this is the
    empirical ``k / n`` quantile: the ``k``-th smallest score. Returns
    ``math.inf`` when ``k > n``.

    ``inf`` is not a large number to be clamped against. It means **the prediction
    set is the full label space**: ``n`` is too small for the requested level, and
    no threshold from this sample can be extrapolated to cover a new point with
    probability ``1 - alpha``. Callers must check :func:`is_certifiable` (or
    ``math.isinf``) and report the full set, rather than substituting the largest
    observed score — which would silently under-cover.
    """
    _check_alpha(alpha)
    ordered = sorted(float(score) for score in scores)
    n = len(ordered)
    if n == 0:
        raise ValueError(
            "conformal_quantile needs at least one calibration score; an empty "
            "sample is a caller error, not a certified full label space"
        )
    k = quantile_rank(n, alpha)
    if k > n:
        return math.inf
    return ordered[k - 1]


def is_certifiable(n: int, alpha: float) -> bool:
    """Whether ``n`` calibration rows can certify level ``alpha`` at all.

    False exactly when ``ceil((n + 1) * (1 - alpha)) > n``, i.e. ``alpha < 1 / (n + 1)``.
    """
    return quantile_rank(n, alpha) <= n


def _check_alpha(alpha: float) -> None:
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise ValueError(f"alpha must be a float in (0, 1), got {alpha!r}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(
            f"alpha must be in (0, 1), got {alpha!r}; alpha = 0 asks for a "
            "guarantee no finite sample can certify, and is refused rather than "
            "silently answered with the full label space"
        )


# ---------------------------------------------------------------------------
# Score function: multinomial logistic regression, stdlib only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StanceScoreFunction:
    """``p(label | features)`` as a softmax over a linear model.

    Fields are the fitted parameters, so the object is immutable and two fits on
    the same rows compare equal. ``probabilities`` standardises with the stored
    training mean and scale before applying the weights, so the caller passes raw
    feature vectors in the same units it trained with.
    """

    mean: tuple[float, ...]
    scale: tuple[float, ...]
    weights: tuple[tuple[float, ...], ...]  # one row per label
    biases: tuple[float, ...]
    labels: tuple[str, ...] = STANCE_LABELS

    @classmethod
    def fit(
        cls,
        rows: Sequence[tuple[Sequence[float], str]],
        *,
        iterations: int = 400,
        learning_rate: float = 0.5,
        labels: tuple[str, ...] = STANCE_LABELS,
    ) -> "StanceScoreFunction":
        """Full-batch gradient descent on mean cross-entropy, zero-initialised.

        No RNG, no shuffling, no early stopping: the same rows give the same
        parameters on every run and every platform. Zero initialisation is safe
        because the class frequencies and the per-row errors break the symmetry
        on the first step.
        """
        if not rows:
            raise ValueError("StanceScoreFunction.fit needs at least one row")
        if iterations < 1:
            raise ValueError(f"iterations must be >= 1, got {iterations}")
        if not 0.0 < learning_rate < 1.0:
            raise ValueError(f"learning_rate must be in (0, 1), got {learning_rate}")

        parsed = _parse_rows(rows, labels)
        dimension = len(parsed[0][0])
        features = [row[0] for row in parsed]

        mean = tuple(
            sum(vector[i] for vector in features) / len(features)
            for i in range(dimension)
        )
        scale = []
        for i in range(dimension):
            variance = sum((vector[i] - mean[i]) ** 2 for vector in features) / len(features)
            deviation = math.sqrt(variance)
            # A constant feature carries no information; a scale of 0 would divide
            # by zero, and a scale of 1 leaves that column at zero after centring,
            # which is the correct contribution for it to make.
            scale.append(deviation if deviation > 0.0 else 1.0)
        scale_tuple = tuple(scale)

        standardised = [
            tuple((vector[i] - mean[i]) / scale_tuple[i] for i in range(dimension))
            for vector in features
        ]

        k = len(labels)
        weights = [[0.0] * dimension for _ in range(k)]
        biases = [0.0] * k
        count = len(standardised)

        for _ in range(iterations):
            grad_w = [[0.0] * dimension for _ in range(k)]
            grad_b = [0.0] * k
            for vector, label_index in zip(standardised, (row[1] for row in parsed)):
                probabilities = _softmax(
                    [
                        biases[j]
                        + sum(weights[j][i] * vector[i] for i in range(dimension))
                        for j in range(k)
                    ]
                )
                for j in range(k):
                    error = probabilities[j] - (1.0 if j == label_index else 0.0)
                    if error == 0.0:
                        continue
                    row_grad = grad_w[j]
                    for i in range(dimension):
                        row_grad[i] += error * vector[i]
                    grad_b[j] += error
            for j in range(k):
                biases[j] -= learning_rate * grad_b[j] / count
                for i in range(dimension):
                    weights[j][i] -= learning_rate * grad_w[j][i] / count

        return cls(
            mean=mean,
            scale=scale_tuple,
            weights=tuple(tuple(row) for row in weights),
            biases=tuple(biases),
            labels=labels,
        )

    @property
    def dimension(self) -> int:
        return len(self.mean)

    def logits(self, features: Sequence[float]) -> tuple[float, ...]:
        """``W x + b`` for the given raw feature vector."""
        vector = self._standardise(features)
        return tuple(
            self.biases[j]
            + sum(self.weights[j][i] * vector[i] for i in range(self.dimension))
            for j in range(len(self.labels))
        )

    def probabilities(self, features: Sequence[float]) -> dict[str, float]:
        """``p(label | features)``, normalised to sum to 1."""
        values = _softmax(self.logits(features))
        return dict(zip(self.labels, values))

    def nonconformity(self, features: Sequence[float], label: str) -> float:
        """``1 - p(label | features)`` — the split-conformal score."""
        if label not in self.labels:
            raise ValueError(f"unknown label {label!r}; expected one of {self.labels}")
        return 1.0 - self.probabilities(features)[label]

    def _standardise(self, features: Sequence[float]) -> tuple[float, ...]:
        values = _parse_features(features, self.dimension)
        return tuple(
            (values[i] - self.mean[i]) / self.scale[i] for i in range(self.dimension)
        )


def _softmax(logits: Sequence[float]) -> list[float]:
    """Numerically stable softmax (subtract the max before exponentiating)."""
    largest = max(logits)
    exponentials = [math.exp(value - largest) for value in logits]
    total = sum(exponentials)
    return [value / total for value in exponentials]


# ---------------------------------------------------------------------------
# Row handling and the split
# ---------------------------------------------------------------------------


Row = tuple[tuple[float, ...], str]


def _parse_features(
    features: Sequence[float], dimension: int | None = None
) -> tuple[float, ...]:
    if isinstance(features, (str, bytes)):
        raise ValueError("features must be a sequence of numbers, not a string")
    try:
        values = tuple(float(value) for value in features)
    except (TypeError, ValueError) as error:
        raise ValueError(f"features must be a sequence of numbers: {error}") from error
    if not values:
        raise ValueError("features must be non-empty")
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"features must all be finite, got {values}")
    if dimension is not None and len(values) != dimension:
        raise ValueError(
            f"expected {dimension} features, got {len(values)}: {values}"
        )
    return values


def _parse_rows(
    rows: Iterable[tuple[Sequence[float], str]],
    labels: tuple[str, ...],
) -> list[tuple[tuple[float, ...], int]]:
    parsed: list[tuple[tuple[float, ...], int]] = []
    dimension: int | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise ValueError(f"row {index} must be a (features, label) pair, got {row!r}")
        features, label = row
        values = _parse_features(features, dimension)
        dimension = len(values)
        if label not in labels:
            # Refused, not dropped: a row with a label outside the label space has
            # no nonconformity, and silently skipping it would change n — and
            # therefore the guarantee — without saying so.
            raise ValueError(
                f"row {index} has label {label!r}, which is not in the label space {labels}"
            )
        parsed.append((values, labels.index(label)))
    return parsed


def split_rows(
    rows: Sequence[Row],
    *,
    fraction: float = 0.5,
    seed: int = 0,
) -> tuple[list[Row], list[Row]]:
    """Deterministically split ``rows`` into ``(part_a, part_b)``.

    ``part_a`` has ``round(len(rows) * fraction)`` rows, clamped to leave at least
    one row in each part. The shuffle is ``random.Random(seed)``, whose Mersenne
    Twister stream is stable across runs and platforms for a given seed, so the
    split is reproducible; it is not a claim of statistical randomness.

    The point of this function is that the two parts are disjoint by construction,
    so a caller cannot accidentally calibrate on the rows it measures coverage on.
    """
    total = len(rows)
    if total < 2:
        raise ValueError(
            f"need at least 2 rows to split, got {total}: one for the score "
            "function and one to calibrate against"
        )
    if not 0.0 < fraction < 1.0:
        raise ValueError(f"fraction must be in (0, 1), got {fraction}")

    size_a = round(total * fraction)
    size_a = min(max(size_a, 1), total - 1)

    order = list(range(total))
    random.Random(seed).shuffle(order)
    chosen = set(order[:size_a])
    part_a = [rows[index] for index in range(total) if index in chosen]
    part_b = [rows[index] for index in range(total) if index not in chosen]
    return part_a, part_b


# ---------------------------------------------------------------------------
# The predictor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationReport:
    """Coverage measured on rows the fit never saw.

    ``quantile`` is ``inf`` and ``full_label_space`` is True when ``alpha`` was
    too small for the calibration sample; a coverage of 1.0 in that case is
    guaranteed by the trivial set, not by the method, and the flag says so.
    """

    alpha: float
    n_calibration: int
    n_evaluated: int
    coverage: float
    mean_set_size: float
    max_set_size: int
    quantile: float
    full_label_space: bool


class ConformalStancePredictor:
    """Split-conformal prediction sets over the stance decision.

    ``fit(rows)`` does two things with the rows it is given, in this order:

    1. split them with :func:`split_rows`, using ``calibration_fraction`` and
       ``seed``;
    2. train :class:`StanceScoreFunction` on one part and take the nonconformity
       of every row in the other part as the calibration sample.

    Splitting inside ``fit`` is what keeps the quantile out-of-sample for the
    score function. Calibrating on the rows the model was trained on would make
    the calibration scores optimistically small, the threshold too tight, and the
    coverage claim false — the same error one level up from evaluating on fitted
    rows, which :meth:`evaluate` refuses outright.

    ``fit`` records every row it was given, so :meth:`evaluate` can refuse to
    measure coverage on any of them.
    """

    def __init__(
        self,
        *,
        labels: tuple[str, ...] = STANCE_LABELS,
        iterations: int = 400,
        learning_rate: float = 0.5,
    ) -> None:
        if len(labels) < 2:
            raise ValueError(f"a prediction set needs at least 2 labels, got {labels}")
        if len(set(labels)) != len(labels):
            raise ValueError(f"labels must be distinct, got {labels}")
        self.labels = tuple(labels)
        self.iterations = iterations
        self.learning_rate = learning_rate
        self._score_function: StanceScoreFunction | None = None
        self._calibration_scores: tuple[float, ...] = ()
        self._fit_keys: frozenset[tuple[tuple[float, ...], str]] = frozenset()
        self._n_training_rows = 0

    # -- fitting ----------------------------------------------------------

    def fit(
        self,
        rows: Sequence[Row],
        *,
        calibration_fraction: float = 0.5,
        seed: int = 0,
    ) -> "ConformalStancePredictor":
        """Train the score function and take the calibration scores."""
        if not rows:
            raise ValueError("fit needs at least one row")
        keys = frozenset(_row_key(row, self.labels) for row in rows)
        calibration_rows, training_rows = split_rows(
            rows, fraction=calibration_fraction, seed=seed
        )
        self._score_function = StanceScoreFunction.fit(
            training_rows,
            iterations=self.iterations,
            learning_rate=self.learning_rate,
            labels=self.labels,
        )
        self._calibration_scores = tuple(
            self._score_function.nonconformity(features, label)
            for features, label in calibration_rows
        )
        self._fit_keys = keys
        self._n_training_rows = len(training_rows)
        return self

    # -- prediction -------------------------------------------------------

    @property
    def fitted(self) -> bool:
        return self._score_function is not None

    @property
    def score_function(self) -> StanceScoreFunction:
        if self._score_function is None:
            raise NotFittedError("call fit(rows) before using the predictor")
        return self._score_function

    @property
    def n_calibration(self) -> int:
        return len(self._calibration_scores)

    @property
    def n_training(self) -> int:
        return self._n_training_rows

    def conformal_quantile(self, alpha: float) -> float:
        """The threshold for ``alpha``, from this predictor's calibration scores."""
        if self._score_function is None:
            raise NotFittedError("call fit(rows) before asking for a quantile")
        return conformal_quantile(self._calibration_scores, alpha)

    def predict_proba(self, features: Sequence[float]) -> dict[str, float]:
        """The point distribution the score function assigns; not a guarantee."""
        return self.score_function.probabilities(features)

    def predict_set(self, features: Sequence[float], alpha: float) -> tuple[str, ...]:
        """Labels whose nonconformity is within the conformal quantile.

        The set is

            { y : 1 - p(y | x) <= quantile }  union  { argmax_y p(y | x) }

        and the second term is not decoration. With this score the filtered set
        *can* be empty — a test point the model finds uniformly implausible has
        minimum nonconformity above a small quantile — and an empty set is not a
        prediction. Including the model's best guess makes the set non-empty by
        construction. It changes nothing when the filtered set is already
        non-empty, because the argmax label has the smallest nonconformity of any
        label and so is already in it; and it cannot lower coverage, since adding
        a label never removes the true one. Because the added term does not depend
        on ``alpha``, the nested-ness in ``alpha`` survives too.

        When the quantile is ``inf`` every label is returned.
        """
        quantile = self.conformal_quantile(alpha)
        probabilities = self.score_function.probabilities(features)
        return self._predict_set_at(probabilities, quantile)

    def _predict_set_at(
        self, probabilities: dict[str, float], quantile: float
    ) -> tuple[str, ...]:
        """`predict_set` with the threshold already computed.

        `evaluate` measures many rows at one `alpha`; sorting the calibration scores
        once instead of once per row is the difference between `O(n log n)` and
        `O(n^2 log n)` for a coverage table.
        """
        if math.isinf(quantile):
            return self.labels
        kept = tuple(
            label for label in self.labels if 1.0 - probabilities[label] <= quantile
        )
        if kept:
            return kept
        best = max(self.labels, key=lambda label: probabilities[label])
        return (best,)

    def set_size(self, features: Sequence[float], alpha: float) -> int:
        return len(self.predict_set(features, alpha))

    # -- evaluation -------------------------------------------------------

    def evaluate(self, rows: Sequence[Row], alpha: float) -> EvaluationReport:
        """Measure empirical coverage on rows ``fit`` never saw.

        Raises :class:`CalibrationLeakageError` if any row passed here was also
        passed to :meth:`fit`, in either part of the internal split. The check is
        by value — the feature tuple and the label — so it catches the mistake of
        re-using the same list, and cannot catch a re-generated copy of the same
        data. It is a guard against accidental leakage, not provenance tracking.
        """
        if self._score_function is None:
            raise NotFittedError("call fit(rows) before evaluating")
        _check_alpha(alpha)
        if not rows:
            raise ValueError("evaluate needs at least one row")

        leaked = [
            row
            for row in rows
            if _row_key(row, self.labels) in self._fit_keys
        ]
        if leaked:
            raise CalibrationLeakageError(
                f"{len(leaked)} of {len(rows)} evaluation rows were used to fit "
                "this predictor; coverage measured on fitted rows is not a "
                "coverage measurement. Split the data first and evaluate on the "
                "part fit never saw."
            )

        quantile = self.conformal_quantile(alpha)
        covered = 0
        sizes: list[int] = []
        for features, label in rows:
            prediction = self._predict_set_at(
                self.score_function.probabilities(features), quantile
            )
            sizes.append(len(prediction))
            if label in prediction:
                covered += 1

        return EvaluationReport(
            alpha=alpha,
            n_calibration=self.n_calibration,
            n_evaluated=len(rows),
            coverage=covered / len(rows),
            mean_set_size=sum(sizes) / len(sizes),
            max_set_size=max(sizes),
            quantile=quantile,
            full_label_space=math.isinf(quantile),
        )


def _row_key(row: Sequence[object], labels: tuple[str, ...]) -> tuple[tuple[float, ...], str]:
    """Canonical, hashable form of a row, used only for the leakage check."""
    features, label = row
    values = _parse_features(features)
    if label not in labels:
        raise ValueError(f"label {label!r} is not in the label space {labels}")
    return values, label
