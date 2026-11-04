"""In-memory session and audit trail manager for the Story Connect Policy Demo.

Provides an isolated, in-process, append-only audit trail for reviewer
evidence challenges during an active browser session.

Design & Safety Constraints:
- Purely in-memory: all history is lost on process restart or reset.
- Bounded capacity: fixed max sessions (100) and max events per session (20).
- Unguessable session IDs: 32-hex random UUIDs; strict regex validation.
- Scenario isolation: a session is bound to one scenario at a time; cross-scenario
  contamination is rejected with a sanitized 422 error.
- Sanitized payloads: stores only validated, structured fields; no raw user text,
  credentials, or unbounded exception strings.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import threading
from typing import Any

from policy_evidence_demo import ALLOWED_SCENARIO_IDS, SCENARIO_SCHEDULING


MAX_SESSIONS = 100
MAX_EVENTS_PER_SESSION = 20
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}\Z")
PROPOSAL_ID_PATTERN = re.compile(r"^[a-f0-9]{32}\Z")
MAX_PENDING_PROPOSALS = 100
MAX_PROPOSAL_SNAPSHOT_BYTES = 256_000


class PolicySessionError(ValueError):
    """Sanitized public error for demo session operations."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class AuditTrailEvent:
    """Immutable record of an individual evidence challenge in a session."""

    sequence_number: int
    timestamp_iso: str
    scenario_id: str
    target_department: str
    target_side: str
    applicability_status: str
    initial_relation: str
    recomputed_relation: str
    core_classification: str
    uncertainty_reasons: tuple[str, ...]
    contract_enforced: bool
    summary: str
    proposal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_number": self.sequence_number,
            "timestamp_iso": self.timestamp_iso,
            "scenario_id": self.scenario_id,
            "proposal_id": self.proposal_id,
            "target_department": self.target_department,
            "target_side": self.target_side,
            "applicability_status": self.applicability_status,
            "initial_relation": self.initial_relation,
            "recomputed_relation": self.recomputed_relation,
            "core_classification": self.core_classification,
            "uncertainty_reasons": list(self.uncertainty_reasons),
            "contract_enforced": self.contract_enforced,
            "summary": self.summary,
        }


@dataclass
class DemoSession:
    """In-memory investigation session tracking an append-only audit trail."""

    session_id: str
    scenario_id: str
    created_at_iso: str
    events: list[AuditTrailEvent]
    total_events: int = 0
    generation: int = 0
    proposal_id: str | None = None
    proposal_snapshot_json: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "scenario_id": self.scenario_id,
            "created_at_iso": self.created_at_iso,
            "proposal_id": self.proposal_id,
            "events_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(frozen=True)
class SessionMetadata:
    session_id: str
    scenario_id: str
    created_at_iso: str
    history_count: int
    total_events: int
    generation: int
    proposal_id: str | None = None


@dataclass(frozen=True)
class SessionHistorySnapshot:
    metadata: SessionMetadata
    events: tuple[AuditTrailEvent, ...]


@dataclass(frozen=True)
class RecordedChallengeSnapshot:
    event: AuditTrailEvent
    metadata: SessionMetadata


class InMemoryDemoSessionManager:
    """Thread-safe in-memory session manager with explicit RLock synchronization."""

    def __init__(
        self,
        max_sessions: int = MAX_SESSIONS,
        max_events: int = MAX_EVENTS_PER_SESSION,
        max_pending_proposals: int = MAX_PENDING_PROPOSALS,
    ) -> None:
        self.max_sessions = max_sessions
        self.max_events = max_events
        self.max_pending_proposals = max_pending_proposals
        self._sessions: OrderedDict[str, DemoSession] = OrderedDict()
        self._pending_proposals: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
            raise PolicySessionError(
                code="invalid_session_id",
                detail="Session ID is invalid or malformed.",
            )

    @staticmethod
    def _validate_scenario_id(scenario_id: str) -> None:
        if scenario_id not in ALLOWED_SCENARIO_IDS:
            raise PolicySessionError(
                code="unknown_scenario",
                detail=f"Scenario ID '{scenario_id}' is not recognized.",
            )

    @staticmethod
    def _validate_proposal_id(proposal_id: str) -> None:
        if not isinstance(proposal_id, str) or not PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
            raise PolicySessionError("invalid_proposal_id", "Proposal ID is invalid or malformed.")

    @staticmethod
    def _metadata(session: DemoSession) -> SessionMetadata:
        return SessionMetadata(
            session_id=session.session_id,
            scenario_id=session.scenario_id,
            created_at_iso=session.created_at_iso,
            history_count=len(session.events),
            total_events=session.total_events,
            generation=session.generation,
            proposal_id=session.proposal_id,
        )

    def register_proposal(self, scenario_id: str, proposal: dict[str, Any]) -> str:
        """Keep a bounded immutable proposal snapshot until its session is created."""
        self._validate_scenario_id(scenario_id)
        if type(proposal) is not dict or proposal.get("scenario_id") != scenario_id:
            raise PolicySessionError("invalid_proposal", "Proposal does not match the requested scenario.")

        import uuid
        proposal_id = uuid.uuid4().hex
        snapshot = dict(proposal)
        snapshot["proposal_id"] = proposal_id
        try:
            snapshot_bytes = json.dumps(
                snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8", "strict")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise PolicySessionError("invalid_proposal", "Proposal snapshot is invalid.") from None
        if len(snapshot_bytes) > MAX_PROPOSAL_SNAPSHOT_BYTES:
            raise PolicySessionError("proposal_too_large", "Proposal snapshot exceeds its size limit.")

        with self._lock:
            while len(self._pending_proposals) >= self.max_pending_proposals:
                self._pending_proposals.popitem(last=False)
            self._pending_proposals[proposal_id] = (scenario_id, snapshot_bytes)
        return proposal_id

    def create_session(
        self, scenario_id: str = SCENARIO_SCHEDULING, proposal_id: str | None = None,
    ) -> SessionMetadata:
        """Create a session bound to a pending proposal snapshot when supplied."""
        self._validate_scenario_id(scenario_id)
        if proposal_id is not None:
            self._validate_proposal_id(proposal_id)

        import uuid
        session_id = uuid.uuid4().hex

        with self._lock:
            proposal_snapshot_json = None
            if proposal_id is not None:
                pending = self._pending_proposals.get(proposal_id)
                if pending is None:
                    raise PolicySessionError("proposal_not_found", "Proposal is missing, stale, or already consumed.")
                if pending[0] != scenario_id:
                    raise PolicySessionError("proposal_scenario_mismatch", "Proposal does not match the requested scenario.")
                proposal_snapshot_json = pending[1]
                del self._pending_proposals[proposal_id]

            # Enforce max sessions cap via FIFO eviction
            while len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)

            now_iso = datetime.now(timezone.utc).isoformat()
            session = DemoSession(
                session_id=session_id,
                scenario_id=scenario_id,
                created_at_iso=now_iso,
                events=[],
                proposal_id=proposal_id,
                proposal_snapshot_json=proposal_snapshot_json,
            )
            self._sessions[session_id] = session
            return self._metadata(session)

    def get_bound_proposal(
        self, session_id: str, scenario_id: str, proposal_id: str,
    ) -> tuple[SessionMetadata, dict[str, Any]]:
        """Return a detached copy of the exact immutable proposal bound to a session."""
        self._validate_proposal_id(proposal_id)
        self._validate_scenario_id(scenario_id)
        with self._lock:
            metadata = self.get_session(session_id)
            session = self._sessions[metadata.session_id]
            if session.scenario_id != scenario_id:
                raise PolicySessionError("scenario_mismatch", "Session scenario does not match the challenge.")
            if session.proposal_id != proposal_id or session.proposal_snapshot_json is None:
                raise PolicySessionError("proposal_mismatch", "Proposal does not match this session or is no longer available.")
            try:
                snapshot = json.loads(session.proposal_snapshot_json.decode("utf-8", "strict"))
            except (UnicodeError, json.JSONDecodeError):
                raise PolicySessionError("proposal_unavailable", "Bound proposal snapshot is unavailable.") from None
            if type(snapshot) is not dict or snapshot.get("scenario_id") != scenario_id or snapshot.get("proposal_id") != proposal_id:
                raise PolicySessionError("proposal_unavailable", "Bound proposal snapshot is unavailable.")
            return metadata, snapshot

    def get_session(self, session_id: str) -> SessionMetadata:
        """Return immutable metadata for an active session, never the internal object."""
        self._validate_session_id(session_id)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise PolicySessionError(
                    code="session_not_found",
                    detail="Session not found or has expired.",
                )
            return self._metadata(session)

    def get_history_snapshot(self, session_id: str) -> list[AuditTrailEvent]:
        """Return an immutable snapshot of events for the session."""
        with self._lock:
            metadata = self.get_session(session_id)
            return list(self._sessions[metadata.session_id].events)

    def get_session_history_snapshot(self, session_id: str) -> SessionHistorySnapshot:
        """Return immutable metadata and event tuple from one locked read."""
        with self._lock:
            session = self.get_session(session_id)
            # get_session returns metadata; fetch internal state only under this lock.
            internal = self._sessions[session.session_id]
            return SessionHistorySnapshot(self._metadata(internal), tuple(internal.events))

    def record_challenge_event(
        self,
        session_id: str,
        scenario_id: str,
        target_department: str,
        target_side: str,
        applicability_status: str,
        initial_relation: str,
        recomputed_relation: str,
        core_classification: str,
        uncertainty_reasons: list[str],
        contract_enforced: bool,
        summary: str,
    ) -> AuditTrailEvent:
        """Append an event and return the immutable event record."""
        return self.record_challenge_event_snapshot(
            session_id, scenario_id, target_department, target_side, applicability_status,
            initial_relation, recomputed_relation, core_classification, uncertainty_reasons,
            contract_enforced, summary, expected_generation=None,
        ).event

    def record_challenge_event_snapshot(
        self,
        session_id: str,
        scenario_id: str,
        target_department: str,
        target_side: str,
        applicability_status: str,
        initial_relation: str,
        recomputed_relation: str,
        core_classification: str,
        uncertainty_reasons: list[str],
        contract_enforced: bool,
        summary: str,
        expected_generation: int | None,
        proposal_id: str | None = None,
    ) -> RecordedChallengeSnapshot:
        """Atomically record an event and capture its corresponding history metadata."""
        with self._lock:
            metadata = self.get_session(session_id)
            session = self._sessions[metadata.session_id]

            if session.scenario_id != scenario_id:
                raise PolicySessionError(
                    code="scenario_mismatch",
                    detail=(
                        f"Session is bound to scenario '{session.scenario_id}', "
                        f"cannot record challenge for scenario '{scenario_id}'."
                    ),
                )
            if expected_generation is not None and session.generation != expected_generation:
                raise PolicySessionError(
                    code="session_reset",
                    detail="Session was reset while the challenge was being computed.",
                )
            if proposal_id is not None and session.proposal_id != proposal_id:
                raise PolicySessionError(
                    code="proposal_mismatch",
                    detail="Proposal does not match this session or is no longer available.",
                )

            session.total_events += 1
            sequence_number = session.total_events
            now_iso = datetime.now(timezone.utc).isoformat()

            event = AuditTrailEvent(
                sequence_number=sequence_number,
                timestamp_iso=now_iso,
                scenario_id=scenario_id,
                target_department=target_department,
                target_side=target_side,
                applicability_status=applicability_status,
                initial_relation=initial_relation,
                recomputed_relation=recomputed_relation,
                core_classification=core_classification,
                uncertainty_reasons=tuple(sorted(set(uncertainty_reasons))),
                contract_enforced=contract_enforced,
                summary=summary[:500],  # bounded deterministic summary
                proposal_id=proposal_id if proposal_id is not None else session.proposal_id,
            )
            session.events.append(event)
            while len(session.events) > self.max_events:
                session.events.pop(0)
            return RecordedChallengeSnapshot(event=event, metadata=self._metadata(session))

    def reset_session(self, session_id: str, new_scenario_id: str | None = None) -> SessionMetadata:
        """Clear history and optionally update binding, returning immutable metadata."""
        if new_scenario_id is not None:
            self._validate_scenario_id(new_scenario_id)
        with self._lock:
            metadata = self.get_session(session_id)
            session = self._sessions[metadata.session_id]
            session.events.clear()
            session.total_events = 0
            session.generation += 1
            if new_scenario_id is not None:
                if new_scenario_id != session.scenario_id:
                    session.proposal_id = None
                    session.proposal_snapshot_json = None
                session.scenario_id = new_scenario_id
            return self._metadata(session)

    def clear_all(self) -> None:
        """Clear all in-memory sessions (for test teardown)."""
        with self._lock:
            self._sessions.clear()
            self._pending_proposals.clear()


# Global in-memory singleton for the demo service
default_session_manager = InMemoryDemoSessionManager()
