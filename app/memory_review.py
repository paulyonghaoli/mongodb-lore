"""Monthly memory and query retention review.

The scan only creates reviewer work: proposed memories stay pending, query
records stay intact until a reviewer deletes them, and unused memories are only
marked as review candidates.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from . import audit, db, llm, memory
from .models import ProposedMemory, UserContext
# checking schema
MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["metric", "definition", "decision", "fact"]},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "source_turn_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["type", "title", "content", "source_turn_ids"],
            "additionalProperties": False,
        }},
    },
    "required": ["memories"],
    "additionalProperties": False,
}

MEMORY_RULES = """Review business questions and their recorded outcome/metric metadata for durable, reusable company knowledge.
Only propose explicit metric definitions, business rules, or confirmed facts stated in the input.
Do not turn an individual request, date range, result, guess, or user-specific permission into memory.
Never invent or infer a definition. Cite only supplied turn IDs. Return an empty array when nothing qualifies.
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_bounds(month: str | None = None) -> tuple[date, date, str]:
    if month:
        try:
            year, number = (int(x) for x in month.split("-", 1))
            start = date(year, number, 1)
        except (ValueError, TypeError):
            raise HTTPException(422, "month must use YYYY-MM")
        if start.strftime("%Y-%m") != month:
            raise HTTPException(422, "month must use YYYY-MM")
    else:
        today = _now().date()
        this_month = date(today.year, today.month, 1)
        start = (this_month - timedelta(days=1)).replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end, start.strftime("%Y-%m")


def _as_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "memory"


def _draft_memories(sessions: list[dict], batch_id: str) -> list[str]:
    eligible = [s for s in sessions if s.get("turn_id")]
    inserted: list[str] = []
    for offset in range(0, len(eligible), 30):
        chunk = eligible[offset:offset + 30]
        turns = [{"turn_id": s["turn_id"], "question": s.get("question", ""),
                  "metrics_used": s.get("metrics_used", []), "outcome": s.get("outcome")}
                 for s in chunk]
        usage = llm.Usage()
        result = llm.complete(MEMORY_RULES, [{"role": "user", "content": json.dumps(turns)}],
                              usage, schema=MEMORY_SCHEMA, effort="low", max_tokens=5000)
        allowed_ids = {s["turn_id"] for s in chunk}
        for item in result["memories"]:
            sources = sorted(set(item["source_turn_ids"]) & allowed_ids)
            if not sources or not item["title"].strip() or not item["content"].strip():
                continue
            proposed = ProposedMemory(type=item["type"], title=item["title"].strip(),
                                      content=item["content"].strip())
            collection = db.app_db()[db.MEMORIES]
            if collection.find_one({"title": proposed.title, "content": proposed.content}):
                continue
            latest = collection.find_one({"title": proposed.title}, sort=[("version", -1)])
            version = latest["version"] + 1 if latest else 1
            memory_id = f"mem_{_slug(proposed.title)}_v{version}"
            doc = {
                "memory_id": memory_id, "type": proposed.type, "title": proposed.title,
                "content": proposed.content, "version": version, "status": "pending",
                "visibility": ["finance_lead", "analyst", "store_manager"],
                "expires_at": None,
                "source": {"turn_id": sources[0], "turn_ids": sources,
                           "proposed_by": "monthly_review", "batch_id": batch_id},
                "approved_by": None, "created_at": _now(), "forgotten": None,
                "embed_model": None, "embedding": None,
            }
            if collection.find_one({"memory_id": memory_id}):
                memory_id = f"{memory_id}_{batch_id.replace('-', '')}"
                doc["memory_id"] = memory_id
            collection.insert_one(doc)
            audit.write(None, "memory_propose", "memory", memory_id,
                        {"title": proposed.title, "version": version,
                         "source_turn_ids": sources, "monthly_batch_id": batch_id})
            inserted.append(memory_id)
    return inserted


def run_monthly(month: str | None = None) -> dict[str, Any]:
    start, end, batch_id = _month_bounds(month)
    runs = db.app_db()[db.MEMORY_REVIEW_RUNS]
    existing = runs.find_one({"batch_id": batch_id})
    if existing and existing.get("status") == "complete":
        return {k: v for k, v in existing.items() if k != "_id"}
    if existing and existing.get("status") == "running":
        raise HTTPException(409, f"Monthly review {batch_id} already started; inspect its run record")
    if existing:
        db.app_db()[db.MEMORY_REVIEW_ITEMS].delete_many({"batch_id": batch_id})
        db.app_db()[db.MEMORIES].delete_many({"source.batch_id": batch_id,
                                              "source.proposed_by": "monthly_review",
                                              "status": "pending"})
        runs.update_one({"batch_id": batch_id}, {"$set": {
            "status": "running", "error": None, "created_at": _now()}})
    else:
        runs.insert_one({"batch_id": batch_id, "period_start": _as_utc(start),
                         "period_end": _as_utc(end), "status": "running", "created_at": _now()})
    session_col = db.app_db()[db.SESSIONS]
    sessions = list(session_col.find({"ts": {"$gte": _as_utc(start), "$lt": _as_utc(end)}})
                    .sort("ts", 1))
    items = db.app_db()[db.MEMORY_REVIEW_ITEMS]
    query_items = 0
    for s in sessions:
        turn_id = s.get("turn_id")
        if not turn_id:
            continue
        items.update_one({"batch_id": batch_id, "item_type": "query", "turn_id": turn_id},
                         {"$setOnInsert": {
                             "batch_id": batch_id, "item_type": "query",
                             "item_id": f"query_{turn_id}", "turn_id": turn_id,
                             "session_id": s.get("session_id"), "user_id": s.get("user_id"),
                             "role": s.get("role"), "question": s.get("question", ""),
                             "outcome": s.get("outcome"), "created_at": s.get("ts"),
                             "status": "pending", "reviewed_at": None,
                         }}, upsert=True)
        query_items += 1

    memory_ids_used = {mid for s in sessions for mid in s.get("memory_ids", [])}
    memory.sweep_expired()
    active_memories = db.app_db()[db.MEMORIES].find(
        {"status": "active", "created_at": {"$lt": _as_utc(end)}})
    memory_items = 0
    for m in active_memories:
        if m["memory_id"] in memory_ids_used:
            continue
        items.update_one({"batch_id": batch_id, "item_type": "memory", "memory_id": m["memory_id"]},
                         {"$setOnInsert": {
                             "batch_id": batch_id, "item_type": "memory",
                             "item_id": f"memory_{m['memory_id']}", "memory_id": m["memory_id"],
                             "title": m["title"], "content": m["content"],
                             "version": m["version"], "last_used_in_period": False,
                             "review_reason": "This active memory was not used by any session during this month.",
                             "status": "pending", "created_at": _now(), "reviewed_at": None,
                         }}, upsert=True)
        memory_items += 1

    try:
        proposed_ids = _draft_memories(sessions, batch_id)
    except Exception as exc:
        runs.update_one({"batch_id": batch_id}, {"$set": {
            "status": "failed", "error": str(exc), "failed_at": _now()}})
        raise
    summary = {"batch_id": batch_id, "status": "complete", "period_start": _as_utc(start),
               "period_end": _as_utc(end), "query_items": query_items,
               "memory_items": memory_items, "proposed_memory_ids": proposed_ids,
               "created_at": _now()}
    runs.update_one({"batch_id": batch_id}, {"$set": summary})
    return summary


def list_runs(limit: int = 12) -> list[dict]:
    return [{k: v for k, v in d.items() if k != "_id"}
            for d in db.app_db()[db.MEMORY_REVIEW_RUNS].find().sort("batch_id", -1).limit(limit)]


def list_items(batch_id: str | None = None, item_type: str | None = None,
               status: str | None = "pending", limit: int = 500) -> list[dict]:
    query: dict[str, Any] = {}
    if batch_id:
        query["batch_id"] = batch_id
    if item_type:
        query["item_type"] = item_type
    if status:
        query["status"] = status
    return [{k: v for k, v in d.items() if k != "_id"}
            for d in db.app_db()[db.MEMORY_REVIEW_ITEMS].find(query).sort("created_at", -1).limit(limit)]


def _reviewer(user: UserContext) -> None:
    if not user.can_review:
        raise HTTPException(403, "Reviewer permission required")


def retain_item(reviewer: UserContext, item_id: str) -> dict:
    _reviewer(reviewer)
    col = db.app_db()[db.MEMORY_REVIEW_ITEMS]
    item = col.find_one({"item_id": item_id})
    if item is None:
        raise HTTPException(404, f"Review item {item_id} not found")
    if item["status"] != "pending":
        raise HTTPException(409, f"Review item is {item['status']}")
    col.update_one({"item_id": item_id}, {"$set": {
        "status": "retained", "reviewed_by": reviewer.user_id, "reviewed_at": _now()}})
    audit.write(reviewer, "review_retain", item["item_type"], item.get("turn_id") or item.get("memory_id"),
                {"batch_id": item["batch_id"], "item_id": item_id})
    return {k: v for k, v in col.find_one({"item_id": item_id}).items() if k != "_id"}


def delete_item(reviewer: UserContext, item_id: str, reason: str) -> dict:
    _reviewer(reviewer)
    if not reason.strip():
        raise HTTPException(400, "A reason is required")
    col = db.app_db()[db.MEMORY_REVIEW_ITEMS]
    item = col.find_one({"item_id": item_id})
    if item is None:
        raise HTTPException(404, f"Review item {item_id} not found")
    if item["status"] != "pending":
        raise HTTPException(409, f"Review item is {item['status']}")

    if item["item_type"] == "query":
        ep_col = db.app_db()[db.EPISODES]
        episode_ids = [e["episode_id"] for e in ep_col.find({"turn_id": item["turn_id"]})]
        # Remove source episodes and make dependent skills unavailable for review.
        ep_col.delete_many({"turn_id": item["turn_id"]})
        if episode_ids:
            skill_col = db.app_db()[db.SKILLS]
            for skill in skill_col.find({"source_episodes": {"$in": episode_ids}}):
                skill_col.update_one({"_id": skill["_id"]}, {"$set": {
                    "status": "retired", "retired_reason": "source query deleted",
                    "retired_at": _now()}, "$pull": {
                    "source_episodes": {"$in": episode_ids}}})
        db.app_db()[db.SESSIONS].delete_one({"turn_id": item["turn_id"]})
        db.app_db()[db.AUDIT_LOG].update_many(
            {"action": "query", "details.turn_id": item["turn_id"]},
            {"$set": {"details.question": None, "details.pipeline": None,
                       "details.query_deleted": True}})
        col.update_one({"item_id": item_id}, {"$set": {
            "status": "deleted", "question": None, "reviewed_by": reviewer.user_id,
            "reviewed_at": _now(), "deletion_reason": reason.strip()}})
        audit.write(reviewer, "query_delete", "query", item["turn_id"],
                    {"batch_id": item["batch_id"], "reason": reason.strip(),
                     "episodes_deleted": len(episode_ids)})
    elif item["item_type"] == "memory":
        memory.forget(reviewer, item["memory_id"], reason.strip())
        col.update_one({"item_id": item_id}, {"$set": {
            "status": "deleted", "content": None, "reviewed_by": reviewer.user_id,
            "reviewed_at": _now(), "deletion_reason": reason.strip()}})
    else:
        raise HTTPException(409, "Unsupported review item type")

    return {k: v for k, v in col.find_one({"item_id": item_id}).items() if k != "_id"}
