"""Explicit default-deny filtering for restricted synthetic records.

This context is an in-process policy input for isolated tests. It is not an
identity provider, credential, authentication, or production authorization.
"""
from dataclasses import dataclass

from .models import Record


@dataclass(frozen=True)
class AccessContext:
    can_view_restricted: bool = False


def visible_records(records: list[Record], context: AccessContext | None = None) -> list[Record]:
    policy = context or AccessContext()
    return [record for record in records if policy.can_view_restricted or not record.restricted]

