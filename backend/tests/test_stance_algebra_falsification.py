"""Falsification of the clause-verdict stance algebra.

The rest of the algebra's tests prove things *about the model*: that
``compose`` is associative and commutative, that an abstention composed with a
direction leaves the direction alone, that the carrier is closed. Those proofs
are about clause verdicts. This file attacks the assumption underneath them —
that a sentence's meaning can be split into clause verdicts at all — and
measures what the guard does on sentences it was not written against.

Three groups of checks:

1. A deterministic generative search over 20 000 sentences built from the
   guard's own cue inventory (imported at runtime, never copied), with nine
   scope-operator classes. For each sentence the intended polarity is known by
   construction, so the guard's verdict can be scored, not just described.
   Four invariants are checked on the same set: determinism, order independence
   under clause permutation, idempotence under clause repetition, and
   ``ABSTAIN_INFO`` as a composition identity.

2. A measurement. What fraction of the 20 000 sentences the guard commits a
   direction on, and how many of those commits are wrong by construction. The
   always-abstain baseline is reported on the same set.

3. Three minimal counterexamples the algebra cannot express, each a
   characterisation test: it asserts what the guard does today, and the
   docstring says why that is wrong. Comments marked ``FALSIFIED`` are the
   findings; see ``ct3/audit/ALGEBRA-FALSIFICATION.md``.

Nothing in this file changes guard behaviour. Rename an assertion here only
after reading the audit note that justifies it.
"""



from __future__ import annotations
import pytest

import itertools
import random
from collections import Counter

from app import stance_algebra
from app.models import Stance
from app.semantic_guard import _CUES, reviewed_relation_details

SEED = 20261102
N_SAMPLE = 20000
MIN_SAMPLE = 20000

# Scope-neutral lead-ins. Each is a plain time/place/attribution adverbial, so
# it does not change whether the clause it sits in is asserted.
LEADS = [
    "",
    "At the ward round, ",
    "During the handover, ",
    "According to the record, ",
    "On the night shift, ",
    "At 03:40, ",
    "In the handover folder, ",
    "After the audit, ",
]

# Scope-neutral trailing coordinates. Same rule: adds a clause, asserts nothing
# about the hypothesis under test.
TAILS = [
    "",
    ", and the shift ended on time",
    ", and the ward was quiet",
    " as the night log records",
    ", and the binder stayed on the desk",
]

# (operator class, sentence template, intended status)
#   "DIRECTION" -> the sentence asserts the cue, so the cue's stance is the
#                  only defensible committed answer.
#   "ABSTAIN"   -> the sentence does not assert the cue, so any committed
#                  direction is wrong by construction.
# Every template is ordinary English for its class; none is a trick form. The
# trick forms are in group 3, kept out of the measurement on purpose.
TEMPLATES = [
    ("PLAIN", "{cue}", "DIRECTION"),
    ("PLAIN", "The note states {cue}", "DIRECTION"),
    ("NEGATION", "It is not true that {cue}", "ABSTAIN"),
    ("NEGATION", "It was not the case that {cue}", "ABSTAIN"),
    ("HEDGE", "Perhaps {cue}", "ABSTAIN"),
    ("HEDGE", "It is possible that {cue}", "ABSTAIN"),
    # A postposed hedge: the operator scopes over the clause to its left.
    ("HEDGE", "The auditor said {cue}, probably", "ABSTAIN"),
    ("QUESTION", "Did anyone ask whether {cue}", "ABSTAIN"),
    ("QUESTION", "Is it true that {cue}", "ABSTAIN"),
    ("CONDITIONAL", "If {cue}, the team should have escalated", "ABSTAIN"),
    ("CONDITIONAL", "Unless {cue}, the audit continued as planned", "ABSTAIN"),
    ("EVIDENCE_ABOUTNESS", "No evidence shows {cue}", "ABSTAIN"),
    ("QUANTIFIER", "No one confirmed that {cue}", "ABSTAIN"),
    ("QUANTIFIER", "Nobody had checked whether {cue}", "ABSTAIN"),
    ("QUANTIFIER", "None of the staff reported that {cue}", "ABSTAIN"),
    ("EVIDENTIAL", "The auditor confirmed that {cue}", "DIRECTION"),
    ("EVIDENTIAL", "The note recorded that {cue}", "DIRECTION"),
    ("CONTRAST", "{cue}, but the ward was quiet", "DIRECTION"),
    ("CONTRAST", "The ward was quiet, but {cue}", "DIRECTION"),
    ("CONCESSION", "Although the ward was quiet, {cue}", "DIRECTION"),
    ("CONCESSION", "{cue}, although the ward was quiet", "DIRECTION"),
]

TERMINAL = {"QUESTION": "?"}


# --------------------------------------------------------------------------
# grammar
# --------------------------------------------------------------------------


def _cue_phrases() -> list[tuple[str, Stance, str]]:
    """Every directional cue in the inventory, read from the inventory itself.

    Neutral phrases are excluded: they are meta-statements about the
    observation ("says nothing about ..."), so they do not slot into the
    sentence frames below. Nothing here restates the list.
    """
    out = []
    for hypothesis in sorted(_CUES):
        by_stance = _CUES[hypothesis]
        for stance, phrases in sorted(by_stance.items(), key=lambda kv: kv[0].value):
            if stance not in (Stance.SUPPORTS, Stance.CONTRADICTS):
                continue
            for phrase in phrases:
                out.append((hypothesis, stance, phrase))
    return out


def _grammar_product() -> list[tuple[str, str, str, Stance, str]]:
    """The full grammar as a product: operator x template x lead x tail x cue."""
    phrases = _cue_phrases()
    out = []
    for operator, template, status in TEMPLATES:
        terminal = TERMINAL.get(operator, ".")
        for lead in LEADS:
            for tail in TAILS:
                for hypothesis, stance, phrase in phrases:
                    sentence = lead + template.format(cue=phrase) + tail + terminal
                    out.append((operator, status, hypothesis, stance, sentence))
    return out


def _sample() -> list[tuple[str, str, str, Stance, str]]:
    """The deterministic 20 000-sentence sample, drawn once per session."""
    global _SAMPLED
    if _SAMPLED is None:
        product = _grammar_product()
        assert len(product) >= MIN_SAMPLE, (
            f"grammar product is only {len(product)} sentences; the falsification "
            f"claim needs at least {MIN_SAMPLE}"
        )
        rng = random.Random(SEED)
        _SAMPLED = product if len(product) <= N_SAMPLE else rng.sample(product, N_SAMPLE)
    return _SAMPLED


_SAMPLED: list[tuple[str, str, str, Stance, str]] | None = None


def _verdict(sentence: str, hypothesis: str) -> tuple[Stance | None, str | None]:
    details = reviewed_relation_details(sentence, hypothesis)
    return details["relation"], details["reason_code"]


def _scored() -> dict:
    """Score every sampled sentence against its intended polarity."""
    per_operator = Counter()
    per_operator_commit = Counter()
    per_operator_wrong = Counter()
    per_operator_miss = Counter()
    per_operator_flip = Counter()
    relations = Counter()
    reasons = Counter()
    wrong_by_operator: dict[str, str] = {}
    commits = wrong = misses = flips = recall_hits = 0
    directional_rows = abstain_rows = 0

    for operator, status, hypothesis, stance, sentence in _sample():
        relation, reason = _verdict(sentence, hypothesis)
        per_operator[operator] += 1
        relations[str(relation)] += 1
        reasons[str(reason)] += 1
        if relation is not None:
            commits += 1
            per_operator_commit[operator] += 1
        if status == "DIRECTION":
            directional_rows += 1
            if relation == stance:
                recall_hits += 1
            elif relation is None:
                misses += 1
                per_operator_miss[operator] += 1
            else:
                flips += 1
                per_operator_flip[operator] += 1
        else:
            abstain_rows += 1
            if relation is not None:
                wrong += 1
                per_operator_wrong[operator] += 1
                wrong_by_operator.setdefault(operator, sentence)

    return {
        "n": len(_sample()),
        "commits": commits,
        "wrong_commits": wrong,
        "misses": misses,
        "flips": flips,
        "directional_rows": directional_rows,
        "abstain_rows": abstain_rows,
        "recall_hits": recall_hits,
        "relations": relations,
        "reasons": reasons,
        "per_operator": per_operator,
        "per_operator_commit": per_operator_commit,
        "per_operator_wrong": per_operator_wrong,
        "per_operator_miss": per_operator_miss,
        "per_operator_flip": per_operator_flip,
        "wrong_by_operator": wrong_by_operator,
    }


_SCORED: dict | None = None


def _score() -> dict:
    global _SCORED
    if _SCORED is None:
        _SCORED = _scored()
    return _SCORED


# --------------------------------------------------------------------------
# 1. the search: is the generator non-trivial, and is the guard stable on it?
# --------------------------------------------------------------------------


def test_generator_produces_non_trivial_verdicts() -> None:
    """A 99%-NO_CUE_MATCH generator would prove nothing, so this gates the rest.

    Reported distribution is asserted to be dominated by real decisions: at
    least half the sentences draw a cue and the guard commits on at least a
    third of them, with several distinct abstention reasons in play.
    """
    score = _score()
    n = score["n"]
    no_cue = score["reasons"].get("NO_CUE_MATCH", 0)

    assert n >= MIN_SAMPLE
    assert no_cue / n < 0.25, f"{no_cue}/{n} sentences drew no cue at all"
    assert score["commits"] / n > 0.33, (
        f"only {score['commits']}/{n} sentences got a committed direction; "
        f"relations={dict(score['relations'])}"
    )
    thin = {op: count for op, count in score["per_operator"].items() if count < 900}
    assert not thin, f"operator classes under-sampled: {thin}"
    assert len(score["per_operator"]) == len({row[0] for row in TEMPLATES})
    distinct_reasons = {code for code in score["reasons"] if code != "None"}
    assert len(distinct_reasons) >= 5, (
        f"only {sorted(distinct_reasons)} abstention reasons exercised; the "
        f"generator is not reaching the operator classes"
    )


def test_determinism_across_repeated_calls() -> None:
    """Same sentence, same verdict, every time: 2 calls x 20 000 sentences."""
    violations = 0
    first = None
    for _, _, hypothesis, _, sentence in _sample():
        a = _verdict(sentence, hypothesis)
        b = _verdict(sentence, hypothesis)
        if a != b:
            violations += 1
            if first is None:
                first = (sentence, hypothesis, a, b)
    assert violations == 0, f"{violations} non-deterministic verdicts; first={first}"


# --- order independence under clause permutation ---------------------------


def _sentence(clauses: list[str]) -> str:
    head = clauses[0][0].upper() + clauses[0][1:]
    return head + "".join(", and " + clause for clause in clauses[1:]) + "."


def _permutation_cases():
    """Yield (original, permuted, hypotheses, family) with the clauses reordered.

    Three families, because they stress different things:
      distinct_hyp  - independent clauses about different hypotheses;
      same_hyp_agree- two cues for one hypothesis, same direction;
      same_hyp_oppose - two cues for one hypothesis, opposite directions.
    """
    hypotheses = sorted(_CUES)
    support = {h: _CUES[h][Stance.SUPPORTS][0] for h in hypotheses}
    contradict = {
        h: _CUES[h][Stance.CONTRADICTS][0]
        for h in hypotheses
        if _CUES[h].get(Stance.CONTRADICTS)
    }

    for size in (2, 3):
        for combo in itertools.combinations(hypotheses, size):
            for lead in LEADS[:3]:
                clauses = [lead + support[h] for h in combo]
                original = _sentence(clauses)
                for perm in itertools.permutations(range(size)):
                    if tuple(perm) == tuple(range(size)):
                        continue
                    yield original, _sentence([clauses[i] for i in perm]), combo, "distinct_hyp"

    for hypothesis in hypotheses:
        phrases = _CUES[hypothesis][Stance.SUPPORTS]
        if len(phrases) < 2:
            continue
        for lead in LEADS[:3]:
            clauses = [lead + phrases[0], phrases[1]]
            yield _sentence(clauses), _sentence(clauses[::-1]), (hypothesis,), "same_hyp_agree"

    for hypothesis, phrase in contradict.items():
        for lead in LEADS[:3]:
            clauses = [lead + support[hypothesis], phrase]
            yield _sentence(clauses), _sentence(clauses[::-1]), (hypothesis,), "same_hyp_oppose"


def test_order_independence_under_clause_permutation() -> None:
    """Permuting independent clauses must not move the verdict.

    This is the law the algebra is built on: it composes a set of clause
    verdicts, so the composition cannot depend on the order the clauses arrived
    in. A violation here is not an algebra bug — it means the *guard* is not
    producing a function of the clause set, and every order-independence result
    downstream is about a model that the guard does not implement.
    """
    violations = Counter()
    smallest: dict[str, tuple] = {}
    checks = 0

    for original, permuted, subset, family in _permutation_cases():
        for hypothesis in subset:
            checks += 1
            before = _verdict(original, hypothesis)
            after = _verdict(permuted, hypothesis)
            if before != after:
                violations[family] += 1
                candidate = (len(original), original, permuted, hypothesis, before, after)
                if family not in smallest or candidate[0] < smallest[family][0]:
                    smallest[family] = candidate

    assert checks >= 500, f"only {checks} permutation checks ran"
    assert not violations, (
        f"{dict(violations)} of {checks} permutation checks changed the verdict; "
        f"smallest per family={smallest}"
    )


def test_idempotence_under_clause_repetition() -> None:
    """Repeating a clause you already have cannot change the verdict."""
    violations = 0
    first = None
    checks = 0
    hypotheses = sorted(_CUES)
    support = {h: _CUES[h][Stance.SUPPORTS][0] for h in hypotheses}

    for size in (2, 3):
        for combo in itertools.combinations(hypotheses, size):
            clauses = [support[h] for h in combo]
            once = _sentence(clauses)
            twice = _sentence(clauses + [clauses[-1]])
            for hypothesis in combo:
                checks += 1
                if _verdict(once, hypothesis) != _verdict(twice, hypothesis):
                    violations += 1
                    if first is None:
                        first = (once, twice, hypothesis)
    assert checks >= 40, f"only {checks} idempotence checks ran"
    assert violations == 0, f"{violations} of {checks} failed; first={first}"


def test_abstain_info_is_a_composition_identity_on_real_verdicts() -> None:
    """``ABSTAIN_INFO`` must never change a committed direction.

    Checked twice: on the four carrier elements, and on every verdict the guard
    actually produced for the 20 000 sentences. This is the law that makes the
    audit's finding B (a sentence-scope operator recorded as a clause-scope
    abstention) invisible to the composition: a withheld clause composes to the
    identity, so a committed neighbour carries the sentence.
    """
    carrier = [
        stance_algebra.Verdict.ABSTAIN_INFO,
        stance_algebra.Verdict.ABSTAIN_CONFLICT,
        stance_algebra.Verdict.SUPPORTS,
        stance_algebra.Verdict.CONTRADICTS,
    ]
    info = stance_algebra.Verdict.ABSTAIN_INFO
    for element in carrier:
        assert stance_algebra.compose_all([info, element]) == element
        assert stance_algebra.compose_all([element, info]) == element

    violations = 0
    first = None
    committed = 0
    for _, _, hypothesis, _, sentence in _sample():
        relation, _reason = _verdict(sentence, hypothesis)
        if relation is None:
            continue
        committed += 1
        element = stance_algebra.Verdict(relation.value)
        if stance_algebra.compose_all([element, info]) != element:
            violations += 1
            if first is None:
                first = (sentence, element)
    # 7 661 after the negative-frame rule was extended to speech acts (8 604 before,
    # 9 576 before that); the bound only guards against a corpus that stopped
    # producing claims to check against.
    assert committed > 7000, f"only {committed} committed verdicts to check against"
    assert violations == 0, f"{violations} of {committed} changed; first={first}"


# --------------------------------------------------------------------------
# 2. the measurement
# --------------------------------------------------------------------------


def test_measured_commit_rate_and_wrong_commits() -> None:
    """What committing buys, and what it costs, on the same 20 000 sentences.

    Re-measured after the postposed-hedge reader landed: 9 576 / 20 000 committed
    (47.9%), of which 1 915 (20.0%) are wrong by construction; 0 misses and 0 flips
    on the 7 661 sentences that really do assert the cue. The figures have moved three
    times: 10 530 / 2 869 (27.2%) before the postposed-hedge reader, 9 576 / 1 915
    (20.0%) after it, 8 604 / 943 (11.0%) after the evidential-denial rule, and
    **7 661 / 0** after that rule was extended to speech acts. The bounds below moved
    down with each fix; they are regression guards, not claims of adequacy. A corpus at
    zero is saturated, not solved: it now measures agreement with its own generator,
    and a fresh generator is the next real test.
    """
    score = _score()
    n = score["n"]
    assert n == N_SAMPLE
    assert score["directional_rows"] + score["abstain_rows"] == n
    assert score["misses"] == 0, (
        f"{score['misses']} asserted sentences lost their direction; "
        f"per_operator_miss={dict(score['per_operator_miss'])}"
    )
    assert score["flips"] == 0, (
        f"{score['flips']} asserted sentences got the opposite direction; "
        f"per_operator_flip={dict(score['per_operator_flip'])}"
    )
    assert 7500 <= score["commits"] <= 12000, f"committed {score['commits']}/{n}"
    # Measured: 0. The generator's ground truth and the guard now agree on every
    # generated sentence, which means this corpus has stopped discriminating — the
    # bound is kept at 0 so a regression is loud, and it is worth saying plainly
    # that a metric at zero has to be replaced before it can be trusted again.
    assert score["wrong_commits"] == 0, (
        f"{score['wrong_commits']}/{score['commits']} commits are wrong by "
        f"construction; per_operator_wrong={dict(score['per_operator_wrong'])}"
    )


def test_wrong_commits_are_confined_to_one_operator_class() -> None:
    """The errors are one family, not noise: scope read at the wrong level.

    When this file was written every wrong commit landed in HEDGE (a postposed
    hedge) or QUANTIFIER (a quantifier over a complement clause) — the same defect
    in two costumes: the operator's scope is the sentence, and the guard read scope
    only in the cue's own clause. The HEDGE half was curable and is now zero: the
    reader looked at the text *before* the cue, so a hedge after it was invisible by
    construction. QUANTIFIER remains, and is blocked by a corpus decision rather than
    by a missing rule (a negated reporting verb is pinned as certifying in
    `test_semantic_guard_negation_corpus.py`). Anything outside QUANTIFIER is a new
    family and must be investigated before the bound above is relaxed.
    """
    score = _score()
    outside = {
        operator: count
        for operator, count in score["per_operator_wrong"].items()
        if operator not in ("QUANTIFIER",)
    }
    assert not outside, (
        f"wrong commits outside the two known families: {outside}; "
        f"smallest examples={ {op: score['wrong_by_operator'][op] for op in outside} }"
    )


# --------------------------------------------------------------------------
# 3. three minimal counterexamples, each outside what the algebra can express
# --------------------------------------------------------------------------

CU = "CHECKLIST_UNAVAILABLE"


def test_attack_a_cue_spanning_a_clause_boundary() -> None:
    """CLOSED (was a FALSIFIED recall hole): a parenthetical inside the cue.

    "The checklist, as it happens, was unavailable" asserts exactly the cue. The
    matcher joined cue words with ``\\s+``, so whitespace inside the phrase was
    tolerated and punctuation was not: the comma version reported NO_CUE_MATCH —
    the guard's "the quote says nothing about this hypothesis" — while the newline
    version matched. The reader now tolerates a comma-, bracket- or dash-delimited
    aside inside the phrase.
    """
    assert _verdict("The checklist, as it happens, was unavailable.", CU) == (
        Stance.SUPPORTS, None)
    assert _verdict("The checklist (as it happens) was unavailable.", CU) == (
        Stance.SUPPORTS, None)
    assert _verdict("The checklist\nwas unavailable.", CU) == (Stance.SUPPORTS, None)

    # Neighbours: the aside cannot *be* the cue, and cannot carry the negation.
    assert _verdict("The checklist, as it happens.", CU) == (None, "NO_CUE_MATCH")
    assert _verdict("The checklist, as one might expect, was not unavailable.",
                    CU)[0] is None


def test_attack_b_operator_whose_scope_is_the_sentence() -> None:
    """CLOSED (was FALSIFIED): the consequent of a conditional was asserted.

    "If the ward was busy, the checklist was unavailable" asserts nothing about
    the checklist's availability; a conditional's consequent is proposed, not
    claimed. The guard abstained when the cue was the *antecedent*
    (CONDITIONAL_CUE) and committed SUPPORTS when the cue was the consequent, so
    the same operator produced opposite treatment depending on which side the
    cue landed on. The scope layer now reads the conditional by clause and both
    positions abstain.

    The semicolon variant is the same shape with a hedge: "Perhaps" scopes over
    the coordination, and the reader now sees the span rather than the cue's
    comma segment.
    """
    consequent = "If the ward was busy, the checklist was unavailable."
    antecedent = "If the checklist was unavailable, the team should have escalated."
    semicolon_hedge = "Perhaps the ward was busy; the checklist was unavailable."

    # CLOSED (was FALSIFIED). Both positions of the cue now abstain with the same
    # reason, so the verdict no longer depends on which side of the comma the cue
    # happens to fall on; and the semicolon hedge is read as a span, not as a
    # comma segment.
    assert _verdict(consequent, CU) == (None, "CONDITIONAL_CUE")
    assert _verdict(antecedent, CU) == (None, "CONDITIONAL_CUE")
    assert _verdict(semicolon_hedge, CU) == (None, "HEDGED_CUE")

    # Neighbours: the rule must not swallow a temporal clause or a coordination.
    assert _verdict("The checklist was unavailable when the ward round began.", CU) \
        == (Stance.SUPPORTS, None)
    assert _verdict("Perhaps the ward was busy, and the checklist was unavailable.", CU) \
        == (Stance.SUPPORTS, None)


def test_attack_c_negation_with_two_attachment_sites() -> None:
    """CLOSED (was FALSIFIED): negation over a reporting verb certified the cue.

    "The team did not report that the checklist was unavailable" has two
    attachment sites, and the dominant reading asserts nothing — while the guard
    committed SUPPORTS because a negated speech act was pinned as certifying.
    Negation over an *evidential* verb one line away abstained, so two lists
    disagreed about one construction; "I do not think …" was the same shape with a
    verb in neither list.

    All three now withhold. The three reasons differ, and that is the trace
    working: a denied speech act and a denied evidential act are both matrix
    frames (``ATTRIBUTED_DENIAL``), while a negation inside the cue's own clause
    is a cue negation (``NEGATED_CUE``).
    """
    assert _verdict("The team did not report that the checklist was unavailable.",
                    CU) == (None, "ATTRIBUTED_DENIAL")
    assert _verdict("I do not think the checklist was unavailable.", CU) == (
        None, "ATTRIBUTED_DENIAL")
    assert _verdict("The auditor did not confirm the checklist was unavailable.",
                    CU) == (None, "ATTRIBUTED_DENIAL")

    # Neighbours: affirmative frames certify, and a negation elsewhere does not reach.
    assert _verdict("The team reported that the checklist was unavailable.", CU) == (
        Stance.SUPPORTS, None)
    assert _verdict("The checklist was unavailable, and I do not think so.", CU) == (
        Stance.SUPPORTS, None)


def test_algebra_cannot_express_the_scope_the_attacks_need() -> None:
    """Why the three findings are not fixable inside the composition.

    A sentence-scope operator would have to be an element that *dominates* a
    committed direction. In this carrier ``ABSTAIN_INFO`` is the identity, so
    composing it with SUPPORTS is SUPPORTS — the composition is provably unable
    to let a withheld clause block a committed one. The only element above a
    direction is ``ABSTAIN_CONFLICT``, which means "two directions are both
    supported", a different fact. Detecting finding B therefore cannot be a
    composition rule; it has to happen before the clause is typed.
    """
    info = stance_algebra.Verdict.ABSTAIN_INFO
    supports = stance_algebra.Verdict.SUPPORTS
    conflict = stance_algebra.Verdict.ABSTAIN_CONFLICT

    assert stance_algebra.compose_all([info, supports]) == supports
    assert stance_algebra.compose_all([conflict, supports]) == conflict
    assert stance_algebra.is_abstention(info)
    assert not stance_algebra.is_direction(info)


# CLOSED DEFECT (was pinned strict xfail). The composition was always sound — it was
# never given the clause. A cue whose subject is a pronoun was not matched at all, so a
# sentence asserting both directions lost the second one and certified the first. The
# scope layer now derives the occurrence from the clause's own predicate and resolves the
# pronoun to the cue's subject.
#
# The neighbours matter as much as the fix: agreement still certifies, an unrelated
# subject still certifies, and the invariant-plural and determiner-led variants of the
# same construction must abstain too, because the first version of this fix resolved
# "it" to *staff* (an invariant plural read as singular) and to *the auditor* (an
# intervening animate subject), each time letting the sentence commit.
def test_an_opposing_clause_with_a_pronoun_is_not_silently_dropped():
    from app.semantic_guard import reviewed_relation_details

    for sentence in (
        "The checklist was unavailable, and others say it was available.",
        "The checklist was unavailable, and staff say it was available.",
        "The checklist was unavailable, and people say it was available.",
        "The checklist was unavailable, and they say it was available.",
        "The checklist was unavailable, and the auditor said it was available.",
        "The checklist was unavailable. The auditor said it was available.",
    ):
        detail = reviewed_relation_details(sentence, "CHECKLIST_UNAVAILABLE")
        assert detail["relation"] is None, (sentence, detail)
        assert detail["reason_code"] == "AMBIGUOUS_CUE_RELATIONS", (sentence, detail)


def test_a_pronoun_that_agrees_with_the_cue_still_certifies():
    """The neighbour: deriving the occurrence must not turn agreement into conflict."""
    from app.semantic_guard import reviewed_relation_details

    for sentence in (
        "The checklist was unavailable, and the auditor said it was unavailable.",
        "The checklist was unavailable, and staff say it was unavailable.",
    ):
        detail = reviewed_relation_details(sentence, "CHECKLIST_UNAVAILABLE")
        assert detail["relation"] is Stance.SUPPORTS, (sentence, detail)
        assert detail["reason_code"] is None, (sentence, detail)


def test_an_unrelated_subject_after_the_cue_still_certifies():
    """The over-attachment guard: no referent for the cue's subject, no derivation."""
    from app.semantic_guard import reviewed_relation_details

    for sentence in (
        "The checklist was unavailable, and the ward was empty.",
        "The checklist was unavailable. The auditor said the binder was missing.",
    ):
        detail = reviewed_relation_details(sentence, "CHECKLIST_UNAVAILABLE")
        assert detail["relation"] is Stance.SUPPORTS, (sentence, detail)


def test_the_same_sentence_with_the_subject_repeated_abstains():
    """The neighbour: this is the behaviour the rule is supposed to have everywhere."""
    from app.semantic_guard import reviewed_relation_details

    sentence = "The checklist was unavailable, and the checklist was available."
    assert reviewed_relation_details(sentence, "CHECKLIST_UNAVAILABLE")["relation"] is None
