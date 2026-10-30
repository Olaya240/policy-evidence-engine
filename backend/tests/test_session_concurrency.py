"""Concurrency tests for InMemoryDemoSessionManager (SEC-03 — threading.RLock).

Verifies that concurrent session creation, event recording, reset, and history
snapshot operations are free from data corruption, counter drift, and exception leaks.

Safety:
- No external network calls; purely in-process unit tests.
- No file I/O; purely in-memory object manipulation.
- Uses threading.Thread and threading.Barrier for deterministic coordination.
- Ephemeral manager instances isolated per test via fixture.
"""
from __future__ import annotations

from collections import OrderedDict
import threading
from typing import Any

import pytest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from policy_demo_session import (
    AuditTrailEvent,
    InMemoryDemoSessionManager,
    MAX_EVENTS_PER_SESSION,
    MAX_SESSIONS,
    PolicySessionError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mgr() -> InMemoryDemoSessionManager:
    """Return a fresh manager with default limits for each test."""
    return InMemoryDemoSessionManager()


@pytest.fixture()
def small_mgr() -> InMemoryDemoSessionManager:
    """Return a manager with tight limits for boundary tests."""
    return InMemoryDemoSessionManager(max_sessions=5, max_events=5)


def _record_event(
    mgr: InMemoryDemoSessionManager,
    session_id: str,
    errors: list[Exception],
    results: list[AuditTrailEvent],
    barrier: threading.Barrier | None = None,
) -> None:
    """Thread worker: optionally wait at barrier then record one challenge event."""
    if barrier is not None:
        barrier.wait()
    try:
        event = mgr.record_challenge_event(
            session_id=session_id,
            scenario_id="scheduling",
            target_department="HOUSEKEEPING",
            target_side="employer",
            applicability_status="APPLICABLE",
            initial_relation="COMPATIBLE_CHANGE",
            recomputed_relation="COMPATIBLE_CHANGE",
            core_classification="COMPATIBLE_CHANGE",
            uncertainty_reasons=[],
            contract_enforced=False,
            summary="Concurrent test event",
        )
        results.append(event)
    except Exception as exc:
        errors.append(exc)


# ---------------------------------------------------------------------------
# SEC-03 — Concurrent event recording
# ---------------------------------------------------------------------------

def test_concurrent_event_recording_no_corruption(mgr: InMemoryDemoSessionManager) -> None:
    """10 concurrent threads each record one event; no corruption, no exceptions."""
    session = mgr.create_session("scheduling")
    sid = session.session_id

    n_threads = 10
    errors: list[Exception] = []
    results: list[AuditTrailEvent] = []
    barrier = threading.Barrier(n_threads)

    threads = [
        threading.Thread(target=_record_event, args=(mgr, sid, errors, results, barrier))
        for _ in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == [], f"Concurrent recording raised exceptions: {errors}"
    # All events were recorded (within the max_events cap)
    assert len(results) == n_threads


def test_concurrent_event_sequence_numbers_are_unique(mgr: InMemoryDemoSessionManager) -> None:
    """Sequence numbers assigned concurrently are all unique (no duplicate counter assignment)."""
    session = mgr.create_session("scheduling")
    sid = session.session_id

    n_threads = 8
    errors: list[Exception] = []
    results: list[AuditTrailEvent] = []
    barrier = threading.Barrier(n_threads)

    threads = [
        threading.Thread(target=_record_event, args=(mgr, sid, errors, results, barrier))
        for _ in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
    seq_numbers = [e.sequence_number for e in results]
    assert len(seq_numbers) == len(set(seq_numbers)), (
        f"Duplicate sequence numbers under concurrent access: {sorted(seq_numbers)}"
    )


def test_event_fifo_limit_enforced_under_concurrent_writes(small_mgr: InMemoryDemoSessionManager) -> None:
    """Session never exceeds max_events=5 under concurrent writes from 15 threads."""
    session = small_mgr.create_session("scheduling")
    sid = session.session_id

    n_threads = 15
    errors: list[Exception] = []
    results: list[AuditTrailEvent] = []
    barrier = threading.Barrier(n_threads)

    threads = [
        threading.Thread(target=_record_event, args=(small_mgr, sid, errors, results, barrier))
        for _ in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
    final_history = small_mgr.get_history_snapshot(sid)
    assert len(final_history) <= small_mgr.max_events, (
        f"Events exceed cap: {len(final_history)} > {small_mgr.max_events}"
    )


# ---------------------------------------------------------------------------
# SEC-03 — Concurrent reset vs. recording
# ---------------------------------------------------------------------------

def test_concurrent_reset_and_record_no_exception_leak(mgr: InMemoryDemoSessionManager) -> None:
    """Concurrent reset and record do not raise unhandled exceptions."""
    session = mgr.create_session("scheduling")
    sid = session.session_id

    record_errors: list[Exception] = []
    reset_errors: list[Exception] = []
    n_recorders = 6
    barrier = threading.Barrier(n_recorders + 1)  # +1 for reset thread

    def reset_worker() -> None:
        barrier.wait()
        try:
            mgr.reset_session(sid)
        except PolicySessionError:
            pass  # race with a concurrent reset is acceptable
        except Exception as exc:
            reset_errors.append(exc)

    record_results: list[AuditTrailEvent] = []
    record_threads = [
        threading.Thread(target=_record_event, args=(mgr, sid, record_errors, record_results, barrier))
        for _ in range(n_recorders)
    ]
    reset_thread = threading.Thread(target=reset_worker)

    for t in record_threads:
        t.start()
    reset_thread.start()

    for t in record_threads:
        t.join(timeout=5.0)
    reset_thread.join(timeout=5.0)

    assert record_errors == [], f"Unexpected record errors: {record_errors}"
    assert reset_errors == [], f"Unexpected reset errors: {reset_errors}"


# ---------------------------------------------------------------------------
# SEC-03 — History snapshot isolation
# ---------------------------------------------------------------------------

def test_history_snapshot_isolates_from_subsequent_reset(mgr: InMemoryDemoSessionManager) -> None:
    """A snapshot taken before reset is not mutated by the subsequent reset."""
    session = mgr.create_session("scheduling")
    sid = session.session_id

    # Record 3 events
    for _ in range(3):
        _record_event(mgr, sid, [], [], barrier=None)

    snapshot_before_reset = mgr.get_history_snapshot(sid)
    assert len(snapshot_before_reset) == 3

    # Reset the session
    mgr.reset_session(sid)

    # Snapshot taken before reset must not be altered
    assert len(snapshot_before_reset) == 3, (
        "Snapshot was mutated by a subsequent reset — isolation is broken."
    )


def test_history_snapshot_is_independent_list(mgr: InMemoryDemoSessionManager) -> None:
    """Snapshot is a new list; mutating it does not affect the live session events list."""
    session = mgr.create_session("scheduling")
    sid = session.session_id
    _record_event(mgr, sid, [], [], barrier=None)

    snapshot = mgr.get_history_snapshot(sid)
    snapshot.clear()  # mutate the returned snapshot

    live_history = mgr.get_history_snapshot(sid)
    assert len(live_history) == 1, (
        "Clearing the snapshot list corrupted the live session events list."
    )


def test_combined_history_snapshot_is_immutable_and_detached(mgr: InMemoryDemoSessionManager) -> None:
    sid = mgr.create_session("scheduling").session_id
    _record_event(mgr, sid, [], [], None)
    snapshot = mgr.get_session_history_snapshot(sid)
    assert isinstance(snapshot.events, tuple)
    assert len(snapshot.events) == 1
    with pytest.raises((AttributeError, TypeError)):
        snapshot.metadata.scenario_id = "uniform_grooming"  # type: ignore[misc]
    mgr.reset_session(sid)
    assert len(snapshot.events) == 1
    assert snapshot.metadata.history_count == 1


def test_history_snapshots_during_concurrent_reset_and_record(mgr: InMemoryDemoSessionManager) -> None:
    """Concurrent snapshots remain detached and operations complete without errors."""
    sid = mgr.create_session("scheduling").session_id
    barrier = threading.Barrier(3)
    errors: list[Exception] = []
    snapshots: list[list[AuditTrailEvent]] = []

    def snapshot_worker() -> None:
        barrier.wait()
        try:
            snapshots.append(mgr.get_history_snapshot(sid))
        except Exception as exc:
            errors.append(exc)

    def reset_worker() -> None:
        barrier.wait()
        try:
            mgr.reset_session(sid)
        except Exception as exc:
            errors.append(exc)

    def record_worker() -> None:
        barrier.wait()
        try:
            _record_event(mgr, sid, errors, [], None)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for worker in (snapshot_worker, reset_worker, record_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert errors == []
    assert len(snapshots) == 1
    snapshots[0].clear()
    assert len(mgr.get_history_snapshot(sid)) in (0, 1)


# ---------------------------------------------------------------------------
# SEC-03 — Concurrent session creation up to capacity limit
# ---------------------------------------------------------------------------

def test_concurrent_session_creation_at_limit(small_mgr: InMemoryDemoSessionManager) -> None:
    """Concurrent creation of max_sessions+5 sessions never raises unhandled exceptions
    and the manager never holds more than max_sessions sessions."""
    max_s = small_mgr.max_sessions  # 5
    n_threads = max_s + 5  # 10 concurrent creators

    errors: list[Exception] = []
    created_ids: list[str] = []
    barrier = threading.Barrier(n_threads)

    def create_worker() -> None:
        barrier.wait()
        try:
            session = small_mgr.create_session("scheduling")
            created_ids.append(session.session_id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == [], f"Session creation raised unexpected errors: {errors}"
    # Internal dict must never exceed max_sessions
    assert len(small_mgr._sessions) <= max_s, (
        f"Session manager holds {len(small_mgr._sessions)} sessions, exceeds cap {max_s}."
    )


def test_fifo_session_eviction_preserves_retained_sessions_under_manager_lock() -> None:
    class TrackingRLock:
        def __init__(self) -> None:
            self._lock = threading.RLock()
            self._local = threading.local()

        def __enter__(self):
            self._lock.acquire()
            self._local.depth = getattr(self._local, "depth", 0) + 1
            return self

        def __exit__(self, *_args):
            self._local.depth -= 1
            self._lock.release()

        def held_by_current_thread(self) -> bool:
            return getattr(self._local, "depth", 0) > 0

    class LockCheckingSessions(OrderedDict):
        def __init__(self, lock: TrackingRLock) -> None:
            super().__init__()
            self.lock = lock
            self.eviction_lock_checks = 0

        def popitem(self, last: bool = True):
            assert self.lock.held_by_current_thread(), "session eviction ran without the manager lock"
            self.eviction_lock_checks += 1
            return super().popitem(last=last)

    mgr = InMemoryDemoSessionManager(max_sessions=2, max_events=3)
    observed_lock = TrackingRLock()
    tracked_sessions = LockCheckingSessions(observed_lock)
    mgr._lock = observed_lock
    mgr._sessions = tracked_sessions

    oldest = mgr.create_session("scheduling")
    retained = mgr.create_session("uniform_grooming")
    retained_event = mgr.record_challenge_event(
        session_id=retained.session_id,
        scenario_id="uniform_grooming",
        target_department="CONCIERGE",
        target_side="OLDER",
        applicability_status="UNGROUNDED",
        initial_relation="CONTRADICTION",
        recomputed_relation="INCONCLUSIVE",
        core_classification="INCONCLUSIVE",
        uncertainty_reasons=["synthetic_reason"],
        contract_enforced=True,
        summary="Retained history",
    )
    retained_before = mgr.get_session_history_snapshot(retained.session_id)

    newest = mgr.create_session("lounge_access")
    newest_event = mgr.record_challenge_event(
        session_id=newest.session_id,
        scenario_id="lounge_access",
        target_department="SECURITY",
        target_side="NEWER",
        applicability_status="UNGROUNDED",
        initial_relation="SCOPE_OR_TIME_DIFFERENCE",
        recomputed_relation="INCONCLUSIVE",
        core_classification="INCONCLUSIVE",
        uncertainty_reasons=["synthetic_reason"],
        contract_enforced=True,
        summary="Newest history",
    )

    with pytest.raises(PolicySessionError) as evicted:
        mgr.get_session(oldest.session_id)
    assert evicted.value.code == "session_not_found"
    assert tracked_sessions.eviction_lock_checks == 1

    retained_after = mgr.get_session_history_snapshot(retained.session_id)
    newest_after = mgr.get_session_history_snapshot(newest.session_id)
    assert retained_after.metadata.scenario_id == "uniform_grooming"
    assert retained_after.events == retained_before.events == (retained_event,)
    assert newest_after.metadata.scenario_id == "lounge_access"
    assert newest_after.events == (newest_event,)


# ---------------------------------------------------------------------------
# SEC-03 — Total event counter monotonicity under concurrent writes
# ---------------------------------------------------------------------------

def test_total_events_counter_monotone_under_concurrent_writes(mgr: InMemoryDemoSessionManager) -> None:
    """total_events counter never decreases and reflects total challenges submitted (pre-eviction)."""
    session = mgr.create_session("scheduling")
    sid = session.session_id

    n_threads = 12
    errors: list[Exception] = []
    results: list[AuditTrailEvent] = []
    barrier = threading.Barrier(n_threads)

    threads = [
        threading.Thread(target=_record_event, args=(mgr, sid, errors, results, barrier))
        for _ in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
    final_session = mgr.get_session(sid)
    # total_events == n_threads (counts all, before eviction)
    assert final_session.total_events == n_threads, (
        f"Expected total_events={n_threads}, got {final_session.total_events}"
    )
    # The in-window events have sequence numbers within the expected range
    for event in mgr.get_history_snapshot(sid):
        assert 1 <= event.sequence_number <= n_threads


def test_get_session_returns_immutable_metadata_not_internal_state(mgr: InMemoryDemoSessionManager) -> None:
    session = mgr.create_session("scheduling")
    assert not hasattr(session, "events")
    assert session.total_events == 0
    with pytest.raises((AttributeError, TypeError)):
        session.scenario_id = "uniform_grooming"  # type: ignore[misc]


def test_invalid_reset_scenario_preserves_existing_history(mgr: InMemoryDemoSessionManager) -> None:
    sid = mgr.create_session("scheduling").session_id
    _record_event(mgr, sid, [], [], None)
    before = mgr.get_history_snapshot(sid)
    with pytest.raises(PolicySessionError):
        mgr.reset_session(sid, new_scenario_id="unknown")
    assert mgr.get_history_snapshot(sid) == before


# ---------------------------------------------------------------------------
# SEC-03 — clear_all under concurrent access
# ---------------------------------------------------------------------------

def test_clear_all_concurrent_no_exception(mgr: InMemoryDemoSessionManager) -> None:
    """clear_all() while concurrent sessions are being created doesn't corrupt state."""
    session_ids: list[str] = []
    errors: list[Exception] = []
    n_threads = 8
    barrier = threading.Barrier(n_threads + 1)

    def create_many() -> None:
        barrier.wait()
        for _ in range(3):
            try:
                s = mgr.create_session("scheduling")
                session_ids.append(s.session_id)
            except Exception as exc:
                errors.append(exc)

    def clear_worker() -> None:
        barrier.wait()
        try:
            mgr.clear_all()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create_many) for _ in range(n_threads)]
    clear_thread = threading.Thread(target=clear_worker)
    for t in threads:
        t.start()
    clear_thread.start()
    for t in threads:
        t.join(timeout=5.0)
    clear_thread.join(timeout=5.0)

    assert errors == [], f"Errors during concurrent clear_all: {errors}"
    # After all threads finish, the manager must be internally consistent
    session_count = len(mgr._sessions)
    assert session_count >= 0  # trivially, but also confirms no AttributeError etc.
