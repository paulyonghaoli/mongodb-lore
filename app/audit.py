"""Audit log. Every component writes the same shape (contracts: Audit event)."""
from datetime import datetime, timezone
from typing import Any

from . import db
from .models import UserContext

ACTIONS = {
    "query",
    "memory_propose", "memory_approve", "memory_reject",
    "memory_expire", "memory_forget",
    "query_delete", "review_retain",
    "skill_publish", "skill_retire",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def write(
    actor: UserContext | None,
    action: str,
    target_kind: str,
    target_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action {action!r}")
    event = {
        "ts": now(),
        "actor": actor.user_id if actor else "system",
        "role": actor.role if actor else "system",
        "action": action,
        "target": {"kind": target_kind, "id": target_id},
        "details": details or {},
    }
    db.app_db()[db.AUDIT_LOG].insert_one(event)
    event.pop("_id", None)
    return event


def recent(limit: int = 100, action: str | None = None) -> list[dict]:
    q = {"action": action} if action else {}
    cur = db.app_db()[db.AUDIT_LOG].find(q, {"_id": 0}).sort("ts", -1).limit(limit)
    return list(cur)
