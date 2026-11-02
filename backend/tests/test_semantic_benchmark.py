"""Labelled benchmark for the phrase cue guard (`app/semantic_guard.py`).

The guard's accuracy was previously unmeasured: the only figure in the tree was
two of three committed verdicts on a twelve-row table. This module is the
measurement. It carries 105 committed sentences, each with the hypothesis it is
judged against, the outcome a reviewer should certify, a one-line justification
and the linguistic phenomenon the row exercises.

**The split is frozen.** Every row carries its own ``split``. 64 rows are ``dev``
(61%) and 41 are ``holdout`` (39%). The holdout half is measured exactly once,
after the single fix this benchmark motivated, and is not re-split, re-labelled
or tuned against. See ``ct3/audit/SEMANTIC-BENCHMARK.md``.

Labelling protocol — a row is ``SUPPORTS`` / ``CONTRADICTS`` only when the
sentence *asserts* the hypothesis's cue proposition (or its denial) about the
world, and three charter rules hold:

1. **Assertion, not mention.** A question, a conditional, a hedge, or a negated
   report does not assert the proposition. Those rows are ``ABSTAIN``.
2. **No flipping.** A sentence whose cue is negated is not read as the opposite
   direction: the guard abstains. ``ABSTAIN`` is therefore also the label where a
   *human* could reason the flip out but the guard's charter forbids it.
3. **One direction.** Two opposite cues in one sentence, or a cue whose scope
   over the clause is undecidable from the words, is ``ABSTAIN``.

``ABSTAIN`` means a careful reviewer would not certify a direction. Where the
guard returns its explicit ``NEUTRAL`` relation (the "says nothing about"
cues), the row is scored as ``ABSTAIN``: no direction is certified either way.
That mapping is deliberate and is counted in the artifact.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.models import Stance
from app.semantic_guard import reviewed_relation_details

DEV = "dev"
HOLDOUT = "holdout"

SUPPORTS = "SUPPORTS"
CONTRADICTS = "CONTRADICTS"
ABSTAIN = "ABSTAIN"
CLASSES = (SUPPORTS, CONTRADICTS, ABSTAIN)

CU = "CHECKLIST_UNAVAILABLE"
TG = "TRAINING_GAP"
SC = "STAFFING_CONSTRAINTS"
PMS = "PMS_SYSTEM_ISSUE"
TP = "TIME_PRESSURE"

# The twelve phenomena this benchmark was required to cover, plus six more.
NAMED_TAGS = (
    "quantifier-negation",
    "verb-separated-negation",
    "evidence-aboutness",
    "concession",
    "contrast",
    "temporal-change",
    "hedge",
    "passive",
    "comma-splice",
    "cue-in-question",
    "negated-reporting-verb",
    "conditional",
)
EXTRA_TAGS = (
    "plain-assertion",
    "plain-negation",
    "quoted-speech",
    "clause-boundary-negation",
    "neutral-cue",
    "polarity-list",
)
ALL_TAGS = NAMED_TAGS + EXTRA_TAGS


@dataclass(frozen=True)
class Row:
    id: str
    split: str
    tag: str
    sentence: str
    hypothesis: str
    expected: str
    justification: str


ROWS: tuple[Row, ...] = (
    # --- plain assertion: an unhedged cue, nothing in scope over it ----------
    Row("assert-d1", DEV, "plain-assertion",
        "The printed checklist was unavailable in the theatre all morning.",
        CU, SUPPORTS, "A flat assertion of the cue; nothing negates or hedges it."),
    Row("assert-d2", DEV, "plain-assertion",
        "The ward was short staffed for the whole night shift.",
        SC, SUPPORTS, "Flat assertion of short staffing; the night detail does not qualify it."),
    Row("assert-d3", DEV, "plain-assertion",
        "The shift ran out of time before the inspection began.",
        TP, SUPPORTS, "Flat assertion of running out of time; the deadline does not weaken it."),
    Row("assert-d4", DEV, "plain-assertion",
        "The checklist opened normally at the start of the shift.",
        CU, CONTRADICTS, "The availability cue is asserted without qualification."),
    Row("assert-d5", DEV, "plain-assertion",
        "There were enough people on duty during the evening handover.",
        SC, CONTRADICTS, "The contradicting staffing cue is asserted; the shift time is descriptive."),
    Row("assert-h1", HOLDOUT, "plain-assertion",
        "The binder was missing from the reception desk.",
        CU, SUPPORTS, "The support cue is asserted as fact, with an adjunct only."),
    Row("assert-h2", HOLDOUT, "plain-assertion",
        "The property system timed out twice while saving the handover notes.",
        PMS, SUPPORTS, "Two timeouts are asserted, so the system-issue cue holds."),
    Row("assert-h3", HOLDOUT, "plain-assertion",
        "The system worked normally after the restart.",
        PMS, CONTRADICTS, "Normal operation is asserted; the restart is not a hedge."),
    Row("assert-h4", HOLDOUT, "plain-assertion",
        "The new colleague was unsure about the medication round.",
        TG, SUPPORTS, "The uncertainty cue is asserted of the colleague, not mentioned by another."),
    Row("assert-h5", HOLDOUT, "plain-assertion",
        "The shift had enough time to review every open item.",
        TP, CONTRADICTS, "Enough time is asserted, which is the denial of time pressure."),

    # --- plain negation: the cue itself is negated ---------------------------
    # Charter rule 2: the guard does not flip a negated cue, so these abstain
    # even where a human can reason the opposite direction out.
    Row("neg-d1", DEV, "plain-negation",
        "No checklist was available at the ward round.",
        CU, ABSTAIN, "The cue is negated; the guard's charter forbids inferring the flip."),
    Row("neg-d2", DEV, "plain-negation",
        "The unit was never short staffed over the weekend.",
        SC, ABSTAIN, "Clause negation of the staffing cue; only a flip would certify a direction."),
    Row("neg-d3", DEV, "plain-negation",
        "There was no time pressure that afternoon.",
        TP, ABSTAIN, "The time-pressure cue is denied in place; the opposite needs a flip."),
    Row("neg-d4", DEV, "plain-negation",
        "No colleague was unsure about the handover.",
        TG, ABSTAIN, "Quantified denial of the cue; certifying either way needs a flip."),
    Row("neg-h1", HOLDOUT, "plain-negation",
        "The ward was not understaffed during the handover.",
        SC, ABSTAIN, "The cue is negated in place; the readability of the flip is not the guard's licence."),
    Row("neg-h2", HOLDOUT, "plain-negation",
        "No binder was missing from the folder.",
        CU, ABSTAIN, "A quantifier denies the cue; no direction is asserted."),

    # --- quantifier negation: a subject quantifier scopes over the cue ------
    Row("quant-d1", DEV, "quantifier-negation",
        "Nobody walked through the handover with the new colleague.",
        TG, ABSTAIN, "The quantifier denies that the walkthrough happened at all."),
    Row("quant-d2", DEV, "quantifier-negation",
        "No one was short staffed on the night shift.",
        SC, ABSTAIN, "The quantifier denies the cue's proposition, not a report of it."),
    Row("quant-d3", DEV, "quantifier-negation",
        "Nobody saw that the binder was missing.",
        CU, ABSTAIN, "The quantifier scopes over the perception, and no availability is asserted."),
    Row("quant-d4", DEV, "quantifier-negation",
        "None of the staff walked through the handover.",
        TG, ABSTAIN, "Zero staff, so the walkthrough cue is denied outright."),
    Row("quant-h1", HOLDOUT, "quantifier-negation",
        "No colleague was absent that morning.",
        SC, ABSTAIN, "The absence cue is denied for the whole set of colleagues."),
    Row("quant-h2", HOLDOUT, "quantifier-negation",
        "Nobody had enough time to review every open item.",
        TP, ABSTAIN, "The quantifier denies that anyone had the time; no direction is asserted."),

    # --- verb-separated negation: negation carried by a verb ----------------
    Row("verbneg-d1", DEV, "verb-separated-negation",
        "We did not have enough time to review every open item.",
        TP, ABSTAIN, "States the absence of time without asserting the cue; the verb carries the doubt."),
    Row("verbneg-d2", DEV, "verb-separated-negation",
        "The team did not confirm the checklist was available.",
        CU, ABSTAIN, "Absence of confirmation is not a denial of availability."),
    Row("verbneg-d3", DEV, "verb-separated-negation",
        "The auditor has not verified the system worked normally.",
        PMS, ABSTAIN, "Not verifying normal operation says nothing about how the system ran."),
    Row("verbneg-h1", HOLDOUT, "verb-separated-negation",
        "Staff did not document that the binder was missing.",
        CU, ABSTAIN, "The documentation gap is the claim; the binder's state is not asserted."),
    Row("verbneg-h2", HOLDOUT, "verb-separated-negation",
        "The clerk never recorded that the system timed out.",
        PMS, ABSTAIN, "No record of a timeout is not evidence either way about the timeout."),
    Row("verbneg-h3", HOLDOUT, "verb-separated-negation",
        "We did not establish that the shift had enough time.",
        TP, ABSTAIN, "Failing to establish a fact leaves both directions uncertified."),

    # --- evidence aboutness: the sentence is about the evidence base --------
    Row("evid-d1", DEV, "evidence-aboutness",
        "No evidence the checklist was available.",
        CU, ABSTAIN, "The sentence reports an absence of evidence, not the checklist's state."),
    Row("evid-d2", DEV, "evidence-aboutness",
        "Nothing suggests the system timed out.",
        PMS, ABSTAIN, "About what the record suggests, not about what happened."),
    Row("evid-d3", DEV, "evidence-aboutness",
        "No evidence that the shift ran out of time.",
        TP, ABSTAIN, "An evidence gap is not an assertion that there was no time pressure."),
    Row("evid-h1", HOLDOUT, "evidence-aboutness",
        "There is no indication the checklist was unavailable.",
        CU, ABSTAIN, "Indicates a gap in the record, which cannot certify availability either."),
    Row("evid-h2", HOLDOUT, "evidence-aboutness",
        "There was no sign the colleague was absent.",
        SC, ABSTAIN, "Reports the absence of a sign, not the colleague's attendance."),

    # --- concession: the cue is conceded in a subordinate clause ------------
    Row("conc-d1", DEV, "concession",
        "Although the checklist was available, staff searched the cabinet for ten minutes.",
        CU, CONTRADICTS, "The concessive clause concedes availability; the search does not retract it."),
    Row("conc-d2", DEV, "concession",
        "The checklist was available, although it was filed in the wrong cabinet.",
        CU, CONTRADICTS, "Filing is not availability; the main assertion stands."),
    Row("conc-d3", DEV, "concession",
        "Although the shift had enough time, the review was rushed.",
        TP, CONTRADICTS, "Enough time is conceded; the rushed review does not deny it."),
    Row("conc-d4", DEV, "concession",
        "Though the ward was short staffed, the handover was completed.",
        SC, SUPPORTS, "Short staffing is conceded; completing the handover does not retract it."),
    Row("conc-h1", HOLDOUT, "concession",
        "Even though the binder was missing, the appointment went ahead.",
        CU, SUPPORTS, "The missing binder is the conceded premise, so the support cue holds."),
    Row("conc-h2", HOLDOUT, "concession",
        "The team walked through the handover, although the colleague already knew the process.",
        TG, SUPPORTS, "A completed walkthrough is asserted even if it was redundant."),

    # --- contrast: two clauses joined by but / however ----------------------
    Row("contr-d1", DEV, "contrast",
        "The checklist was unavailable in the morning, but the binder was at the desk by noon.",
        CU, ABSTAIN, "Support and contradiction are both asserted; the tail does not date them."),
    Row("contr-d2", DEV, "contrast",
        "The ward was short staffed, but there were enough people on duty by midnight.",
        SC, ABSTAIN, "Opposite staffing cues in one sentence; the times do not settle which governs."),
    Row("contr-d3", DEV, "contrast",
        "The staff were not short staffed, but the colleague was absent.",
        SC, SUPPORTS, "The negation is confined to the first clause; absence is asserted."),
    Row("contr-d4", DEV, "contrast",
        "The binder was at the desk, but the staff still could not review every open item.",
        CU, CONTRADICTS, "The availability cue is asserted and nothing after it retracts it."),
    Row("contr-h1", HOLDOUT, "contrast",
        "The binder was missing at 9am, but the checklist was available from 10am.",
        CU, ABSTAIN, "Two opposite cues with different times; no single direction is asserted."),
    Row("contr-h2", HOLDOUT, "contrast",
        "The checklist was available, but no one could confirm the binder was at the desk.",
        CU, CONTRADICTS, "Availability is asserted outright; the second clause is an evidence gap."),

    # --- temporal change: a later clause supersedes an earlier state --------
    Row("temp-d1", DEV, "temporal-change",
        "The checklist was unavailable this morning, but it is available now.",
        CU, CONTRADICTS, "The current state is availability, and it supersedes the morning state."),
    Row("temp-d2", DEV, "temporal-change",
        "The ward was short staffed last week, but it is not short staffed any more.",
        SC, CONTRADICTS, "The later clause is a present-tense denial of short staffing."),
    Row("temp-d3", DEV, "temporal-change",
        "The binder was missing at 8am, but it is at the desk now.",
        CU, CONTRADICTS, "Being at the desk now is the current state, so the morning gap is historical."),
    Row("temp-h1", HOLDOUT, "temporal-change",
        "The system was unavailable yesterday, but it is working normally today.",
        PMS, CONTRADICTS, "Today's normal operation supersedes yesterday's outage."),
    Row("temp-h2", HOLDOUT, "temporal-change",
        "The shift had enough time yesterday; today it does not have enough time.",
        TP, SUPPORTS, "The temporal contrast inverts the state; today is the state under review."),
    Row("temp-h3", HOLDOUT, "temporal-change",
        "The checklist was available yesterday, but the binder was missing this morning.",
        CU, ABSTAIN, "Two opposite cues on two days; the record does not rank the days."),

    # --- hedge: the proposition is proposed, not asserted ------------------
    Row("hedge-d1", DEV, "hedge",
        "Perhaps the checklist was unavailable during the ward round.",
        CU, ABSTAIN, "An epistemic adverb over the whole clause; the speaker does not assert it."),
    Row("hedge-d2", DEV, "hedge",
        "It is possible the system timed out during the save.",
        PMS, ABSTAIN, "Possibility is not occurrence, so no direction is certifiable."),
    Row("hedge-d3", DEV, "hedge",
        "Probably the ward was short staffed that evening.",
        SC, ABSTAIN, "A probability adverb leaves the proposition unasserted."),
    Row("hedge-d4", DEV, "hedge",
        "It seems that the checklist was unavailable.",
        CU, ABSTAIN, "An appearance report about the cue, not an assertion of it."),
    Row("hedge-d5", DEV, "hedge",
        "Presumably the colleague was unsure about the medication round.",
        TG, ABSTAIN, "Presumption is weaker than assertion; nothing is certified."),
    Row("hedge-h1", HOLDOUT, "hedge",
        "Possibly the colleague was unsure about the handover.",
        TG, ABSTAIN, "A possibility adverb, so the uncertainty cue is not asserted."),
    Row("hedge-h2", HOLDOUT, "hedge",
        "Maybe the shift ran out of time before the inspection.",
        TP, ABSTAIN, "The clause is offered as a possibility, not as the shift's state."),
    Row("hedge-h3", HOLDOUT, "hedge",
        "The checklist was unavailable, I think.",
        CU, ABSTAIN, "A postposed hedge weakens the assertion, so no direction is certifiable."),

    # --- passive: the cue sits in a passive or impersonal frame ------------
    Row("pass-d1", DEV, "passive",
        "It was confirmed by the auditor that the checklist was unavailable.",
        CU, SUPPORTS, "A passive attribution of a confirmation still asserts the complement."),
    Row("pass-d2", DEV, "passive",
        "It was noted by the supervisor that the ward was short staffed.",
        SC, SUPPORTS, "The impersonal frame carries the asserted staffing cue."),
    Row("pass-d3", DEV, "passive",
        "It was observed by the auditor that the shift had enough time.",
        TP, CONTRADICTS, "Observation of enough time is an assertion about the shift."),
    Row("pass-d4", DEV, "passive",
        "It was confirmed by the auditor that the checklist was available.",
        CU, CONTRADICTS, "The passive asserts availability, which is the denial of the hypothesis."),
    Row("pass-h1", HOLDOUT, "passive",
        "It was recorded by the clerk that the binder was missing.",
        CU, SUPPORTS, "A recorded statement of the cue is still a statement of the cue."),
    Row("pass-h2", HOLDOUT, "passive",
        "It was documented that the colleague was absent.",
        SC, SUPPORTS, "The impersonal assertion carries the cue without hedging it."),

    # --- comma splice: one sentence, several clauses -----------------------
    Row("splice-d1", DEV, "comma-splice",
        "The checklist was unavailable, the staff improvised a verbal handover.",
        CU, SUPPORTS, "The spliced clause asserts the cue; the second clause is commentary."),
    Row("splice-d2", DEV, "comma-splice",
        "The binder was missing, the audit was postponed.",
        CU, SUPPORTS, "The spliced consequence does not retract the missing binder."),
    Row("splice-d3", DEV, "comma-splice",
        "The checklist was available, the staff did not need the printed copy.",
        CU, CONTRADICTS, "Availability is asserted; the second clause explains it, without undoing it."),
    Row("splice-d4", DEV, "comma-splice",
        "The system timed out, the clerk re-entered the notes by hand.",
        PMS, SUPPORTS, "The transcript of a timeout is asserted, then a workaround."),
    Row("splice-h1", HOLDOUT, "comma-splice",
        "The ward was understaffed, the night shift stretched to twelve hours.",
        SC, SUPPORTS, "Understaffing is asserted and the long shift corroborates, not weakens."),
    Row("splice-h2", HOLDOUT, "comma-splice",
        "The shift ran out of time, the inspection started late.",
        TP, SUPPORTS, "Running out of time is asserted; the late start is separate."),

    # --- cue in question: the cue appears inside a question ----------------
    Row("q-d1", DEV, "cue-in-question",
        "Was the checklist unavailable at the ward round?",
        CU, ABSTAIN, "A yes/no question asks whether the cue holds; it does not assert it."),
    Row("q-d2", DEV, "cue-in-question",
        "Did anyone see that the binder was missing?",
        CU, ABSTAIN, "The question asks about a sighting, so the cue is not asserted."),
    Row("q-d3", DEV, "cue-in-question",
        "Did the shift have enough time to review every open item?",
        TP, ABSTAIN, "A question about time; certifying either direction would invent an answer."),
    Row("q-d4", DEV, "cue-in-question",
        "Was anyone told that the checklist was unavailable?",
        CU, ABSTAIN, "A question about who was told asserts neither the telling nor the cue."),
    Row("q-h1", HOLDOUT, "cue-in-question",
        "Has the ward been short staffed this week?",
        SC, ABSTAIN, "An open question about staffing levels, not a statement of them."),
    Row("q-h2", HOLDOUT, "cue-in-question",
        "Is it true that the checklist was unavailable?",
        CU, ABSTAIN, "Even a truth-checking question leaves the proposition unasserted."),

    # --- negated reporting verb: the saying is denied, not the cue ---------
    Row("rept-d1", DEV, "negated-reporting-verb",
        "The auditor did not say the checklist was unavailable.",
        CU, ABSTAIN, "The denial is of the saying; the checklist's state stays unasserted."),
    Row("rept-d2", DEV, "negated-reporting-verb",
        "The clerk never claimed the binder was missing.",
        CU, ABSTAIN, "Never claiming is not a claim; nothing about the binder follows."),
    Row("rept-d3", DEV, "negated-reporting-verb",
        "The supervisor did not mention that the shift ran out of time.",
        TP, ABSTAIN, "The omission is the claim; it does not assert or deny time pressure."),
    Row("rept-h1", HOLDOUT, "negated-reporting-verb",
        "No one reported that the ward was short staffed.",
        SC, ABSTAIN, "The report is denied; the staffing state is not asserted either way."),
    Row("rept-h2", HOLDOUT, "negated-reporting-verb",
        "The technician did not note that the system timed out.",
        PMS, ABSTAIN, "A missing note is not a missing timeout."),

    # --- conditional: the cue is a hypothesis, not a fact ------------------
    Row("cond-d1", DEV, "conditional",
        "If the checklist was unavailable, the team should have escalated.",
        CU, ABSTAIN, "A conditional antecedent proposes the cue; it does not assert it."),
    Row("cond-d2", DEV, "conditional",
        "If the system was unavailable, the clerk would have logged it.",
        PMS, ABSTAIN, "The counterfactual consequent says nothing asserted about the outage."),
    Row("cond-d3", DEV, "conditional",
        "Unless the checklist was unavailable, the audit proceeds as planned.",
        CU, ABSTAIN, "Unless introduces a hypothetical exception, not an assertion of the cue."),
    Row("cond-h1", HOLDOUT, "conditional",
        "If the binder was missing, the audit would have stopped.",
        CU, ABSTAIN, "A counterfactual antecedent, so the missing binder is not asserted."),
    Row("cond-h2", HOLDOUT, "conditional",
        "Were the ward short staffed, agency staff would cover the shift.",
        SC, ABSTAIN, "An inverted subjunctive conditional; no staffing state is asserted."),

    # --- quoted speech: an attributed assertion ----------------------------
    Row("quote-d1", DEV, "quoted-speech",
        "The auditor wrote: 'the checklist was unavailable all morning'.",
        CU, SUPPORTS, "An attributed assertion of the cue is still an assertion of the cue."),
    Row("quote-d2", DEV, "quoted-speech",
        "The night nurse said the ward was short staffed.",
        SC, SUPPORTS, "Reported speech with no negation reports the cue as stated."),
    Row("quote-d3", DEV, "quoted-speech",
        "'We ran out of time,' the shift lead said.",
        TP, SUPPORTS, "The quoted clause asserts running out of time."),
    Row("quote-h1", HOLDOUT, "quoted-speech",
        "'The binder was missing,' the clerk told the review.",
        CU, SUPPORTS, "A quoted assertion of the cue, attributed but unnegated."),
    Row("quote-h2", HOLDOUT, "quoted-speech",
        "The clerk said that the system worked normally after the restart.",
        PMS, CONTRADICTS, "Attributed and unnegated, so normal operation is reported as asserted."),

    # --- clause-boundary negation: the negation is in another clause -------
    Row("bound-d1", DEV, "clause-boundary-negation",
        "The clerk did not have the key, however the checklist was unavailable.",
        CU, SUPPORTS, "The negation is confined to the first clause; the cue clause is intact."),
    Row("bound-d2", DEV, "clause-boundary-negation",
        "The clerk was never trained on the system, but the system timed out twice.",
        PMS, SUPPORTS, "Training is the negated subject; the timeout is asserted separately."),
    Row("bound-d3", DEV, "clause-boundary-negation",
        "The auditor had no notes, and the checklist was unavailable.",
        CU, SUPPORTS, "The quantifier over notes does not reach the availability clause."),
    Row("bound-d4", DEV, "clause-boundary-negation",
        "The ward was not quiet, though the shift had enough time.",
        TP, CONTRADICTS, "Noise is what is negated; enough time is asserted in its own clause."),
    Row("bound-h1", HOLDOUT, "clause-boundary-negation",
        "The team did not know the ward, but the colleague was absent that night.",
        SC, SUPPORTS, "Familiarity is negated; the absence cue is a separate assertion."),
    Row("bound-h2", HOLDOUT, "clause-boundary-negation",
        "No one had seen the binder before, yet the checklist was unavailable.",
        CU, SUPPORTS, "The quantifier scopes over the sighting clause, not the availability clause."),

    # --- neutral cue: the record explicitly does not address the question --
    Row("neut-d1", DEV, "neutral-cue",
        "The report says nothing about checklist availability.",
        CU, ABSTAIN, "An explicit non-address offers no direction at all."),
    Row("neut-d2", DEV, "neutral-cue",
        "The log says nothing about checklist availability during the audit.",
        CU, ABSTAIN, "Nothing about availability is exactly no certifiable direction."),
    Row("neut-h1", HOLDOUT, "neutral-cue",
        "The note does not address checklist availability.",
        CU, ABSTAIN, "An explicit statement of non-address certifies no direction."),

    # --- polarity list: not-X-but-Y, not only ------------------------------
    Row("polar-d1", DEV, "polarity-list",
        "The system was unavailable, not only slow.",
        PMS, SUPPORTS, "The list narrows the fault; unavailability is still asserted."),
    Row("polar-d2", DEV, "polarity-list",
        "The ward was understaffed, not because of absence but because of turnover.",
        SC, SUPPORTS, "The not-because list explains the cause; understaffing stands."),
    Row("polar-h1", HOLDOUT, "polarity-list",
        "The checklist was unavailable, not just the printed copy.",
        CU, SUPPORTS, "Not-just widens rather than cancels the unavailability."),
    Row("polar-h2", HOLDOUT, "polarity-list",
        "The checklist was unavailable, not merely delayed.",
        CU, SUPPORTS, "Not-merely contrasts the magnitude, not the state."),
)


# --- measurement ----------------------------------------------------------


def observed(row: Row) -> str:
    """The guard's direction for one row, with ``NEUTRAL`` folded into ABSTAIN."""
    detail = reviewed_relation_details(row.sentence, row.hypothesis)
    relation = detail["relation"]
    if relation is None or relation is Stance.NEUTRAL:
        return ABSTAIN
    return relation.value


def rows_for(split: str) -> tuple[Row, ...]:
    return tuple(row for row in ROWS if row.split == split)


def score(rows) -> dict:
    rows = tuple(rows)
    confusion = {expected: {seen: 0 for seen in CLASSES} for expected in CLASSES}
    for row in rows:
        confusion[row.expected][observed(row)] += 1
    correct = sum(confusion[cls][cls] for cls in CLASSES)
    per_class = {}
    for cls in CLASSES:
        true_positive = confusion[cls][cls]
        predicted = sum(confusion[other][cls] for other in CLASSES)
        actual = sum(confusion[cls].values())
        per_class[cls] = {
            "true_positive": true_positive,
            "predicted": predicted,
            "actual": actual,
            "precision": (true_positive / predicted) if predicted else None,
            "recall": (true_positive / actual) if actual else None,
        }
    return {
        "total": len(rows),
        "correct": correct,
        "accuracy": (correct / len(rows)) if rows else None,
        "confusion": confusion,
        "per_class": per_class,
    }


def misreads(rows) -> list[tuple[Row, str]]:
    """Rows the guard gets wrong, in stable row order."""
    return [(row, observed(row)) for row in rows if observed(row) != row.expected]


def tag_errors(rows) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if observed(row) != row.expected:
            counts[row.tag] = counts.get(row.tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def format_report(splits=(DEV, HOLDOUT)) -> str:
    """The table the audit artifact records, computed from the same code path."""
    lines = []
    for split in splits:
        rows = rows_for(split)
        measured = score(rows)
        lines.append(f"[{split}] accuracy {measured['correct']}/{measured['total']} "
                     f"= {measured['accuracy']:.3f}")
        header = "expected \\ observed".ljust(22) + "".join(cls.rjust(12) for cls in CLASSES)
        lines.append(header)
        for expected in CLASSES:
            cells = "".join(str(measured["confusion"][expected][seen]).rjust(12)
                            for seen in CLASSES)
            lines.append(expected.ljust(22) + cells)
        for cls in CLASSES:
            stats = measured["per_class"][cls]
            precision = f"{stats['precision']:.2f}" if stats["precision"] is not None else "n/a"
            recall = f"{stats['recall']:.2f}" if stats["recall"] is not None else "n/a"
            lines.append(f"  {cls}: precision {precision} ({stats['true_positive']}/"
                         f"{stats['predicted']}), recall {recall} "
                         f"({stats['true_positive']}/{stats['actual']})")
        if split == DEV:
            errors = misreads(rows)
            lines.append(f"  dev misreads {len(errors)}/{len(rows)}:"
                         + ("" if errors else " none"))
            for row, seen in errors:
                lines.append(f"    {row.id} [{row.tag}] expected {row.expected}, saw {seen}")
            counts = tag_errors(rows)
            lines.append("  dev misreads by tag: "
                         + (", ".join(f"{tag} {count}" for tag, count in counts.items())
                            if counts else "none"))
    return "\n".join(lines)


# --- pins -----------------------------------------------------------------


def test_benchmark_is_large_enough_and_the_split_is_frozen():
    assert len(ROWS) >= 80, len(ROWS)
    dev = rows_for(DEV)
    holdout = rows_for(HOLDOUT)
    # The committed split: 64 dev / 41 holdout. The share is pinned so a later
    # edit cannot quietly move rows between halves after seeing a result.
    assert len(dev) == 64, len(dev)
    assert len(holdout) == 41, len(holdout)
    assert 0.55 <= len(dev) / len(ROWS) <= 0.65, len(dev) / len(ROWS)


def test_row_ids_are_unique():
    ids = [row.id for row in ROWS]
    assert len(ids) == len(set(ids)), "duplicate row id"


def test_every_phenomenon_is_covered_on_both_splits():
    tags = {row.tag for row in ROWS}
    assert tags == set(ALL_TAGS), (tags ^ set(ALL_TAGS))
    for tag in NAMED_TAGS:
        for split in (DEV, HOLDOUT):
            assert any(row.tag == tag and row.split == split for row in ROWS), (tag, split)
    for tag in ALL_TAGS:
        assert sum(row.tag == tag for row in ROWS) >= 3, tag


def test_every_row_matches_a_cue():
    """A row that matched no phrase would abstain for the wrong reason."""
    for row in ROWS:
        detail = reviewed_relation_details(row.sentence, row.hypothesis)
        assert detail["cue_ids"], (row.id, row.sentence)
        assert all(cue_id.startswith(row.hypothesis + ".") for cue_id in detail["cue_ids"]), (
            row.id, detail["cue_ids"]
        )


def test_every_row_carries_a_justification_a_reader_can_disagree_with():
    for row in ROWS:
        assert len(row.justification) >= 40, row.id
        assert row.expected in CLASSES, row.id
        assert row.sentence.strip().endswith((".", "?", "'")), row.id


def test_all_three_classes_have_denominators_on_both_splits():
    # Four is a floor, not a comfort: the holdout CONTRADICTS denominator is five
    # rows, which is why its precision and recall are quoted with that denominator
    # and are not used to rank anything.
    for split in (DEV, HOLDOUT):
        measured = score(rows_for(split))
        for cls in CLASSES:
            assert measured["per_class"][cls]["actual"] >= 4, (split, cls)


# The single fix this benchmark motivated: a sentence-initial epistemic hedge
# ("Perhaps ...", "It is possible ...") proposes the cue instead of asserting it,
# so the guard must abstain. The neighbours below are the rows that must NOT
# abstain, pinned so the rule cannot widen into ordinary modality.
HEDGE_NEIGHBOURS = [
    ("The team could not review every open item before the deadline.", TP, SUPPORTS),
    ("The shift had enough time to review every open item.", TP, CONTRADICTS),
    ("No one could confirm that the checklist was unavailable.", CU, SUPPORTS),
    ("Perhaps the ward was busy, and the checklist was unavailable.", CU, SUPPORTS),
    ("The checklist was unavailable, though perhaps the binder was at the desk.",
     CU, SUPPORTS),
    ("There is no doubt the binder was missing.", CU, SUPPORTS),
]


@pytest.mark.parametrize("sentence,hypothesis,stance", HEDGE_NEIGHBOURS)
def test_the_hedge_rule_does_not_swallow_ordinary_modality(sentence, hypothesis, stance):
    relation = reviewed_relation_details(sentence, hypothesis)["relation"]
    assert relation is not None, (sentence, "a readable row must not abstain")
    assert relation == Stance(stance), (sentence, relation)


# The hedge rule reads only to the left of the cue, where English puts these
# adverbials. A hedge *after* the cue is outside the rule; the row is kept in the
# benchmark as a known misread rather than dropped from the measurement.
POST_CUE_HEDGE_IDS = frozenset({"hedge-h3"})


@pytest.mark.parametrize(
    "sentence,hypothesis",
    [(row.sentence, row.hypothesis) for row in ROWS
     if row.tag == "hedge" and row.id not in POST_CUE_HEDGE_IDS],
)
def test_a_hedged_row_abstains_with_its_own_reason_and_still_cites_the_cue(
        sentence, hypothesis):
    detail = reviewed_relation_details(sentence, hypothesis)
    assert detail["relation"] is None, (sentence, detail)
    assert detail["reason_code"] == "HEDGED_CUE", (sentence, detail)
    assert detail["cue_ids"], (sentence, detail)


@pytest.mark.parametrize(
    "sentence,hypothesis",
    [(row.sentence, row.hypothesis) for row in ROWS],
)
def test_benchmark_row_is_deterministic(sentence, hypothesis):
    first = reviewed_relation_details(sentence, hypothesis)
    assert reviewed_relation_details(sentence, hypothesis) == first
    first["cue_ids"].append("injected")
    assert "injected" not in reviewed_relation_details(sentence, hypothesis)["cue_ids"]


# Rows whose label the guard does not meet. Each entry is a defect report, kept
# as a strict xfail: when a later fix makes the row pass, pytest fails on the
# XPASS and the marker must be removed with the defect. See the artifact.
KNOWN_MISREADS: dict[str, str] = {
    # Quantifier rule switched off by the complementiser "that" (quant-d3): a
    # sentence that denies the sighting is certified SUPPORTS. Unsafe direction.
    "quant-d3": "'that' disables the quantifier rule, so a denied sighting certifies SUPPORTS",
    # Temporal supersession. Safe direction = the guard abstains where the label
    # certifies the current state; unsafe = it certifies the superseded state.
    "temp-d1": "safe abstention: 'available now' supersedes the cue",
    "temp-d2": "unsafe: 'any more' is not the 'anymore' token the current-state pattern reads",
    "temp-d3": "safe abstention: 'at the desk now' supersedes the cue",
    "temp-h1": "safe abstention: 'working normally today' supersedes the cue",
    "temp-h2": "unsafe: supersession across a semicolon is invisible, so yesterday's state certifies",
    # Residual of the hedge fix: the new rule reads only to the left of the cue.
    "hedge-h3": "residual: a hedge after the cue is outside the pre-cue hedge rule",
    # Negated speech-act verb: this is the reading the negation corpus pins on
    # purpose (CU-MATRIX-DID-NOT-SAY, SC-NO-ONE-REPORTED, CU-MATRIX-NEVER-CLAIMED),
    # so the guard cannot be fixed here without contradicting a committed pin.
    "rept-d1": "unsafe, pinned by the negation corpus: a negated report certifies the complement",
    "rept-d2": "unsafe, pinned by the negation corpus: a denied claim certifies the complement",
    "rept-d3": "unsafe, pinned by the negation corpus: a denied mention certifies the complement",
    "rept-h1": "unsafe, pinned by the negation corpus: a denied report certifies the complement",
    "rept-h2": "unsafe, pinned by the negation corpus: a missing note certifies the complement",
    # Conditional antecedent certified as though asserted. Only the unmarked
    # inversion below is left: it has no if/when/unless marker to key on.
    "cond-h2": "unsafe: an inverted subjunctive is certified as if asserted",
    # Safe direction: the quantifier rule reaches across a clause boundary.
    "bound-h2": "safe abstention: the quantifier rule reaches across a clause boundary",
}


def _cases():
    cases = []
    for row in ROWS:
        marks = ()
        if row.id in KNOWN_MISREADS:
            marks = (pytest.mark.xfail(strict=True,
                                       reason=KNOWN_MISREADS[row.id]),)
        cases.append(pytest.param(row, id=row.id, marks=marks))
    return cases


@pytest.mark.parametrize("row", _cases())
def test_benchmark_row_matches_label(row):
    seen = observed(row)
    assert seen == row.expected, (
        f"{row.id} [{row.tag}] expected {row.expected}, saw {seen}: {row.sentence!r}"
    )


def test_dev_accuracy_floor():
    """Regression floor: 50/64 = 0.781 measured after the hedge fix."""
    measured = score(rows_for(DEV))
    assert measured["accuracy"] >= 0.78, format_report((DEV,))


def test_holdout_accuracy_floor():
    """Regression floor: the single holdout measurement, 31/41 = 0.756."""
    measured = score(rows_for(HOLDOUT))
    assert measured["accuracy"] >= 0.75, format_report((HOLDOUT,))
