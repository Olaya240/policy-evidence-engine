"""Fresh semantic-guard holdout, written independently of the first benchmark.

Why this file exists
--------------------
``tests/test_semantic_benchmark.py`` measured the guard at 78.1% accuracy on its
dev split, and its ``holdout`` half has since been looked at, discussed and used
to motivate fixes. A split that has been read is no longer a holdout: every later
figure computed on it is contaminated by whoever read it. This module is a second,
independent measurement so that a clean accuracy figure exists.

Independence method (and its honest limits)
-------------------------------------------
* The rows below were written from the twelve required phenomena and from the
  guard's *cue inventory* (``_CUES`` in ``app/semantic_guard.py``), not from the
  first benchmark's sentences. A row needs a real cue string to be meaningful, so
  the inventory is fair game; the sentences are not.
* **What actually happened, disclosed rather than papered over:** while opening
  the first benchmark only to read its module docstring, dataclass and tag list,
  the first ~120 lines of its ``ROWS`` tuple came with the read. That exposed its
  rows for five tags — ``plain-assertion``, ``plain-negation``,
  ``quantifier-negation``, ``verb-separated-negation`` and ``evidence-aboutness``
  — before mine were written. My rows for those tags were not written as variants
  of what I saw, but that cannot be proven from the file, so the independence
  claim is *qualified for those five tags* and clean for the other thirteen. This
  is recorded in ``ct3/audit/SEMANTIC-HOLDOUT-V2.md``.
* The rows were committed here and their consistency checks were run **before**
  the guard was called on any of them. ``git log``/mtime order is the evidence.

Labelling protocol
------------------
A row is ``SUPPORTS`` / ``CONTRADICTS`` only when the sentence *asserts* the
hypothesis's cue proposition (or the opposing one) about the world. The charter
rules that decide the rest:

1. **Assertion, not mention.** A question, a conditional, a hedge, or a negated
   report does not assert the proposition: ``ABSTAIN``.
2. **No flipping.** A sentence whose cue is negated is not read as the opposite
   direction: ``ABSTAIN``.
3. **One direction.** Two opposing cues in one sentence, or a cue whose scope is
   undecidable from the words: ``ABSTAIN``.

``contested`` marks a row where a reasonable reviewer could defend a different
label. Contested rows are reported separately and are **excluded** from the
headline accuracy, so a judgement call can neither inflate nor deflate it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

from app.models import Stance
from app.semantic_guard import _CUES, reviewed_relation_details

SPLIT = "holdout"

SUPPORTS = "SUPPORTS"
CONTRADICTS = "CONTRADICTS"
ABSTAIN = "ABSTAIN"
CLASSES = (SUPPORTS, CONTRADICTS, ABSTAIN)

CU = "CHECKLIST_UNAVAILABLE"
TG = "TRAINING_GAP"
SC = "STAFFING_CONSTRAINTS"
PMS = "PMS_SYSTEM_ISSUE"
TP = "TIME_PRESSURE"

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
    "plain-assertion",
)


@dataclass(frozen=True)
class Row:
    """One holdout sentence and the label a careful reviewer should certify.

    ``inventory_phrase`` is the cue string from ``_CUES`` the row is built around.
    Rows that deliberately break the cue's surface form instead declare
    ``disruption`` — the altered words present in the sentence — and no inventory
    phrase may match them.
    """

    id: str
    tag: str
    sentence: str
    hypothesis: str
    expected: str
    justification: str
    inventory_phrase: str | None = None
    disruption: str | None = None
    contested: bool = False
    contested_note: str = ""


ROWS: tuple[Row, ...] = (
    # --- quantifier negation: a subject quantifier scopes over the cue --------
    Row("qn-v2-1", "quantifier-negation",
        "Nobody on the night team noticed the binder was missing.",
        CU, ABSTAIN,
        "The quantifier denies that anyone noticed; nothing is asserted about the binder.",
        inventory_phrase="binder was missing"),
    Row("qn-v2-2", "quantifier-negation",
        "None of the porters had enough time to review every open item.",
        TP, SUPPORTS,
        "Applied to the whole set of porters this asserts the time shortage, not just its absence.",
        inventory_phrase="enough time to review every open item",
        contested=True,
        contested_note="The sufficiency cue fires here under a denial, so the guard must abstain on the "
                       "opposite surface form; a reader can also hear this as a quantitative denial "
                       "rather than an asserted shortage."),
    Row("qn-v2-3", "quantifier-negation",
        "No one claimed the system timed out.",
        PMS, ABSTAIN,
        "The quantifier negates the claiming, and a negated report asserts nothing about the timeout.",
        inventory_phrase="system timed out",
        contested=True,
        contested_note="The guard's own comment pins speech-act reports as still certifying, which "
                       "contradicts the benchmark charter's 'negated report -> ABSTAIN'."),
    Row("qn-v2-4", "quantifier-negation",
        "There was no doctor on duty, so the ward was short staffed all night.",
        SC, SUPPORTS,
        "The shortage is asserted outright in the main clause; the missing doctor is the premise.",
        inventory_phrase="short staffed"),
    Row("qn-v2-5", "quantifier-negation",
        "Nobody told the new colleague about the checklist, so the colleague was unsure.",
        TG, SUPPORTS,
        "Uncertainty is asserted of the colleague; the quantifier scopes over the telling.",
        inventory_phrase="colleague was unsure"),

    # --- verb-separated negation: the negation rides an auxiliary or a verb ---
    Row("vn-v2-1", "verb-separated-negation",
        "We did not have enough time to review every open item.",
        TP, ABSTAIN,
        "The auxiliary carries the negation, so the cue proposition is denied rather than asserted.",
        inventory_phrase="enough time to review every open item"),
    Row("vn-v2-2", "verb-separated-negation",
        "The night team did not record that the system timed out.",
        PMS, ABSTAIN,
        "Absence of a record is the claim; the timeout is not asserted or denied.",
        inventory_phrase="system timed out"),
    Row("vn-v2-3", "verb-separated-negation",
        "Our handover notes do not show the binder was missing.",
        CU, ABSTAIN,
        "The sentence is about what the notes show, which cannot certify the binder's state.",
        inventory_phrase="binder was missing"),
    Row("vn-v2-4", "verb-separated-negation",
        "The auditor had not yet verified that the checklist was available.",
        CU, ABSTAIN,
        "Not-yet-verified leaves availability undecided; the evidence gap is not a denial.",
        inventory_phrase="checklist was available"),
    Row("vn-v2-5", "verb-separated-negation",
        "The supervisor never saw that anyone was short staffed.",
        SC, ABSTAIN,
        "The negation scopes over the seeing, so staffing is neither asserted nor denied.",
        inventory_phrase="short staffed"),

    # --- evidence aboutness: the sentence is about the evidence base ----------
    Row("ev-v2-1", "evidence-aboutness",
        "The notes contain no evidence that the ward was short staffed.",
        SC, ABSTAIN,
        "About the notes, not the ward; an evidence gap is not a denial of the cue.",
        inventory_phrase="short staffed"),
    Row("ev-v2-2", "evidence-aboutness",
        "Nothing on the whiteboard indicates the system was unavailable.",
        PMS, ABSTAIN,
        "Reports what the whiteboard shows, which still cannot certify how the system ran.",
        inventory_phrase="system was unavailable"),
    Row("ev-v2-3", "evidence-aboutness",
        "There is no evidence in the file that the binder was at the desk.",
        CU, ABSTAIN,
        "A gap in the file says nothing about where the binder was.",
        inventory_phrase="binder was at the desk"),
    Row("ev-v2-4", "evidence-aboutness",
        "The audit found no sign that the shift ran out of time.",
        TP, ABSTAIN,
        "The audit's silence about timing is not an assertion that time was sufficient.",
        inventory_phrase="ran out of time"),
    Row("ev-v2-5", "evidence-aboutness",
        "Photos of the desk show nothing that suggests the binder was missing.",
        CU, ABSTAIN,
        "A photograph's silence about the binder cannot certify its presence.",
        inventory_phrase="binder was missing"),

    # --- concession: the cue sits in a concessive clause ---------------------
    Row("co-v2-1", "concession",
        "Although the binder was missing, the checklist opened normally at midday.",
        CU, ABSTAIN,
        "Both the shortage cue and its denial are asserted, so no single direction is available.",
        inventory_phrase="checklist opened normally"),
    Row("co-v2-2", "concession",
        "Even though the shift was short staffed, there were enough people on duty for the drug round.",
        SC, ABSTAIN,
        "Short staffing and sufficient staffing are both asserted of the same shift.",
        inventory_phrase="enough people on duty"),
    Row("co-v2-3", "concession",
        "Although the checklist was unavailable, the team finished the round on time.",
        CU, SUPPORTS,
        "The concessive clause still asserts the shortage; finishing on time is a different fact.",
        inventory_phrase="checklist was unavailable"),
    Row("co-v2-4", "concession",
        "The ward was short staffed, although the agency sent two nurses by noon.",
        SC, SUPPORTS,
        "The main assertion stands; the concession qualifies its duration, not its truth.",
        inventory_phrase="short staffed"),
    Row("co-v2-5", "concession",
        "While the system was unavailable, staff used the paper forms all shift.",
        PMS, SUPPORTS,
        "The outage is asserted as background; the fallback does not retract it.",
        inventory_phrase="system was unavailable"),

    # --- contrast: two clauses joined against each other --------------------
    Row("cx-v2-1", "contrast",
        "The checklist was available at nine, but it was unavailable by noon.",
        CU, ABSTAIN,
        "Two opposite states are asserted at different times, so neither direction is current.",
        inventory_phrase="checklist was available"),
    Row("cx-v2-2", "contrast",
        "The binder was at the desk at the start, but the binder was missing after lunch.",
        CU, ABSTAIN,
        "The sentence asserts both the presence and the absence; the direction is not one.",
        inventory_phrase="binder was at the desk"),
    Row("cx-v2-3", "contrast",
        "The system worked normally in the morning, but the system timed out during the afternoon handover.",
        PMS, ABSTAIN,
        "Both the normal operation and the timeout are asserted, in different periods.",
        inventory_phrase="system worked normally"),
    Row("cx-v2-4", "contrast",
        "There was enough time to review every open item, however the team ran out of time before the round.",
        TP, ABSTAIN,
        "Sufficient and insufficient time are both asserted; picking one needs a scope the words do not give.",
        inventory_phrase="ran out of time"),
    Row("cx-v2-5", "contrast",
        "The ward was short staffed, but no colleague was absent that day.",
        SC, SUPPORTS,
        "The contrast denies a cause of the shortage, not the shortage itself.",
        inventory_phrase="short staffed"),

    # --- temporal change: a later clause moves the current state ------------
    Row("tc-v2-1", "temporal-change",
        "The checklist was unavailable at eight, but it is available now.",
        CU, ABSTAIN,
        "The later clause changes the current state, so the sentence certifies neither direction now.",
        inventory_phrase="checklist was unavailable"),
    Row("tc-v2-2", "temporal-change",
        "The system timed out yesterday, but it is working normally now.",
        PMS, ABSTAIN,
        "The outage is historical and the current state is the opposite; no single direction holds.",
        inventory_phrase="system timed out"),
    Row("tc-v2-3", "temporal-change",
        "The ward was short staffed in the morning; by the afternoon there were enough people on duty.",
        SC, ABSTAIN,
        "Both staffing states are asserted of the same day, so neither is the sentence's direction.",
        inventory_phrase="enough people on duty"),
    Row("tc-v2-4", "temporal-change",
        "The binder was missing on Monday, but the binder was at the desk on Tuesday.",
        CU, ABSTAIN,
        "Presence and absence are both asserted, dated, and neither is unambiguously current.",
        inventory_phrase="binder was missing"),
    Row("tc-v2-5", "temporal-change",
        "The checklist was available all week and remains available today.",
        CU, CONTRADICTS,
        "Availability is asserted over the whole period including today, with no reversal.",
        inventory_phrase="checklist was available"),

    # --- hedge: an epistemic marker over the cue ----------------------------
    Row("hd-v2-1", "hedge",
        "Perhaps the binder was missing from the trolley.",
        CU, ABSTAIN,
        "A possibility is proposed, not asserted, so no direction is certified.",
        inventory_phrase="binder was missing"),
    Row("hd-v2-2", "hedge",
        "The system probably timed out during the save.",
        PMS, ABSTAIN,
        "Probability is not assertion; the timeout is offered, not stated.",
        inventory_phrase="system timed out",
        disruption="probably timed out"),
    Row("hd-v2-3", "hedge",
        "It seems the ward was short staffed over the weekend.",
        SC, ABSTAIN,
        "An appearance report leaves the staffing fact uncertified.",
        inventory_phrase="short staffed"),
    Row("hd-v2-4", "hedge",
        "The ward was presumably staffed by the agency, and the checklist was available at handover.",
        CU, CONTRADICTS,
        "The hedge sits in the other clause; availability itself is asserted flatly.",
        inventory_phrase="checklist was available"),
    Row("hd-v2-5", "hedge",
        "Maybe the shift ran out of time, so the checklist was unavailable.",
        CU, ABSTAIN,
        "The certainty of the consequent is inherited from a hedged premise, so the cue is not asserted.",
        inventory_phrase="checklist was unavailable",
        contested=True,
        contested_note="A reader can take the main clause as an outright assertion and the hedge as "
                       "scoping only over the premise."),

    # --- passive: the cue appears in a passive or inverted construction -----
    Row("pv-v2-1", "passive",
        "The handover was walked through by the senior nurse for the new colleague.",
        TG, SUPPORTS,
        "The walkthrough is asserted; the passive reorders it without weakening it.",
        inventory_phrase="walked through the handover",
        disruption="was walked through by"),
    Row("pv-v2-2", "passive",
        "The ward was left short staffed after two nurses called in sick.",
        SC, SUPPORTS,
        "The passive asserts the resulting shortage as a state of the ward.",
        inventory_phrase="short staffed"),
    Row("pv-v2-3", "passive",
        "The system was found to have timed out during the save.",
        PMS, SUPPORTS,
        "The timeout is asserted of the system; the reporting frame does not make it a rumour.",
        inventory_phrase="system timed out",
        disruption="found to have timed out"),
    Row("pv-v2-4", "passive",
        "The binder was reported missing by the receptionist.",
        CU, ABSTAIN,
        "A report is asserted, not the binder's state, so neither direction can be certified.",
        inventory_phrase="binder was missing",
        disruption="reported missing",
        contested=True,
        contested_note="A reviewer can treat 'reported missing' as sufficient evidence to certify support."),
    Row("pv-v2-5", "passive",
        "Enough people were on duty, as the rota required.",
        SC, CONTRADICTS,
        "Sufficient staffing is asserted; the inserted copula does not change the claim.",
        inventory_phrase="enough people on duty",
        disruption="people were on duty"),

    # --- comma splice: two clauses, one comma -------------------------------
    Row("cs-v2-1", "comma-splice",
        "Staff did not have enough training, the checklist was unavailable.",
        CU, SUPPORTS,
        "The splice leaves the second clause as an assertion; the negation does not reach it.",
        inventory_phrase="checklist was unavailable"),
    Row("cs-v2-2", "comma-splice",
        "We did not have enough time, so the checklist was unavailable.",
        CU, ABSTAIN,
        "A negated premise joined by a consequence link makes the cue's stance undecidable here.",
        inventory_phrase="checklist was unavailable"),
    Row("cs-v2-3", "comma-splice",
        "The ward was short staffed, the agency sent nobody.",
        SC, SUPPORTS,
        "The spliced clause still asserts the shortage outright.",
        inventory_phrase="short staffed"),
    Row("cs-v2-4", "comma-splice",
        "The system timed out, the clerk never recorded it.",
        PMS, SUPPORTS,
        "The timeout is asserted in the first clause and the second clause is about the record.",
        inventory_phrase="system timed out"),
    Row("cs-v2-5", "comma-splice",
        "The binder was missing, so the team used the printed checklist.",
        CU, SUPPORTS,
        "The consequence follows an affirmative premise, so the shortage is asserted.",
        inventory_phrase="binder was missing"),

    # --- cue in a question: interrogative, so nothing is asserted -----------
    Row("qu-v2-1", "cue-in-question",
        "Was the checklist unavailable during the ward round?",
        CU, ABSTAIN,
        "A question requests the fact; it does not assert either direction.",
        inventory_phrase="checklist unavailable"),
    Row("qu-v2-2", "cue-in-question",
        "Did the system time out while saving the handover notes?",
        PMS, ABSTAIN,
        "Interrogative mood over the timeout, so the direction is open.",
        inventory_phrase="system timed out",
        disruption="Did the system time out"),
    Row("qu-v2-3", "cue-in-question",
        "Was the ward short staffed on the night shift?",
        SC, ABSTAIN,
        "The shortage is only asked about here, so neither direction is asserted.",
        inventory_phrase="short staffed"),
    Row("qu-v2-4", "cue-in-question",
        "Had the team run out of time before the inspection?",
        TP, ABSTAIN,
        "A question about running out of time cannot certify time pressure.",
        inventory_phrase="ran out of time",
        disruption="run out of time"),
    Row("qu-v2-5", "cue-in-question",
        "Was the binder missing when the round started?",
        CU, ABSTAIN,
        "Interrogative over the absence; nothing is asserted about the binder.",
        inventory_phrase="binder was missing",
        disruption="binder missing"),

    # --- negated reporting verb: the saying is negated, not the thing -------
    Row("nr-v2-1", "negated-reporting-verb",
        "The senior nurse did not say the binder was missing.",
        CU, ABSTAIN,
        "The denial covers the saying; the binder's state is left unasserted.",
        inventory_phrase="binder was missing",
        contested=True,
        contested_note="The guard's inline comment claims speech-act reports keep certifying, which is "
                       "the opposite of the charter rule applied here."),
    Row("nr-v2-2", "negated-reporting-verb",
        "The registrar denied that the system timed out.",
        PMS, ABSTAIN,
        "A reported denial does not assert the timeout, and rule 2 forbids reading it as the flip.",
        inventory_phrase="system timed out"),
    Row("nr-v2-3", "negated-reporting-verb",
        "The team reported that the ward was short staffed.",
        SC, SUPPORTS,
        "An affirmative report of the cue still asserts the cue's content in a shift log.",
        inventory_phrase="short staffed"),
    Row("nr-v2-4", "negated-reporting-verb",
        "The clerk never confirmed the checklist was available.",
        CU, ABSTAIN,
        "The never covers the confirming, so availability is left undecided rather than asserted.",
        inventory_phrase="checklist was available"),
    Row("nr-v2-5", "negated-reporting-verb",
        "The auditor did not note that the shift ran out of time.",
        TP, ABSTAIN,
        "A missing note is not a claim about the shift's timing either way.",
        inventory_phrase="ran out of time"),

    # --- conditional: the cue sits inside an unreal or open condition ------
    Row("cd-v2-1", "conditional",
        "If the checklist was unavailable, the round would have been delayed.",
        CU, ABSTAIN,
        "The antecedent supposes the shortage; a supposition is not an assertion.",
        inventory_phrase="checklist was unavailable"),
    Row("cd-v2-2", "conditional",
        "Had the ward been short staffed, the agency would have sent cover.",
        SC, ABSTAIN,
        "A counterfactual antecedent states no staffing fact about the actual shift.",
        inventory_phrase="short staffed"),
    Row("cd-v2-3", "conditional",
        "The team would have run out of time if the inspection had started earlier.",
        TP, ABSTAIN,
        "The consequent is counterfactual, so no time pressure is asserted to have occurred.",
        inventory_phrase="ran out of time",
        disruption="would have run out of time"),
    Row("cd-v2-4", "conditional",
        "Unless the system timed out, the save would have completed.",
        PMS, ABSTAIN,
        "A condition on the timeout leaves its occurrence open.",
        inventory_phrase="system timed out"),
    Row("cd-v2-5", "conditional",
        "If enough people are on duty, the shift will run normally.",
        SC, ABSTAIN,
        "Sufficient staffing is a condition here, not an assertion about the shift.",
        inventory_phrase="enough people on duty",
        disruption="enough people are on duty"),

    # --- plain assertion: the anchor rows, for class denominators ----------
    Row("pa-v2-1", "plain-assertion",
        "The ward had enough people on duty throughout the night.",
        SC, CONTRADICTS,
        "Sufficient staffing is asserted flatly, with only a time adjunct.",
        inventory_phrase="enough people on duty"),
    Row("pa-v2-2", "plain-assertion",
        "The system worked normally after the upgrade.",
        PMS, CONTRADICTS,
        "Normal operation is asserted; the upgrade is background, not a hedge.",
        inventory_phrase="system worked normally"),
    Row("pa-v2-3", "plain-assertion",
        "The team walked through the handover with the new colleague.",
        TG, SUPPORTS,
        "The walkthrough is asserted of the team, with nothing negating or hedging it.",
        inventory_phrase="walked through the handover"),
    Row("pa-v2-4", "plain-assertion",
        "Two colleagues were absent on the early shift.",
        SC, SUPPORTS,
        "Two named absences assert the shortage; only the plural form differs from the cue.",
        inventory_phrase="colleague was absent",
        disruption="colleagues were absent"),
    Row("pa-v2-5", "plain-assertion",
        "The checklist was available on every trolley we checked.",
        CU, CONTRADICTS,
        "Availability is asserted across the checked set, unqualified by any contrast.",
        inventory_phrase="checklist was available"),
    Row("pa-v2-6", "plain-assertion",
        "The system was working normally during the night audit.",
        PMS, CONTRADICTS,
        "The progressive form still asserts normal operation over the audit.",
        inventory_phrase="system was working normally"),
    Row("pa-v2-7", "plain-assertion",
        "There were enough people on duty for the evening handover.",
        SC, CONTRADICTS,
        "Sufficient staffing is asserted; the handover detail is descriptive.",
        inventory_phrase="enough people on duty"),
    Row("pa-v2-8", "plain-assertion",
        "The shift had enough time to finish the audit before the deadline.",
        TP, CONTRADICTS,
        "Enough time is asserted, which is the denial of the time-pressure cue.",
        inventory_phrase="shift had enough time"),
    Row("pa-v2-9", "plain-assertion",
        "The new colleague attended the handover briefing and completed the checklist.",
        TG, CONTRADICTS,
        "The denying cue is asserted without any qualifier or report frame.",
        inventory_phrase="attended the handover briefing and completed the checklist"),
    Row("pa-v2-10", "plain-assertion",
        "The checklist opened normally, and the round started on time.",
        CU, CONTRADICTS,
        "Normal opening is asserted; the second clause adds timing, not a hedge.",
        inventory_phrase="checklist opened normally"),
)

# Frozen: the holdout is measured as declared here and is never re-split,
# re-labelled or edited after a number is reported from it.
FROZEN_ID_DIGEST = "58afcee0ce7b8aa5e609538d5006ccd4037d0c4b42d216e3950477569e2717a8"


def _pattern(phrase: str) -> str:
    return r"\s+".join(re.escape(part) for part in phrase.split())


def contains_cue(sentence: str, phrase: str) -> bool:
    """Whitespace-tolerant, case-insensitive containment, as the guard matches."""
    return re.search(_pattern(phrase), sentence, re.IGNORECASE) is not None


def _inventory(hypothesis: str, stance: str | None = None) -> tuple[str, ...]:
    cues = _CUES[hypothesis]
    phrases: list[str] = []
    for key, values in cues.items():
        if stance is not None and key.value != stance:
            continue
        phrases.extend(values)
    return tuple(phrases)


def frozen_digest(rows: tuple[Row, ...] = ROWS) -> str:
    """sha256 over ids, labels and contested flags: the frozen declaration."""
    import hashlib

    payload = "\n".join(
        f"{row.id}|{row.tag}|{row.hypothesis}|{row.expected}|"
        f"{int(row.contested)}|{row.sentence}|{row.justification}"
        for row in rows
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- consistency checks (these never call the guard) -----------------------


def test_holdout_has_at_least_45_rows() -> None:
    assert len(ROWS) >= 45, len(ROWS)


def test_ids_are_unique() -> None:
    ids = [row.id for row in ROWS]
    assert len(ids) == len(set(ids))


def test_the_split_is_frozen_and_matches_its_digest() -> None:
    assert FROZEN_ID_DIGEST != "__FILL_ME__", "freeze the digest before measuring"
    assert frozen_digest() == FROZEN_ID_DIGEST


def test_every_row_declares_a_cue_from_the_guard_inventory() -> None:
    """Every row is built on a real cue string.

    A directional row must name a cue the guard knows. Uncontested ones must name
    one of the *expected* stance, so the row really exercises that direction. A
    contested row may name the opposite stance's cue, because that is precisely
    the arguable shape: a shortage asserted through a denied sufficiency cue.
    When ``disruption`` is set the cue is the one the sentence deliberately
    breaks, so it must *not* be found verbatim.
    """
    for row in ROWS:
        assert row.hypothesis in _CUES, row.id
        if row.inventory_phrase is None:
            assert row.expected == ABSTAIN and row.disruption, (
                f"{row.id}: only a disrupted abstention may omit its near cue"
            )
            continue
        assert row.inventory_phrase in _inventory(row.hypothesis), (
            f"{row.id}: {row.inventory_phrase!r} is not an inventory cue"
        )
        if row.expected in (SUPPORTS, CONTRADICTS) and not row.contested:
            assert row.inventory_phrase in _inventory(row.hypothesis, row.expected), (
                f"{row.id}: {row.inventory_phrase!r} is not an inventory cue for {row.expected}"
            )
        if row.disruption is not None:
            assert row.disruption.lower() in row.sentence.lower(), row.id
            assert not contains_cue(row.sentence, row.inventory_phrase), (
                f"{row.id}: a disrupted row must not match {row.inventory_phrase!r} verbatim"
            )
        else:
            assert contains_cue(row.sentence, row.inventory_phrase), (
                f"{row.id}: sentence does not contain {row.inventory_phrase!r}"
            )


def test_a_disrupted_row_really_breaks_the_cue() -> None:
    """The near-miss rows must not accidentally match a whole inventory cue."""
    disrupted = [row for row in ROWS if row.disruption is not None]
    assert len(disrupted) >= 5, "several rows must exercise a broken cue surface form"
    for row in disrupted:
        assert row.disruption.lower() in row.sentence.lower(), row.id
        matched = [phrase for phrase in _inventory(row.hypothesis)
                   if contains_cue(row.sentence, phrase)]
        assert not matched, f"{row.id}: unexpectedly matches {matched}"


def test_every_row_carries_a_justification_a_reader_can_disagree_with() -> None:
    for row in ROWS:
        assert len(row.justification.split()) >= 8, row.id
        assert row.justification.strip().endswith("."), row.id


def test_every_class_and_every_named_phenomenon_has_a_denominator() -> None:
    seen_classes = {row.expected for row in ROWS}
    assert seen_classes == set(CLASSES), seen_classes
    seen_tags = {row.tag for row in ROWS}
    missing = set(NAMED_TAGS) - seen_tags
    assert not missing, f"phenomena without a row: {sorted(missing)}"


def test_contested_rows_say_why_they_are_contested() -> None:
    for row in ROWS:
        if row.contested:
            assert len(row.contested_note.split()) >= 6, row.id


# --- measurement ----------------------------------------------------------


def observe(row: Row) -> dict:
    """The guard's answer for one row, with ``NEUTRAL`` folded into ABSTAIN."""
    detail = reviewed_relation_details(row.sentence, row.hypothesis)
    relation = detail["relation"]
    label = ABSTAIN if relation is None or relation is Stance.NEUTRAL else relation.value
    return {
        "label": label,
        "reason_code": detail["reason_code"],
        "cue_ids": detail["cue_ids"],
    }


def score(rows) -> dict:
    rows = tuple(rows)
    confusion = {expected: {seen: 0 for seen in CLASSES} for expected in CLASSES}
    for row in rows:
        confusion[row.expected][observe(row)["label"]] += 1
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


def misreads(rows) -> list[tuple[Row, dict]]:
    return [(row, observe(row)) for row in rows if observe(row)["label"] != row.expected]


def format_report() -> str:
    uncontested = tuple(row for row in ROWS if not row.contested)
    contested = tuple(row for row in ROWS if row.contested)
    lines = []
    for name, rows in (("all", ROWS), ("uncontested", uncontested), ("contested", contested)):
        measured = score(rows)
        accuracy = f"{measured['accuracy']:.3f}" if measured["accuracy"] is not None else "n/a"
        lines.append(f"[{name}] accuracy {measured['correct']}/{measured['total']} = {accuracy}")
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
    lines.append("")
    errors = misreads(uncontested)
    lines.append(f"uncontested misreads {len(errors)}/{len(uncontested)}")
    for row, seen in errors:
        lines.append(f"  {row.id} [{row.tag}] expected {row.expected}, saw {seen['label']} "
                     f"({seen['reason_code']})")
    counts: dict[str, int] = {}
    for row, _seen in errors:
        counts[row.tag] = counts.get(row.tag, 0) + 1
    lines.append("uncontested misreads by tag: "
                 + (", ".join(f"{tag} {n}" for tag, n in
                              sorted(counts.items(), key=lambda item: (-item[1], item[0])))
                    if counts else "none"))
    lines.append("")
    lines.append(f"contested rows ({len(contested)}) reported separately:")
    for row in contested:
        seen = observe(row)["label"]
        lines.append(f"  {row.id} [{row.tag}] expected {row.expected}, saw {seen}: "
                     f"{row.contested_note}")
    return "\n".join(lines)


def test_the_holdout_is_measured() -> None:
    measured = score(ROWS)
    assert measured["total"] >= 45
    assert all(measured["per_class"][cls]["actual"] > 0 for cls in CLASSES)
    print(format_report())


if __name__ == "__main__":  # pragma: no cover - reporting entry point
    print(format_report())
