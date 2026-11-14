"""Episodes and skills (contracts: Episodes and skills).

session turn -> episode (LLM extraction, validated) -> cluster (vector + structure)
-> draft skill (LLM, manual trigger) -> tests -> reviewer publishes.
A skill stores logic, never results, so it always runs with the caller's permissions.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from bson import json_util
from fastapi import HTTPException

from . import audit, db, embeddings, llm
from .guard import GuardError, find_hidden_references, guard_pipeline
from .models import UserContext

SIMILARITY_THRESHOLD = 0.80
READY_EPISODES = 3
READY_USERS = 2
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?$")

# Full-access context used only to test drafted skills
_TESTER = UserContext(user_id="skill_tester", display_name="Skill tester", role="finance_lead",
                      rows={}, hidden_fields=[], can_review=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("embedding", None)
    return doc


# ---------- reading / using skills ----------

def list_all() -> list[dict]:
    return [_public(d) for d in db.app_db()[db.SKILLS].find().sort([("name", 1), ("version", -1)])]


def offered_to(user: UserContext) -> list[dict]:
    """Published skills whose required fields are all visible to the user."""
    out = []
    for s in db.app_db()[db.SKILLS].find({"status": "published"}):
        if not set(s.get("required_fields", [])) & set(user.hidden_fields):
            out.append(_public(s))
    return out


def _coerce(value: Any) -> Any:
    if isinstance(value, str) and ISO_DATE.match(value):
        v = value if "T" in value else value + "T00:00:00Z"
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return value


def render(template: Any, params: dict[str, Any]) -> Any:
    """Replace "{{name}}" strings with parameter values (ISO dates become datetimes)."""
    if isinstance(template, dict):
        return {k: render(v, params) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, params) for v in template]
    if isinstance(template, str):
        m = re.fullmatch(r"\{\{(\w+)\}\}", template)
        if m:
            if m.group(1) not in params:
                raise GuardError(f"Missing skill parameter {m.group(1)!r}")
            return _coerce(params[m.group(1)])
    return template


def render_for(user: UserContext, name: str, params: dict[str, Any]) -> list[dict]:
    skill = next((s for s in offered_to(user) if s["name"] == name), None)
    if skill is None:
        raise GuardError(f"Skill {name!r} is not available to you")
    return render(json_util.loads(skill["pipeline_template"]), params)


def mark_stale_for_metric(metric: str, new_version: int) -> list[str]:
    stale = []
    for s in db.app_db()[db.SKILLS].find({"status": "published", f"metric_versions.{metric}": {"$lt": new_version}}):
        db.app_db()[db.SKILLS].update_one({"_id": s["_id"]}, {"$set": {
            "status": "stale", "stale_reason": f"{metric} has a new version v{new_version}"}})
        stale.append(s["name"])
    return stale


# ---------- episodes ----------

EPISODE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "parameters_json": {"type": "string"},
        "method": {"type": "array", "items": {"type": "string"}},
        "group_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "parameters_json", "method", "group_fields"],
    "additionalProperties": False,
}

EPISODE_RULES = """You turn one analyst question and its MongoDB pipeline into a reusable episode.
- intent: the general analysis with specific values replaced by <placeholders>,
  e.g. "Rank regions by net margin for <period>".
- parameters_json: JSON object of the specific values, copied exactly as they appear in the pipeline.
  Date ranges are always two parameters named "start" and "end" (YYYY-MM-DD).
- method: 3-6 short steps.
- group_fields: the fields in the pipeline's $group _id (field names only, no $)."""


def _structure_key(ep: dict) -> dict:
    return {
        "collection": ep["collection"],
        "metrics": sorted(ep["metrics"]),
        "parameter_names": sorted(ep["parameters"].keys()),
        "group_fields": sorted(ep["group_fields"]),
    }


def _values_in_pipeline(params: dict, pipeline_text: str) -> bool:
    for v in params.values():
        s = str(v)
        if ISO_DATE.match(s):
            s = s[:10]
        if s not in pipeline_text:
            return False
    return True


def extract_episode(turn: dict) -> dict | None:
    """Create an episode from a successful turn. Returns None when rejected."""
    if turn.get("outcome") not in ("answered", "user_confirmed") or turn.get("skill"):
        return None
    usage = llm.Usage()
    raw = llm.complete(EPISODE_RULES, [{"role": "user", "content": json.dumps({
        "question": turn["question"], "pipeline": turn["pipeline"]})}],
        usage, schema=EPISODE_SCHEMA, effort="low", max_tokens=4000)
    params = json.loads(raw["parameters_json"] or "{}")
    if not _values_in_pipeline(params, turn["pipeline"]):
        return None  # lesson from the practice build: values must really be filtered on

    ep = {
        "episode_id": f"ep_{uuid.uuid4().hex[:6]}",
        "turn_id": turn["turn_id"],
        "user_id": turn["user_id"],
        "intent": raw["intent"],
        "parameters": params,
        "metrics": turn.get("metrics_used", []),
        "collection": turn["collection"],
        "group_fields": raw["group_fields"],
        "method": raw["method"],
        "pipeline": turn["pipeline"],
        "embed_model": embeddings.model_name(),
        "embedding": embeddings.embed_one(raw["intent"] + "\n" + "\n".join(raw["method"])),
        "created_at": _now(),
    }
    ep["structure"] = _structure_key(ep)
    ep["cluster_id"] = _assign_cluster(ep)
    db.app_db()[db.EPISODES].insert_one(ep)
    return _public(ep)


def _assign_cluster(ep: dict) -> str:
    best, best_score = None, 0.0
    for other in db.app_db()[db.EPISODES].find({"structure": ep["structure"]}):
        score = embeddings.cosine(ep["embedding"], other["embedding"])
        if score > best_score:
            best, best_score = other, score
    if best is not None and best_score >= SIMILARITY_THRESHOLD:
        return best["cluster_id"]
    return f"c_{uuid.uuid4().hex[:4]}"


def clusters() -> list[dict]:
    pipeline = [
        {"$group": {"_id": "$cluster_id", "episodes": {"$sum": 1},
                    "users": {"$addToSet": "$user_id"}, "intent": {"$first": "$intent"}}},
        {"$sort": {"episodes": -1}},
    ]
    out = []
    for c in db.app_db()[db.EPISODES].aggregate(pipeline):
        ready = c["episodes"] >= READY_EPISODES and len(c["users"]) >= READY_USERS
        out.append({"cluster_id": c["_id"], "episodes": c["episodes"], "users": c["users"],
                    "intent": c["intent"], "ready": ready})
    return out


# ---------- drafting and testing ----------

SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "parameters_json": {"type": "string"},
        "pipeline_template_json": {"type": "string"},
    },
    "required": ["name", "description", "parameters_json", "pipeline_template_json"],
    "additionalProperties": False,
}

SKILL_RULES = """You turn several similar analyses into one reusable MongoDB aggregation template.
- name: snake_case, e.g. "region_margin_ranking".
- parameters_json: JSON object of parameter name -> short description. Date ranges are "start"
  (ISO date, inclusive) and "end" (ISO date, exclusive).
- pipeline_template_json: the pipeline as a JSON array string, with each parameter written as the
  string "{{name}}" in place of its value (dates too, without $date wrappers).
Keep the method of the source pipelines exactly; only replace the specific values."""


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_round(x) for x in v]
    return v


def _run(user: UserContext, pipeline: list[dict]) -> list[dict]:
    safe, _ = guard_pipeline(user, "sales", pipeline)
    return _round(list(db.business_db()["sales"].aggregate(safe)))


def _test(skill: dict, episodes: list[dict]) -> dict:
    from .users import all_users

    template = json_util.loads(skill["pipeline_template"])
    replay = "pass"
    for ep in episodes[:3]:
        try:
            expected = _run(_TESTER, json_util.loads(ep["pipeline"]))
            actual = _run(_TESTER, render(template, ep["parameters"]))
            if expected != actual:
                replay = "fail"
        except Exception:
            replay = "fail"

    permissions = "pass"
    sample_params = episodes[0]["parameters"]
    for user in all_users().values():
        hidden_needed = set(skill["required_fields"]) & set(user.hidden_fields)
        if hidden_needed:
            continue  # never offered to this user (checked by offered_to)
        try:
            rows = _run(user, render(template, sample_params))
            if user.rows and rows and any(
                k in r and r[k] != v for r in rows for k, v in user.rows.items()):
                permissions = "fail"
        except GuardError:
            permissions = "fail"
    return {"replay": replay, "permissions": permissions}


def generate(cluster_id: str | None = None) -> dict:
    ready = [c for c in clusters() if c["ready"]]
    if cluster_id:
        ready = [c for c in ready if c["cluster_id"] == cluster_id]
    if not ready:
        raise HTTPException(409, "No cluster is ready (needs 3 episodes from 2 users)")
    cluster = ready[0]
    episodes = list(db.app_db()[db.EPISODES].find({"cluster_id": cluster["cluster_id"]}))

    usage = llm.Usage()
    raw = llm.complete(SKILL_RULES, [{"role": "user", "content": json.dumps([
        {"intent": e["intent"], "parameters": e["parameters"], "method": e["method"],
         "pipeline": e["pipeline"]} for e in episodes])}], usage, schema=SKILL_SCHEMA)
    template = json.loads(raw["pipeline_template_json"])

    from .agent import SALES_FIELDS
    required = find_hidden_references(template, list(SALES_FIELDS))
    metric_versions: dict[str, int] = {}
    for e in episodes:
        for m in e["metrics"]:
            if "@" in m:
                name, ver = m.split("@", 1)
                metric_versions[name] = max(metric_versions.get(name, 0), int(ver))

    latest = db.app_db()[db.SKILLS].find_one({"name": raw["name"]}, sort=[("version", -1)])
    skill = {
        "name": raw["name"],
        "version": (latest["version"] + 1) if latest else 1,
        "status": "draft",
        "description": raw["description"],
        "parameters": json.loads(raw["parameters_json"]),
        "pipeline_template": json_util.dumps(template),
        "required_fields": required,
        "metric_versions": metric_versions,
        "source_episodes": [e["episode_id"] for e in episodes],
        "cluster_id": cluster["cluster_id"],
        "reviewed_by": None,
        "created_at": _now(),
    }
    skill["test_results"] = _test(skill, episodes)
    db.app_db()[db.SKILLS].insert_one(skill)
    return _public(skill)


def publish(reviewer: UserContext, name: str) -> dict:
    s = db.app_db()[db.SKILLS].find_one({"name": name, "status": {"$in": ["draft", "stale"]}},
                                        sort=[("version", -1)])
    if s is None:
        raise HTTPException(404, f"No draft or stale skill named {name}")
    if any(v != "pass" for v in s.get("test_results", {}).values()):
        raise HTTPException(409, f"Skill tests have not passed: {s.get('test_results')}")
    db.app_db()[db.SKILLS].update_many({"name": name, "status": "published"},
                                       {"$set": {"status": "retired"}})
    db.app_db()[db.SKILLS].update_one({"_id": s["_id"]}, {"$set": {
        "status": "published", "reviewed_by": reviewer.user_id, "published_at": _now()}})
    audit.write(reviewer, "skill_publish", "skill", name, {"version": s["version"]})
    return _public(db.app_db()[db.SKILLS].find_one({"_id": s["_id"]}))


def retire(reviewer: UserContext, name: str, reason: str) -> dict:
    res = db.app_db()[db.SKILLS].update_many(
        {"name": name, "status": {"$in": ["published", "stale", "draft"]}},
        {"$set": {"status": "retired"}})
    if res.matched_count == 0:
        raise HTTPException(404, f"No active skill named {name}")
    audit.write(reviewer, "skill_retire", "skill", name, {"reason": reason})
    return {"name": name, "status": "retired"}
