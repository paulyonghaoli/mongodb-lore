"""Analyst agent (contracts: Agent output, Session turn, REST /api/ask).

The model only plans. Code retrieves memory, guards the pipeline, runs it and
saves the session; the model never sees rows the user cannot see.
"""
import json
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from bson import ObjectId, json_util
from pymongo.errors import PyMongoError

from . import audit, db, llm, memory, skills
from .config import get_settings
from .guard import GuardError, guard_pipeline
from .models import AgentOutput, ProposedMemory, SkillCall, UserContext

SALES_FIELDS = {
    "date": "Date, daily, UTC, 2026-01-01 to 2026-10-31",
    "store_id": 'String, e.g. "E03" (region letter + number)',
    "store_name": 'String, e.g. "Harbourfront"',
    "region": '"East" | "West" | "North" | "South"',
    "category": '"Camping" | "Apparel" | "Footwear" | "Home"',
    "product": 'String, e.g. "2-person tent"',
    "units": "Int, units sold",
    "revenue": "Double, gross sales in CAD",
    "returns": "Double, refunds in CAD",
    "supplier_cost": "Double, supplier cost in CAD",
    "discount": "Double, fraction off list price",
}

# Strict JSON schema for the planning call. Pipelines are arbitrary objects, so
# they travel as a JSON string and are parsed (MongoDB Extended JSON) in code.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "interpretation": {"type": "string"},
        "collection": {"type": "string"},
        "pipeline_json": {"type": "string"},
        "metrics_used": {"type": "array", "items": {"type": "string"}},
        "skill": {"anyOf": [
            {"type": "object",
             "properties": {"name": {"type": "string"}, "parameters_json": {"type": "string"}},
             "required": ["name", "parameters_json"], "additionalProperties": False},
            {"type": "null"},
        ]},
        "proposed_memory": {"anyOf": [
            {"type": "object",
             "properties": {
                 "type": {"type": "string", "enum": ["metric", "definition", "decision", "fact"]},
                 "title": {"type": "string"},
                 "content": {"type": "string"}},
             "required": ["type", "title", "content"], "additionalProperties": False},
            {"type": "null"},
        ]},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["interpretation", "collection", "pipeline_json", "metrics_used",
                 "skill", "proposed_memory", "assumptions"],
    "additionalProperties": False,
}

PLAN_RULES = """You are Lore, an analyst agent for Northwind Outfitters, a retailer with 20 stores in 4 regions.
You answer business questions by writing one read-only MongoDB aggregation pipeline over the `sales`
collection (one document per store, product and day). Code runs the pipeline, not you.

Rules:
- Allowed stages: $match, $group, $project, $addFields, $set, $sort, $limit, $skip, $unwind, $count.
  Never use $lookup, $graphLookup, $unionWith, $out, $merge, $function, $where or $accumulator.
- Use only the fields listed below. Fields not listed do not exist for this user. If the question needs a
  field that is not listed, say so in `interpretation`, and return a pipeline that answers what you can.
- Write dates as MongoDB Extended JSON: {"$date": "2026-07-01T00:00:00Z"}. Periods are half-open
  ranges [start, end). Quarters are calendar quarters.
- Compute ratios as ratios of sums, never averages of ratios. Round money to 2 decimals.
- `pipeline_json` is the pipeline as a JSON array string. Leave it as "[]" when you use a skill.
- Company memory, when present, is authoritative: follow its definitions exactly, and list each metric
  you used in `metrics_used` as "<title slug>@<version>", e.g. "net_margin@2".
- If the user corrects or states a definition, fill `proposed_memory` with {type, title, content}
  (title is the metric name, e.g. "Net margin"), and answer using the user's definition this time.
  Otherwise set `proposed_memory` to null.
- To reuse a published skill, set `skill` to {name, parameters_json}; otherwise null.
- List any assumptions (e.g. which months a quarter covers) in `assumptions`.
"""

EXPLAIN_RULES = """You are Lore, an analyst agent. Explain query results to a business user in 2-5 sentences.
Use only the rows given. Round money to 2 decimals and ratios to percentages with 1 decimal.
Name the metric definition used and its version when one was given. Do not invent numbers.
If the rows are empty, say so plainly. Never mention fields the user cannot see.
When the answer compares periods of different lengths (e.g. a 31-day and a 30-day month), say so in
one sentence, since part of the change comes from the extra days."""


def _fields_for(user: UserContext) -> dict[str, str]:
    return {k: v for k, v in SALES_FIELDS.items() if k not in user.hidden_fields}


def _system_prompt(user: UserContext, memories: list[dict], offered_skills: list[dict]) -> str:
    fields = "\n".join(f"- {k}: {v}" for k, v in _fields_for(user).items())
    parts = [PLAN_RULES, f"Fields in `sales` for this user:\n{fields}"]
    if user.rows:
        parts.append(f"This user's rows are already limited to {json.dumps(user.rows)}.")
    if memories:
        mem = "\n".join(f"- [{m['memory_id']}] {m['title']} (v{m['version']}, {m['type']}): {m['content']}"
                        for m in memories)
        parts.append(f"Company memory:\n{mem}")
    else:
        parts.append("Company memory: none available. Use your own judgment for definitions.")
    if offered_skills:
        sk = "\n".join(f"- {s['name']} v{s['version']}: {s['description']}; parameters "
                       f"{json.dumps(s['parameters'])}" for s in offered_skills)
        parts.append(f"Published skills you may reuse:\n{sk}")
    return "\n\n".join(parts)


def to_jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items() if k != "_id" or not isinstance(x, ObjectId)}
    if isinstance(v, list):
        return [to_jsonable(x) for x in v]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "to_decimal"):  # Decimal128
        return float(v.to_decimal())
    return v


def _columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


HISTORY_TURNS = 4


def session_history(user: UserContext, session_id: str, limit: int = HISTORY_TURNS) -> list[dict]:
    """Earlier answered turns of this session, for follow-up questions.

    Only the asking user's own turns: session_id comes from the client, so a turn
    from another user (or role) must never leak into this user's context.
    """
    cur = (db.app_db()[db.SESSIONS]
           .find({"session_id": session_id, "user_id": user.user_id, "outcome": "answered"},
                 {"_id": 0, "question": 1, "pipeline": 1, "answer": 1})
           .sort("ts", -1).limit(limit))
    return list(reversed(list(cur)))


def _history_text(history: list[dict]) -> str:
    if not history:
        return ""
    lines = ["Earlier in this conversation (use it to resolve follow-ups like \"break that down by store\"):"]
    for i, h in enumerate(history, 1):
        lines.append(f"{i}. Question: {h['question']}\n   Pipeline: {h['pipeline']}\n   Answer: {h['answer']}")
    return "\n".join(lines) + "\n\n"


def _new_turn_id(session_id: str) -> str:
    """Next turn number after the highest one in the session.

    Not a count: turns can be deleted (monthly review), and a count would then
    hand out an ID that already exists.
    """
    pattern = re.compile(rf"{re.escape(session_id)}_t(\d+)")
    numbers = [int(m.group(1)) for d in db.app_db()[db.SESSIONS].find({"session_id": session_id}, {"turn_id": 1})
               if (m := pattern.fullmatch(d.get("turn_id") or ""))]
    return f"{session_id}_t{max(numbers, default=0) + 1}"


def _resolve_pipeline(user: UserContext, out: AgentOutput) -> tuple[list[dict], dict | None]:
    """The pipeline to run for a plan: the skill's rendered template, or the planned pipeline."""
    if out.skill:
        return skills.render_for(user, out.skill.name, out.skill.parameters), out.skill.model_dump()
    return out.pipeline, None


def plan(user: UserContext, question: str, memories: list[dict], offered: list[dict],
         usage: llm.Usage, extra_messages: list[dict] | None = None,
         history: list[dict] | None = None) -> AgentOutput:
    today = datetime.now(timezone.utc).date().isoformat()
    messages = [{"role": "user",
                 "content": f"Today is {today}.\n\n{_history_text(history or [])}Question: {question}"}]
    messages += extra_messages or []
    raw = llm.complete(_system_prompt(user, memories, offered), messages, usage, schema=PLAN_SCHEMA)
    pipeline = json_util.loads(raw["pipeline_json"] or "[]")
    skill = None
    if raw.get("skill"):
        skill = SkillCall(name=raw["skill"]["name"],
                          parameters=json.loads(raw["skill"]["parameters_json"] or "{}"))
    return AgentOutput(
        interpretation=raw["interpretation"],
        collection=raw["collection"] or "sales",
        pipeline=pipeline,
        metrics_used=raw["metrics_used"],
        skill=skill,
        proposed_memory=ProposedMemory(**raw["proposed_memory"]) if raw.get("proposed_memory") else None,
        assumptions=raw["assumptions"],
    )


def explain(user: UserContext, question: str, out: AgentOutput, rows: list[dict],
            memories: list[dict], usage: llm.Usage) -> str:
    used = [m for m in memories if any(m["title"].lower().replace(" ", "_") in mu for mu in out.metrics_used)]
    payload = {
        "question": question,
        "interpretation": out.interpretation,
        "definitions_used": [{"title": m["title"], "version": m["version"], "content": m["content"]}
                             for m in used],
        "assumptions": out.assumptions,
        "rows": to_jsonable(rows[:50]),
        "row_count": len(rows),
    }
    return llm.complete(EXPLAIN_RULES, [{"role": "user", "content": json.dumps(payload)}],
                        usage, effort="low", max_tokens=4000)


def ask(user: UserContext, question: str, session_id: str | None = None,
        use_memory: bool = True, use_history: bool = True) -> dict:
    settings = get_settings()
    usage = llm.Usage()
    session_id = session_id or f"s_{uuid.uuid4().hex[:6]}"
    turn_id = _new_turn_id(session_id)

    memories = memory.retrieve(user, question, use_memory=use_memory)
    # Skills are learned team knowledge: "without memory" means without them too
    offered = skills.offered_to(user) if use_memory else []
    history = session_history(user, session_id) if use_history else []

    out = plan(user, question, memories, offered, usage, history=history)
    pipeline = out.pipeline
    skill_used = None

    rows: list[dict] = []
    answer = ""
    governance: dict[str, Any] = {"row_filter": user.rows, "removed_fields": user.hidden_fields}
    execution: dict[str, Any] = {"status": "ok", "attempts": 0, "row_count": 0, "columns": []}
    outcome = "answered"

    for attempt in (1, 2):
        execution["attempts"] = attempt
        try:
            # Inside the try: an unavailable skill or missing parameter is a clean rejection
            pipeline, skill_used = _resolve_pipeline(user, out)
            safe, governance = guard_pipeline(user, out.collection, pipeline, settings.max_result_rows)
        except GuardError as e:
            outcome = "rejected"
            execution["status"] = "rejected"
            governance = {"row_filter": user.rows, "removed_fields": user.hidden_fields,
                          "rejected": e.reason, "hidden_fields_referenced": e.hidden_fields_referenced}
            answer = f"I can't run that query: {e.reason}."
            break
        try:
            rows = list(db.business_db()[out.collection].aggregate(safe))
            break
        except PyMongoError as e:
            if attempt == 2 or out.skill:
                outcome = "failed"
                execution["status"] = "error"
                answer = "The query failed to run."
                break
            # One repair attempt: tell the model what went wrong
            out = plan(user, question, memories, offered, usage, history=history, extra_messages=[
                {"role": "assistant", "content": json.dumps({"pipeline_json": json_util.dumps(pipeline)})},
                {"role": "user", "content": f"That pipeline failed in MongoDB: {e}. Fix it."},
            ])
            # The next pass resolves the new plan, rendering a skill if the replan chose one

    audit.write(user, "query", "collection", out.collection, {
        "turn_id": turn_id, "question": question, "status": execution["status"],
        "filters": governance.get("row_filter"), "removed_fields": governance.get("removed_fields"),
        "rejected": governance.get("rejected"),
        "hidden_fields_referenced": governance.get("hidden_fields_referenced", []),
        "pipeline": json_util.dumps(pipeline),
    })

    if outcome == "answered":
        answer = explain(user, question, out, rows, memories, usage)

    pending = None
    if out.proposed_memory:
        pending = memory.propose(user, out.proposed_memory, source_turn_id=turn_id)

    rows_json = to_jsonable(rows)
    execution.update(row_count=len(rows), columns=_columns(rows_json))
    memories_used = [{"memory_id": m["memory_id"], "title": m["title"], "version": m["version"],
                      "content": m["content"]} for m in memories]

    turn = {
        "session_id": session_id,
        "turn_id": turn_id,
        "user_id": user.user_id,
        "role": user.role,
        "question": question,
        "used_memory": use_memory,
        "memory_ids": [m["memory_id"] for m in memories],
        "skill": skill_used,
        "collection": out.collection,
        "pipeline": json_util.dumps(pipeline),  # stored as Extended JSON text; never result rows
        "metrics_used": out.metrics_used,
        "execution": execution,
        "answer": answer,
        "outcome": outcome,
        "usage": usage.as_dict(),
        "ts": datetime.now(timezone.utc),
    }
    db.app_db()[db.SESSIONS].insert_one(turn)

    return {
        **out.model_dump(mode="json"),
        "pipeline": json.loads(json_util.dumps(pipeline)),
        "session_id": session_id,
        "turn_id": turn_id,
        "use_memory": use_memory,
        "answer": answer,
        "outcome": outcome,
        "columns": execution["columns"],
        "rows": rows_json,
        "memories_used": memories_used,
        "skill_used": skill_used,
        "proposed_memory_pending": pending,
        "governance": governance,
        "usage": usage.as_dict(),
    }
