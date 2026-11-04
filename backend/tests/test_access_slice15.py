"""Contract of the explicit default-deny record filter (slice 15).

`visible_records` is the filter applied by the `/api/records` handler, and that
call site passes no context (`app/main.py:107`:
`return visible_records(store.list_records())`), so the deny path is the one the
application actually serves.

Pinned here:

* the filter removes records flagged `restricted` and nothing else -- not by
  text, department, tags or source group, and without reordering;
* it does not mutate, and does not alias, the caller's list;
* an empty input is safe under both contexts.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.access import AccessContext, visible_records
from app.models import Record


def record(rid: str, *, restricted: bool = False, text: str = "synthetic note",
           department: str = "Front Office", tags: list[str] | None = None,
           source_group: str | None = None) -> Record:
    return Record(
        id=rid,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        department=department,
        text=text,
        tags=tags if tags is not None else [],
        restricted=restricted,
        source_group=source_group,
    )


@pytest.fixture()
def mixed() -> list[Record]:
    return [
        record("open-1"),
        record("secret-1", restricted=True),
        record("open-2", department="Compliance", tags=["audit"]),
        record("secret-2", restricted=True, source_group="group-a"),
        record("open-3", source_group="group-a"),
    ]


def test_default_context_hides_exactly_the_restricted_records(mixed):
    visible = visible_records(mixed)
    assert [item.id for item in visible] == ["open-1", "open-2", "open-3"]


def test_explicit_context_none_is_the_default_deny_path(mixed):
    assert [item.id for item in visible_records(mixed, None)] == [
        item.id for item in visible_records(mixed)
    ]


def test_explicit_deny_context_matches_the_default_path(mixed):
    assert [item.id for item in visible_records(mixed, AccessContext())] == [
        item.id for item in visible_records(mixed)
    ]
    assert [item.id for item in visible_records(mixed, AccessContext(can_view_restricted=False))] == [
        "open-1", "open-2", "open-3",
    ]


def test_allow_context_returns_every_record_in_original_order(mixed):
    visible = visible_records(mixed, AccessContext(can_view_restricted=True))
    assert [item.id for item in visible] == [item.id for item in mixed]
    # No duplication and no substitution: same objects, same positions.
    assert all(seen is source for seen, source in zip(visible, mixed, strict=True))


def test_filter_keeps_the_same_record_objects(mixed):
    visible = visible_records(mixed)
    assert visible[0] is mixed[0]
    assert visible[1] is mixed[2]
    assert visible[2] is mixed[4]


def test_filter_is_keyed_on_the_flag_not_on_text_or_metadata():
    """A visible record carrying restricted-looking text still passes."""
    canary_text = "CANARY-RESTRICTED-001"
    records = [
        record("visible-with-canary", text=canary_text),
        record("hidden", text="ordinary text", restricted=True),
    ]
    visible = visible_records(records)
    assert [item.id for item in visible] == ["visible-with-canary"]
    assert visible[0].text == canary_text


def test_filter_ignores_department_tags_and_source_group():
    records = [
        record(f"open-{index}", department=department, tags=[department.lower()],
               source_group=group)
        for index, department, group in [
            (0, "Front Office", None),
            (1, "Compliance", "group-a"),
            (2, "Finance", "group-b"),
            (3, "Security", None),
        ]
    ]
    assert [item.id for item in visible_records(records)] == [
        "open-0", "open-1", "open-2", "open-3",
    ]


def test_input_list_is_not_mutated_and_the_result_is_a_new_list(mixed):
    before = [item.model_copy(deep=True) for item in mixed]
    before_ids = [item.id for item in mixed]

    visible = visible_records(mixed)

    assert [item.id for item in mixed] == before_ids
    assert [item.model_dump() for item in mixed] == [item.model_dump() for item in before]
    assert visible is not mixed
    # Nothing restricted was re-flagged in place to achieve the filtering.
    assert sum(1 for item in mixed if item.restricted) == 2


def test_result_is_never_the_input_list_even_when_nothing_is_filtered():
    records = [record("open-1"), record("open-2")]
    visible = visible_records(records)
    assert visible is not records
    visible.append(record("caller-owned"))
    assert [item.id for item in records] == ["open-1", "open-2"]


def test_empty_input_returns_empty_list_under_every_context():
    for context in (None, AccessContext(), AccessContext(can_view_restricted=True)):
        assert visible_records([], context) == []


def test_all_restricted_input_yields_empty_under_deny_and_all_under_allow():
    records = [record("secret-1", restricted=True), record("secret-2", restricted=True)]
    assert visible_records(records) == []
    assert len(visible_records(records, AccessContext(can_view_restricted=True))) == 2


def test_no_restricted_records_yields_everything_under_deny():
    records = [record("open-1"), record("open-2")]
    assert [item.id for item in visible_records(records)] == ["open-1", "open-2"]


def test_repeated_calls_are_idempotent_on_the_same_input(mixed):
    first = visible_records(mixed)
    second = visible_records(mixed)
    assert [item.id for item in first] == [item.id for item in second]
    assert visible_records(first) == first


def test_access_context_defaults_to_deny():
    assert AccessContext().can_view_restricted is False


def test_access_context_is_immutable_so_a_policy_cannot_be_flipped():
    context = AccessContext()
    with pytest.raises(FrozenInstanceError):
        context.can_view_restricted = True
    assert context.can_view_restricted is False


def test_record_restricted_flag_defaults_to_false_and_survives_deny():
    unset = Record(
        id="no-flag",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        department="Front Office",
        text="synthetic note",
        tags=[],
    )
    assert unset.restricted is False
    assert [item.id for item in visible_records([unset])] == ["no-flag"]
