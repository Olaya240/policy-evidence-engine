"""Which claims depend on a record, and on those claims' dependents.

The question this module answers is asked in three places already, and answered
inline in two of them: `store.get_challenge_snapshot` and
`store.apply_challenge` each rebuild the affected-claim set from `dependencies`
inside their own read, and `evaluate` only checks that the sets agree. Nothing
names the relation, so nothing could ask about it outside that pair.

Scope, stated so it cannot be mistaken for more:

* `direct_dependents` — claims whose evidence cites the record.
* `transitive_dependents` — the closure over claim-to-claim edges.

**There is no claim-to-claim edge in the stored data.** `Claim.dependencies`
(`app/models.py`) holds *source record* ids, and the engine builds it as
`sorted({e.source_record_id for e in evidence})`; no field on `Claim` names
another claim and nothing in `app/` writes a claim id into that list. The closure
therefore collapses to the direct set by construction — this module does not
invent an edge to make "transitive" look like more than it is. A caller that one
day has real claim edges passes them as `claim_edges`; the visited set is the
cycle guard, so such a graph still terminates.

Pure and deterministic on purpose: no I/O, no clock, no mutation of its inputs,
and every result is a tuple sorted by claim id.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["direct_dependents", "transitive_dependents"]


def _cited_record_ids(claim: Any) -> frozenset[str]:
    """The record ids a claim's evidence cites.

    `dependencies` is the denormalized, engine-maintained answer and is what
    `store.py` reads, so it is the source of truth here too. A claim dict that
    carries only `evidence` rows (hand-built input, or a claim from before the
    field was populated) is answered from those rows rather than silently
    reporting no dependency.
    """
    if isinstance(claim, Mapping):
        raw = claim.get("dependencies")
        has_field = "dependencies" in claim
        rows = claim.get("evidence") or ()
    else:
        raw = getattr(claim, "dependencies", None)
        has_field = hasattr(claim, "dependencies")
        rows = getattr(claim, "evidence", None) or ()

    if has_field and raw is not None:
        return frozenset(str(item) for item in raw)

    cited = set()
    for row in rows:
        record_id = row.get("source_record_id") if isinstance(row, Mapping) else getattr(row, "source_record_id", None)
        if record_id is not None:
            cited.add(str(record_id))
    return frozenset(cited)


def direct_dependents(claims: Mapping[str, Any], record_id: str) -> tuple[str, ...]:
    """Claim ids whose evidence cites `record_id`, sorted.

    `claims` is any mapping of claim id to a claim (dict as exchanged by the
    engine and store, or a `Claim` model). The mapping's own keys decide
    identity, so one claim listed twice under different keys is reported under
    both — the answer is about claims as addressed, not about objects.
    """
    record_id = str(record_id)
    return tuple(sorted(cid for cid, claim in claims.items() if record_id in _cited_record_ids(claim)))


def transitive_dependents(
    claims: Mapping[str, Any],
    record_id: str,
    *,
    claim_edges: Mapping[str, Iterable[str]] | None = None,
) -> tuple[str, ...]:
    """The closure of `direct_dependents` over claim-to-claim edges, sorted.

    `claim_edges` maps a claim id to the ids of the claims that depend on it
    (downstream). It defaults to `None`, which is the truth for the stored
    schema: no claim-to-claim edge exists, so the closure is the direct set.
    Edges naming a claim absent from `claims` are ignored — the result only ever
    contains claims that exist in the input — and the visited set makes a cycle
    (including a self-loop) terminate.
    """
    edges: Mapping[str, Iterable[str]] = claim_edges or {}

    seen = set(direct_dependents(claims, record_id))
    pending = sorted(seen)
    while pending:
        for dependent in edges.get(pending.pop(), ()):
            dependent = str(dependent)
            if dependent in seen or dependent not in claims:
                continue
            seen.add(dependent)
            pending.append(dependent)
    return tuple(sorted(seen))
