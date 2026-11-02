"""Label boundaries of the signed decision table.

The module claims the label rule is the one proved in ``ct3/DecisionTable.v``.
These tests pin the arithmetic at the boundaries where the proof and the code
could drift, and they pin the one asymmetry a reader is most likely to "fix":
``contradicted s c := 3*s + 1 <= c`` has no minimum-group bound, while
``supported`` requires ``2 <= s`` (``DecisionTable.v:120-122``).
"""

from __future__ import annotations

import pytest

from app.decision_table import (
    POLICY_CONTEST_BLOCKS,
    POLICY_SIGNED_MARGIN,
    POLICY_TWO_TO_ONE,
    decide,
    score,
)
from app.models import Status


@pytest.mark.parametrize(
    ("s", "c", "expected"),
    [
        (2, 0, Status.SUPPORTED),  # minimum groups met, margin 2 >= 3*0 + 1
        (1, 0, Status.PARTIAL),  # one source is never decisive
        (3, 1, Status.PARTIAL),  # 3 < 3*1 + 1, so the margin is not there
        (4, 1, Status.SUPPORTED),
        (2, 1, Status.PARTIAL),
        (0, 0, Status.INSUFFICIENT),
    ],
)
def test_supported_boundaries(s, c, expected):
    assert decide(s, c).status is expected


@pytest.mark.parametrize(
    ("s", "c", "expected"),
    [
        (0, 1, Status.CONTRADICTED),  # deliberate: refutation needs no minimum
        (0, 2, Status.CONTRADICTED),
        (1, 4, Status.CONTRADICTED),
        (1, 3, Status.PARTIAL),
        (1, 1, Status.PARTIAL),
    ],
)
def test_contradicted_boundaries(s, c, expected):
    assert decide(s, c).status is expected


def test_a_single_contradiction_is_decisive_while_a_single_support_is_not():
    """Asymmetry by design, and the Coq model has it too (DecisionTable.v:120-122)."""
    assert decide(1, 0).status is Status.PARTIAL
    assert decide(0, 1).status is Status.CONTRADICTED


def test_labels_are_exclusive_over_the_small_grid():
    for s in range(7):
        for c in range(7):
            decision = decide(s, c)
            assert not (
                decision.status is Status.SUPPORTED
                and decision.status is Status.CONTRADICTED
            )
            assert -1.0 <= decision.score <= 1.0
            assert decision.confidence == abs(decision.score)


def test_score_is_antisymmetric_and_zero_on_a_balanced_contest():
    for s in range(6):
        for c in range(6):
            assert score(s, c) == -score(c, s)
    assert score(0, 0) == 0
    assert score(3, 3) == 0


def test_score_rejects_negative_counts():
    with pytest.raises(ValueError):
        score(-1, 0)
    with pytest.raises(ValueError):
        score(0, -1)


def test_one_more_support_group_strictly_raises_the_score():
    for s in range(6):
        for c in range(6):
            assert score(s + 1, c) > score(s, c)


def test_the_two_named_policies_are_not_the_shipped_rule():
    """The module only proves POLICY_SIGNED_MARGIN; the others must differ visibly."""
    assert decide(1, 0, policy=POLICY_TWO_TO_ONE).status is Status.SUPPORTED
    assert decide(1, 0, policy=POLICY_SIGNED_MARGIN).status is Status.PARTIAL

    # A contested claim is never decisive under the blocking policy.
    assert decide(2, 1, policy=POLICY_SIGNED_MARGIN).status is Status.PARTIAL
    assert decide(2, 1, policy=POLICY_CONTEST_BLOCKS).status is Status.PARTIAL
    assert decide(3, 1, policy=POLICY_SIGNED_MARGIN).status is Status.PARTIAL
    assert decide(3, 1, policy=POLICY_CONTEST_BLOCKS).status is Status.PARTIAL
