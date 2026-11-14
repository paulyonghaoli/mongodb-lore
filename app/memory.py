"""Governed memory (contracts: Memory, Retrieval rules).

Lifecycle: pending -> active | rejected; active -> superseded | expired | forgotten.
Each version is its own document. Nothing is deleted; every status change is audited.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from . import audit, db, embeddings
from .config import get_settings
from .models import ROLES, ProposedMemory, UserContext

VECTOR_INDEX = "memory_vec"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _col():
    return db.app_db()[db.MEMORIES]


def _public(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("embedding", None)
    return doc


def _get(memory_id: str) -> dict:
    doc = _col().find_one({"memory_id": memory_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    return doc


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _visible_filter(user: UserContext, now: datetime) -> dict:
    """The retrieval filter: active, visible to the role, not expired."""
    return {
        "status": "active",
        "visibility": user.role,
        "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
    }


# ---------- lifecycle ----------

def propose(
    user: UserContext,
    proposed: ProposedMemory,
    source_turn_id: str | None,
    visibility: list[str] | None = None,
) -> dict:
    """A user's correction becomes a pending memory (not embedded, not retrievable).

    Contract: a user cannot propose wider visibility than their own role.
    Interpretation used here: non-reviewers propose for their own role only; the
    reviewer can widen visibility when approving.
    """
    if user.can_review:
        vis = visibility or list(ROLES)
    else:
        vis = [user.role]
        if visibility and set(visibility) - {user.role}:
            raise HTTPException(403, "You cannot propose wider visibility than your own role")

    invalid_roles = set(visibility or []) - set(ROLES)
    if invalid_roles:
        raise HTTPException(422, f"Unknown visibility roles: {sorted(invalid_roles)}")
    if visibility is not None and not visibility:
        raise HTTPException(422, "Visibility must include at least one role")

    latest = _col().find_one({"title": proposed.title}, sort=[("version", -1)])
    version = (latest["version"] + 1) if latest else 1
    memory_id = f"mem_{slug(proposed.title)}_v{version}"
    if _col().find_one({"memory_id": memory_id}):
        memory_id = f"{memory_id}_{uuid.uuid4().hex[:4]}"

    doc = {
        "memory_id": memory_id,
        "type": proposed.type,
        "title": proposed.title,
        "content": proposed.content,
        "version": version,
        "status": "pending",
        "visibility": vis,
        "expires_at": None,
        "source": {"turn_id": source_turn_id, "proposed_by": user.user_id,
                   "corrects_memory": latest["memory_id"] if latest else None},
        "approved_by": None,
        "created_at": _now(),
        "forgotten": None,
        "embed_model": None,
        "embedding": None,
    }
    _col().insert_one(doc)
    audit.write(user, "memory_propose", "memory", memory_id,
                {"title": proposed.title, "version": version,
                 "corrects_memory": doc["source"]["corrects_memory"]})
    return _public(doc)


def approve(
    reviewer: UserContext,
    memory_id: str,
    visibility: list[str] | None = None,
    expires_at: datetime | None = None,
) -> dict:
    if not reviewer.can_review:
        raise HTTPException(403, "Reviewer permission required")
    doc = _get(memory_id)
    if doc["status"] != "pending":
        raise HTTPException(409, f"Memory is {doc['status']}, not pending")

    if visibility is not None and (not visibility or set(visibility) - set(ROLES)):
        raise HTTPException(422, "Visibility must include one or more valid roles")
    if expires_at is not None:
        expires_at = _aware(expires_at)
        if expires_at <= _now():
            raise HTTPException(422, "Expiry must be in the future")

    newer_active = _col().find_one({"title": doc["title"], "status": "active",
                                    "version": {"$gt": doc["version"]}})
    if newer_active:
        raise HTTPException(409, "A newer version is already active")

    text = f"{doc['title']}: {doc['content']}"
    update: dict[str, Any] = {
        "status": "active",
        "approved_by": reviewer.user_id,
        "approved_at": _now(),
        "embedding": embeddings.embed_one(text, "document"),
        "embed_model": embeddings.model_name(),
    }
    if visibility is not None:
        update["visibility"] = visibility
    if expires_at is not None:
        update["expires_at"] = expires_at
    _col().update_one({"memory_id": memory_id}, {"$set": update})

    # Older active versions of the same title are superseded
    superseded = [d["memory_id"] for d in _col().find({
        "title": doc["title"], "status": "active", "memory_id": {"$ne": memory_id}})]
    if superseded:
        _col().update_many({"memory_id": {"$in": superseded}},
                           {"$set": {"status": "superseded", "superseded_by": memory_id}})

    audit.write(reviewer, "memory_approve", "memory", memory_id,
                {"superseded": superseded, "visibility": update.get("visibility", doc["visibility"]),
                 "expires_at": expires_at.isoformat() if expires_at else None,
                 "version": doc["version"], "corrects_memory": doc["source"].get("corrects_memory")})

    if doc["type"] == "metric":
        # Skills built on an older version of this metric need review
        from . import skills
        skills.mark_stale_for_metric(slug(doc["title"]), doc["version"])

    return _public(_get(memory_id))


def reject(reviewer: UserContext, memory_id: str, reason: str) -> dict:
    if not reviewer.can_review:
        raise HTTPException(403, "Reviewer permission required")
    doc = _get(memory_id)
    if doc["status"] != "pending":
        raise HTTPException(409, f"Memory is {doc['status']}, not pending")
    _col().update_one({"memory_id": memory_id},
                      {"$set": {"status": "rejected",
                                "rejected": {"by": reviewer.user_id, "reason": reason, "at": _now()}}})
    audit.write(reviewer, "memory_reject", "memory", memory_id, {"reason": reason})
    return _public(_get(memory_id))


def expire(reviewer: UserContext | None, memory_id: str, reason: str = "") -> dict:
    if reviewer is not None and not reviewer.can_review:
        raise HTTPException(403, "Reviewer permission required")
    doc = _get(memory_id)
    if doc["status"] != "active":
        raise HTTPException(409, f"Memory is {doc['status']}, not active")
    now = _now()
    expires_at = _aware(doc.get("expires_at"))
    new_expiry = expires_at if (expires_at and expires_at <= now) else now
    _col().update_one({"memory_id": memory_id},
                      {"$set": {"status": "expired", "expires_at": new_expiry}})
    audit.write(reviewer, "memory_expire", "memory", memory_id,
                {"reason": reason or ("reached expires_at" if reviewer is None else "expired by reviewer")})
    return _public(_get(memory_id))


def forget(reviewer: UserContext, memory_id: str, reason: str) -> dict:
    if not reviewer.can_review:
        raise HTTPException(403, "Reviewer permission required")
    if not reason:
        raise HTTPException(400, "A reason is required to forget a memory")
    doc = _get(memory_id)
    if doc["status"] == "forgotten":
        raise HTTPException(409, "Memory is already forgotten")
    forgotten_at = _now()
    # Content stays for the audit record; the embedding is dropped so it can never be retrieved
    _col().update_one({"memory_id": memory_id},
                      {"$set": {"status": "forgotten", "embedding": None,
                                "expires_at": forgotten_at,
                                "forgotten": {"by": reviewer.user_id, "reason": reason,
                                              "at": forgotten_at}}})
    audit.write(reviewer, "memory_forget", "memory", memory_id,
                {"reason": reason, "previous_status": doc["status"],
                 "previous_expires_at": doc.get("expires_at"),
                 "forgotten_at": forgotten_at.isoformat()})
    return _public(_get(memory_id))


def sweep_expired() -> list[str]:
    """Move active memories past expires_at to `expired`, with an audit event each."""
    now = _now()
    ids = [d["memory_id"] for d in _col().find({"status": "active", "expires_at": {"$ne": None, "$lte": now}})]
    for mid in ids:
        expire(None, mid)
    return ids


# ---------- reading ----------

def list_for(user: UserContext, status: str | None = None) -> list[dict]:
    """Reviewers see every memory; others see memories whose visibility includes their role."""
    sweep_expired()
    q: dict[str, Any] = {} if user.can_review else {"visibility": user.role}
    if status:
        q["status"] = status
    return [_public(d) for d in _col().find(q).sort([("title", 1), ("version", -1)])]


def retrieve(user: UserContext, question: str, use_memory: bool = True, k: int = 5) -> list[dict]:
    """Memories the agent may use for this user and question.

    Vector Search with filters, plus direct title matching (the vector index lags
    a few seconds after an approval). Results are checked again in Python.
    """
    if not use_memory:
        return []
    sweep_expired()
    now = _now()
    flt = _visible_filter(user, now)
    found: dict[str, dict] = {}

    # 1. Title match
    q_lower = question.lower()
    for d in _col().find(flt):
        if d["title"].lower() in q_lower:
            found[d["memory_id"]] = d

    # 2. Vector search
    qvec = embeddings.embed_one(question, "query")
    if get_settings().vector_backend == "atlas":
        pipeline = [
            {"$vectorSearch": {
                "index": VECTOR_INDEX,
                "path": "embedding",
                "queryVector": qvec,
                "numCandidates": 100,
                "limit": k,
                "filter": flt,
            }},
            {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        ]
        hits = list(_col().aggregate(pipeline))
    else:
        cands = [d for d in _col().find(flt) if d.get("embedding")]
        for d in cands:
            d["score"] = embeddings.cosine(qvec, d["embedding"])
        hits = sorted(cands, key=lambda d: d["score"], reverse=True)[:k]
    for d in hits:
        found.setdefault(d["memory_id"], d)

    # 3. Defence in depth: re-check every rule in code
    safe = []
    for d in found.values():
        exp = _aware(d.get("expires_at"))
        if d["status"] == "active" and user.role in d["visibility"] and (exp is None or exp > now):
            safe.append(_public(d))
    return safe
