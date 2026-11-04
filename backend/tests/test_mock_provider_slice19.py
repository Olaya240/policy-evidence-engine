"""Slice 19: the seed corpus the rest of the suite silently assumes, and the two
things `MockProvider` promises about what it asks for and what it cites.

`app/mock_provider.py` is a fixture, but half the suite is written against it.
`test_architecture_invariants.py` runs `investigate(SEED_RECORDS)` and expects one
claim per hypothesis; `test_engine.py` picks `next(r for r in SEED_RECORDS if
r.restricted)` and expects exactly one canary, and picks `OPS-108` by id expecting
`CHECKLIST_UNAVAILABLE` to have an assessment for it; the coverage and
`source_group` work assumes a record can declare a group naming another record.
Any of those assumptions can be broken by editing one line of the corpus, and
nothing else fails with a message that says so. This file pins them.

Corpus invariants pinned
------------------------
* ids unique, so `{record.id: record}` is a faithful index (engine builds one).
* exactly one restricted canary, whose text is never quoted by any hypothesis.
* every seed text non-empty, and every *non-restricted* text is quoted verbatim
  by at least one hypothesis — an unquoted record silently drops out of the
  evidence set, and a claim built from a corpus that no longer supports it still
  returns a status.
* every department non-empty (evidence rows and the department rollup key on it).
* exactly one record declares `source_group`, it names an existing other record,
  and that record declares none — so the engine's `source_group or id` fallback
  produces exactly one dependent pair and ten singletons.
* timestamps: the ten-record body is chronological in corpus order, and the only
  two out-of-order records are the deliberately stale one (`OPS-109`) and the
  recap of `OPS-105` (`OPS-112`), which is dated *after* the record it recaps.
  **The corpus as a whole is not sorted** — the brief asked for "timestamps
  ordered", and that is false as stated; what holds is the narrower claim above.
  This module pins the narrower claim rather than a sortedness assertion that
  would fail.
* freshness: the fresh body spans less than `STALE_DAYS`, and at a clock after
  the newest record exactly one record (`OPS-109`) is stale and none is
  future-dated. That is what lets the suite evaluate the corpus at a single
  fixed clock.

Provider behaviour pinned
-------------------------
* `assess` refuses an unknown hypothesis id before it records the call, so a
  typo cannot reach `HYPOTHESIS_KEYWORDS[...]` as a `KeyError` and cannot consume
  a fixture output; `HYPOTHESIS_KEYWORDS` covers exactly the known set.
* `assess` cites only records it was given, on the default (fixture-free) path:
  every returned `source_record_id` is in the input, and the quote is that
  record's own text. `HYPOTHESIS_KEYWORDS` values alone can never satisfy that,
  because the keyword branch keys off the given record's text.

Scope of the second guarantee, pinned by test: a configured `assessment_overrides`
entry is echoed back verbatim, including a proposal naming a record the caller
never passed. The provider is not the enforcement point for that — engine.py's
`_validate_provider_proposals` / `MandatoryProviderBoundary` is.
"""
from datetime import datetime, timedelta, timezone
from itertools import combinations

import pytest

from app.engine import STALE_DAYS, _is_stale
from app.mock_provider import HYPOTHESIS_KEYWORDS, SEED_RECORDS, MockProvider, assess_pair
from app.models import HYPOTHESES, Stance

CLOCK = datetime(2026, 10, 25, 0, 0, tzinfo=timezone.utc)

CANARY_ID = "CANARY-RESTRICTED-001"
STALE_OUTLIER = "OPS-109"
COPIED_RECAP = "OPS-112"
RECAP_SOURCE = "OPS-105"

# The chronological body, in corpus order: everything but the stale winter
# record, the recap of OPS-105, and the canary.
BODY_IDS = ["OPS-101", "OPS-102", "OPS-103", "OPS-104", "OPS-105",
            "OPS-106", "OPS-107", "OPS-108", "OPS-110", "OPS-111"]

KNOWN = {hypothesis.id for hypothesis in HYPOTHESES}


def by_id(record_id):
    return next(record for record in SEED_RECORDS if record.id == record_id)


def quoters():
    """(hypothesis id, record id) pairs the default provider actually quotes."""
    provider = MockProvider()
    pairs = []
    for hypothesis_id in sorted(KNOWN):
        for assessment in provider.assess(SEED_RECORDS, hypothesis_id):
            pairs.append((hypothesis_id, assessment["source_record_id"]))
    return pairs


# ---------------------------------------------------------------- corpus


def test_seed_record_ids_are_unique():
    ids = [record.id for record in SEED_RECORDS]

    assert len(ids) == len(set(ids))


def test_exactly_one_restricted_canary():
    restricted = [record for record in SEED_RECORDS if record.restricted]

    assert [record.id for record in restricted] == [CANARY_ID]
    assert restricted[0].text


def test_canary_is_never_quoted_and_every_other_text_is():
    quoted = {record_id for _hypothesis, record_id in quoters()}

    assert CANARY_ID not in quoted
    assert quoted == {record.id for record in SEED_RECORDS if not record.restricted}


def test_every_quote_is_the_whole_non_empty_text_of_the_record_it_cites():
    provider = MockProvider()

    for hypothesis_id in sorted(KNOWN):
        for assessment in provider.assess(SEED_RECORDS, hypothesis_id):
            record = by_id(assessment["source_record_id"])
            assert record.text.strip(), record.id
            assert assessment["quote"] == record.text
            assert assessment["quote"] in record.text
            assert assessment["stance"] in {stance.value for stance in Stance}


def test_every_seed_record_has_a_non_empty_department():
    assert [record.id for record in SEED_RECORDS if not record.department.strip()] == []


def test_exactly_one_record_declares_a_source_group_naming_another_record():
    declaring = [record for record in SEED_RECORDS if record.source_group]

    assert [(record.id, record.source_group) for record in declaring] == [(COPIED_RECAP, RECAP_SOURCE)]
    recap, source = by_id(COPIED_RECAP), by_id(RECAP_SOURCE)
    assert source.source_group is None
    assert RECAP_SOURCE in recap.text
    # The recap restates the source, so nothing in its text is independent of it.
    assert recap.department == source.department


def test_the_engine_group_fallback_yields_one_dependent_pair_and_ten_singletons():
    groups = {}
    for record in SEED_RECORDS:
        groups.setdefault(record.source_group or record.id, []).append(record.id)

    dependent = {group: ids for group, ids in groups.items() if len(ids) > 1}
    assert dependent == {RECAP_SOURCE: [RECAP_SOURCE, COPIED_RECAP]}
    assert len(groups) == len(SEED_RECORDS) - 1


def test_the_body_is_chronological_and_only_two_deliberate_records_break_corpus_order():
    body = [record for record in SEED_RECORDS if record.id in BODY_IDS]

    assert [record.id for record in body] == BODY_IDS
    assert [record.timestamp for record in body] == sorted(record.timestamp for record in body)
    assert len({record.timestamp for record in body}) == len(BODY_IDS)

    # Not "the corpus is sorted" — it is not. The only records dated before a
    # record that precedes them are the deliberately stale one and the recap of
    # an earlier record.
    out_of_place, running = [], None
    for record in SEED_RECORDS:
        if running is not None and record.timestamp < running:
            out_of_place.append(record.id)
        running = record.timestamp if running is None else max(running, record.timestamp)
    assert out_of_place == [STALE_OUTLIER, COPIED_RECAP]
    assert by_id(COPIED_RECAP).timestamp > by_id(RECAP_SOURCE).timestamp


def test_the_fresh_body_spans_less_than_the_staleness_window():
    body = [record for record in SEED_RECORDS if record.id != STALE_OUTLIER]
    span = max(record.timestamp for record in body) - min(record.timestamp for record in body)

    assert span < timedelta(days=STALE_DAYS)
    assert CLOCK >= max(record.timestamp for record in SEED_RECORDS)


def test_at_the_pinned_clock_exactly_the_stale_outlier_is_stale_and_none_is_future_dated():
    stale = {record.id for record in SEED_RECORDS if _is_stale(record.timestamp, CLOCK)}
    future_dated = {record.id for record in SEED_RECORDS if record.timestamp > CLOCK}

    assert stale == {STALE_OUTLIER}
    assert future_dated == set()
    # ... and the same holds a week later, so the choice of clock is not load-bearing.
    later = CLOCK + timedelta(days=7)
    assert {record.id for record in SEED_RECORDS if _is_stale(record.timestamp, later)} == {STALE_OUTLIER}
    # The outlier is stale for a reason this corpus intends, and it is far outside.
    assert (CLOCK - by_id(STALE_OUTLIER).timestamp).days > 365


# ------------------------------------------------------------- behaviour


@pytest.mark.parametrize("hypothesis_id", ["NOT_A_HYPOTHESIS", "checklist_unavailable", "", None, b"CHECKLIST_UNAVAILABLE", 0])
def test_an_unknown_hypothesis_is_refused_before_any_call_is_recorded(hypothesis_id):
    provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [{"source_record_id": "OPS-101", "quote": by_id("OPS-101").text, "stance": "SUPPORTS", "rationale": "fixture"}]})

    with pytest.raises(ValueError):
        provider.assess(SEED_RECORDS, hypothesis_id)

    assert provider.assessment_call_count == 0
    assert provider.assessment_history == ()


def test_only_known_hypotheses_are_ever_asked_for():
    provider = MockProvider()

    for hypothesis_id in sorted(KNOWN):
        provider.assess(SEED_RECORDS, hypothesis_id)

    assert set(provider.assessment_history) == KNOWN
    assert provider.assessment_call_count == len(KNOWN)


def test_the_keyword_table_covers_exactly_the_known_hypotheses():
    assert set(HYPOTHESIS_KEYWORDS) == KNOWN
    assert all(keywords for keywords in HYPOTHESIS_KEYWORDS.values())


@pytest.mark.parametrize("size", [0, 1, 2, 5])
def test_assess_cites_only_records_it_was_given(size):
    pool = [by_id(record_id) for record_id in ("OPS-101", "OPS-103", "OPS-105", "OPS-107", "OPS-110")]
    provider = MockProvider()

    for subset in combinations(pool, size):
        given = {record.id: record for record in subset}
        for hypothesis_id in sorted(KNOWN):
            for assessment in provider.assess(list(subset), hypothesis_id):
                cited = assessment["source_record_id"]
                assert cited in given, (size, hypothesis_id, cited)
                assert assessment["quote"] == given[cited].text


def test_a_restricted_record_alone_yields_no_proposal():
    canary = by_id(CANARY_ID)
    provider = MockProvider()

    for hypothesis_id in sorted(KNOWN):
        assert provider.assess([canary], hypothesis_id) == []


def test_every_cited_id_across_the_whole_corpus_is_a_seed_record():
    corpus_ids = {record.id for record in SEED_RECORDS}

    assert {record_id for _hypothesis, record_id in quoters()} <= corpus_ids


def test_assess_pair_cites_the_record_it_was_handed_even_for_a_keyword_only_match():
    given = by_id("OPS-104")  # "team members" keyword, no explicit mapping for this pair

    assessment = assess_pair(given, "STAFFING_CONSTRAINTS")

    assert assessment is not None
    assert assessment["source_record_id"] == given.id
    assert assessment["quote"] == given.text
    assert assessment["stance"] == Stance.NEUTRAL.value


def test_a_configured_override_citing_an_ungiven_record_is_refused():
    """Fixtures are now held to the same provenance rule as the default path.

    This test used to assert the opposite — that a fixture naming `INVENTED` was
    echoed verbatim and left to the boundary. That made the provider itself a
    source of fabricated citations, which is the one thing the boundary exists to
    prevent; the fix moved the check to the producer.
    """
    bogus = {"source_record_id": "INVENTED", "quote": "a fabricated quote", "stance": "SUPPORTS", "rationale": "fixture"}
    provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [bogus]})

    with pytest.raises(Exception) as excinfo:
        provider.assess([by_id("OPS-101")], "CHECKLIST_UNAVAILABLE")

    assert getattr(excinfo.value, "code", None) == "invalid_source"
