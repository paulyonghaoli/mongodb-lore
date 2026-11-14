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
from .guard import GuardError, find_hidden_references, guard_pipeline, validate
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
    return _with_sources([_public(d) for d in db.app_db()[db.SKILLS].find().sort([("name", 1), ("version", -1)])])


def _with_sources(found: list[dict]) -> list[dict]:
    """Say where each skill came from: how many episodes, whose, how many are sample data, one question to try."""
    ids = list({i for s in found for i in s.get("source_episodes", [])})
    episodes = {e["episode_id"]: e for e in db.app_db()[db.EPISODES].find(
        {"episode_id": {"$in": ids}}, {"episode_id": 1, "user_id": 1, "turn_id": 1, "synthetic": 1})}
    for s in found:
        mine = [episodes[i] for i in s.get("source_episodes", []) if i in episodes]
        s["sources"] = {"episodes": len(s.get("source_episodes", [])),
                        "users": sorted({e["user_id"] for e in mine}),
                        "sample": sum(1 for e in mine if e.get("synthetic"))}
        turn = db.app_db()[db.SESSIONS].find_one({"turn_id": mine[0]["turn_id"]}, {"question": 1}) if mine else None
        s["example_question"] = turn.get("question") if turn else None
    return found


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


def _missing_values(params: dict, pipeline_text: str) -> list[str]:
    """Names of the parameters whose value does not appear in the pipeline."""
    missing = []
    for name, v in params.items():
        s = str(v)
        if ISO_DATE.match(s):
            s = s[:10]
        if s not in pipeline_text:
            missing.append(name)
    return missing


def skip_reason(turn: dict) -> str | None:
    """Why a turn is not worth an episode, decided before any model call. None when it is."""
    if turn.get("outcome") not in ("answered", "user_confirmed"):
        return f"skipped: outcome is {turn.get('outcome')}"
    if turn.get("skill"):
        return "skipped: the turn reused a skill"
    if turn.get("used_memory") is False:
        # The "without memory" half of a replay ignores the company definitions on purpose
        return "skipped: memory was switched off"
    if db.app_db()[db.EPISODES].find_one({"turn_id": turn["turn_id"]}, {"_id": 1}):
        return "skipped: already extracted"
    return None


def extract(turn: dict) -> tuple[dict | None, str | None]:
    """Create an episode from a turn: (episode, None), or (None, why it was skipped or rejected)."""
    reason = skip_reason(turn)
    if reason:
        return None, reason
    usage = llm.Usage()
    raw = llm.complete(EPISODE_RULES, [{"role": "user", "content": json.dumps({
        "question": turn["question"], "pipeline": turn["pipeline"]})}],
        usage, schema=EPISODE_SCHEMA, effort="low", max_tokens=4000)
    params = json.loads(raw["parameters_json"] or "{}")
    missing = _missing_values(params, turn["pipeline"])
    if missing:
        # lesson from the practice build: values must really be filtered on
        return None, f"rejected: parameter {', '.join(missing)} is not a value in the query"

    ep = {
        # One episode per turn: the ID follows the turn, as in scripts/synthesize_activity.py
        "episode_id": f"ep_{turn['turn_id']}",
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
    return _public(ep), None


def extract_episode(turn: dict) -> dict | None:
    """Create an episode from a successful turn. Returns None when skipped or rejected."""
    return extract(turn)[0]


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
    """Episode clusters, largest first, with what they share and whether a skill may be drafted."""
    groups: dict[str, dict] = {}
    fields = {"cluster_id": 1, "user_id": 1, "intent": 1, "structure": 1, "synthetic": 1}
    for e in db.app_db()[db.EPISODES].find({}, fields):
        g = groups.setdefault(e["cluster_id"], {
            "cluster_id": e["cluster_id"], "episodes": 0, "users": [], "intent": e["intent"],
            "structure": e.get("structure"), "sample": 0, "skills": []})
        g["episodes"] += 1
        g["sample"] += 1 if e.get("synthetic") else 0  # written by scripts/synthesize_activity.py
        if e["user_id"] not in g["users"]:
            g["users"].append(e["user_id"])
    for sk in db.app_db()[db.SKILLS].find({"cluster_id": {"$in": list(groups)}},
                                           {"cluster_id": 1, "name": 1, "version": 1, "status": 1}).sort("version", -1):
        groups[sk["cluster_id"]]["skills"].append({k: sk[k] for k in ("name", "version", "status")})
    out = sorted(groups.values(), key=lambda g: -g["episodes"])
    for g in out:
        g["ready"] = g["episodes"] >= READY_EPISODES and len(g["users"]) >= READY_USERS
    return out


def cluster_episodes(cluster_id: str, limit: int = 50) -> list[dict]:
    """The episodes of one cluster, newest first, with the question each came from. Never result rows."""
    found = list(db.app_db()[db.EPISODES].find({"cluster_id": cluster_id}, {"embedding": 0})
                 .sort("created_at", -1).limit(limit))
    questions = {t["turn_id"]: t.get("question") for t in db.app_db()[db.SESSIONS].find(
        {"turn_id": {"$in": [e["turn_id"] for e in found]}}, {"turn_id": 1, "question": 1})}
    return [{"episode_id": e["episode_id"], "turn_id": e["turn_id"], "user_id": e["user_id"],
             "question": questions.get(e["turn_id"]), "parameters": e.get("parameters", {}),
             "created_at": e.get("created_at"), "sample": bool(e.get("synthetic"))} for e in found]


def learning_status() -> dict:
    """What became of the answered questions asked through the app. Script-generated activity is counted apart."""
    counts = {"extracted": 0, "skipped": 0, "rejected": 0, "error": 0, "processing": 0, "waiting": 0}
    asked = {"outcome": {"$in": ["answered", "user_confirmed"]}, "synthetic": {"$ne": True}}
    for t in db.app_db()[db.SESSIONS].find(asked, {"episode_status": 1}):
        status = t.get("episode_status")
        key = status.split(":", 1)[0] if status else "waiting"
        counts[key] = counts.get(key, 0) + 1
    episodes = db.app_db()[db.EPISODES]
    live = episodes.find_one({"synthetic": {"$ne": True}}, {"created_at": 1}, sort=[("created_at", -1)])
    return {**counts, "live_episodes": episodes.count_documents({"synthetic": {"$ne": True}}),
            "sample_episodes": episodes.count_documents({"synthetic": True}),
            "last_live_episode_at": live.get("created_at") if live else None}


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


MAX_DRAFT_EPISODES = 6   # how many episodes the model sees when it drafts
REPLAY_EPISODES = 3      # how many of those the replay test runs again
NUMBER_TOLERANCE = 5e-4  # two results agree when their numbers differ by rounding only


def _sample(episodes: list[dict], n: int) -> list[dict]:
    """Up to n episodes, newest first, taking users in turn so the sample covers more than one person."""
    def when(e: dict) -> datetime:
        t = e.get("created_at") or datetime.min
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

    by_user: dict[str, list[dict]] = {}
    for e in sorted(episodes, key=when, reverse=True):
        by_user.setdefault(e["user_id"], []).append(e)
    picked: list[dict] = []
    while len(picked) < n and any(by_user.values()):
        for queue in by_user.values():
            if queue and len(picked) < n:
                picked.append(queue.pop(0))
    return picked


def _placeholders(node: Any) -> set[str]:
    if isinstance(node, dict):
        return {name for v in node.values() for name in _placeholders(v)}
    if isinstance(node, list):
        return {name for v in node for name in _placeholders(v)}
    if isinstance(node, str):
        m = re.fullmatch(r"\{\{(\w+)\}\}", node)
        return {m.group(1)} if m else set()
    return set()


def _parse_draft(raw: dict) -> tuple[dict, list]:
    """Check the model's draft before anything is saved. Raises 422 with a reason a reviewer can read."""
    try:
        parameters = json.loads(raw.get("parameters_json") or "{}")
        template = json.loads(raw.get("pipeline_template_json") or "")
    except (TypeError, ValueError):
        raise HTTPException(422, "The draft could not be read: the model did not return valid JSON. Try again.")
    if not isinstance(parameters, dict) or not isinstance(template, list):
        raise HTTPException(422, "The draft could not be read: parameters must be an object and the template a list.")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", raw.get("name") or ""):
        raise HTTPException(422, f"The draft's name {raw.get('name')!r} is not snake_case. Try again.")
    used = _placeholders(template)
    if used != set(parameters):
        raise HTTPException(422, f"The draft declares parameters {sorted(parameters)} "
                                 f"but its template uses {sorted(used)}. Try again.")
    try:
        validate("sales", render(template, {name: "x" for name in used}))
    except GuardError as e:
        raise HTTPException(422, f"The draft's query is not allowed: {e.reason}")
    return parameters, template


def _run(user: UserContext, pipeline: list[dict]) -> list[dict]:
    safe, _ = guard_pipeline(user, "sales", pipeline)
    return list(db.business_db()["sales"].aggregate(safe))


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _by_label(rows: list[dict]) -> dict[tuple, list[list[float]]]:
    """Result rows keyed by their labels (the group values), each reduced to its numbers."""
    out: dict[tuple, list[list[float]]] = {}
    for row in rows:
        labels = tuple(sorted(str(v) for v in row.values() if v is not None and not _is_number(v)))
        out.setdefault(labels, []).append(sorted(float(v) for v in row.values() if _is_number(v)))
    return out


def _numbers_agree(a: list[float], b: list[float]) -> bool:
    """Every number of the shorter row appears in the longer one, so extra helper columns are allowed."""
    small, large = (a, list(b)) if len(a) <= len(b) else (b, list(a))
    if not small:
        return not large
    for x in small:
        match = next((y for y in large if abs(x - y) <= max(NUMBER_TOLERANCE, 1e-6 * abs(y))), None)
        if match is None:
            return False
        large.remove(match)
    return True


def compare_results(expected: list[dict], actual: list[dict]) -> str | None:
    """None when two results say the same thing, otherwise what differs.

    Rows are matched on their labels. Column names, column order and row order are ignored, because
    two people's queries for the same analysis rarely agree on those. The numbers must agree.
    """
    want, got = _by_label(expected), _by_label(actual)
    if set(want) != set(got):
        missing, extra = sorted(set(want) - set(got)), sorted(set(got) - set(want))
        return f"different rows: {len(missing)} missing, {len(extra)} unexpected"
    for labels, rows in want.items():
        others = got[labels]
        if len(rows) != len(others) or not all(_numbers_agree(x, y) for x, y in zip(sorted(rows), sorted(others))):
            return f"different numbers for {', '.join(labels) or 'the total'}"
    return None


def _replay_test(template: list, episodes: list[dict]) -> list[dict]:
    """Run each source query and the filled-in template with full access: they must give the same result."""
    details = []
    for ep in episodes[:REPLAY_EPISODES]:
        entry = {"episode_id": ep["episode_id"], "user_id": ep["user_id"], "parameters": ep["parameters"]}
        try:
            expected = _run(_TESTER, json_util.loads(ep["pipeline"]))
            actual = _run(_TESTER, render(template, ep["parameters"]))
            problem = compare_results(expected, actual)
            entry.update(result="fail" if problem else "pass", rows=len(actual), reason=problem)
        except Exception as e:
            entry.update(result="fail", rows=0, reason=str(e)[:200])
        details.append(entry)
    return details


def _permission_test(skill: dict, template: list, params: dict) -> list[dict]:
    """Run the skill as every user it is offered to: each must get the full result cut down to their rows."""
    from .users import all_users

    details = []
    for user in all_users().values():
        entry: dict[str, Any] = {"user_id": user.user_id, "role": user.role}
        hidden = sorted(set(skill["required_fields"]) & set(user.hidden_fields))
        if hidden:
            entry.update(result="not offered", reason=f"needs {', '.join(hidden)}")
        else:
            try:
                row_filter = [{"$match": dict(user.rows)}] if user.rows else []
                allowed = _run(_TESTER, row_filter + render(template, params))
                problem = compare_results(allowed, _run(user, render(template, params)))
                entry.update(result="fail" if problem else "pass", reason=problem)
            except Exception as e:
                entry.update(result="fail", reason=str(e)[:200])
        details.append(entry)
    return details


def _test(skill: dict, episodes: list[dict]) -> dict:
    """Run both tests and keep the detail on the skill. The result keeps the contract shape."""
    template = json_util.loads(skill["pipeline_template"])
    replay = _replay_test(template, episodes)
    permissions = _permission_test(skill, template, episodes[0]["parameters"])
    skill["test_details"] = {"replay": replay, "permissions": permissions}
    return {"replay": "pass" if replay and all(r["result"] == "pass" for r in replay) else "fail",
            "permissions": "fail" if any(r["result"] == "fail" for r in permissions) else "pass"}


AUTO_DRAFTER = "learning_worker"  # `drafted_by` on a skill the worker drafted without anyone asking


def draft_if_ready(cluster_id: str) -> dict | None:
    """Automatic drafting: draft a skill when the cluster is ready and nothing was ever drafted from it.

    Returns the draft, or None when there is nothing to do. Only the drafting is automatic: the draft
    is not offered to the agent until a reviewer publishes it.
    """
    cluster = next((c for c in clusters() if c["cluster_id"] == cluster_id), None)
    if cluster is None or not cluster["ready"] or cluster["skills"]:
        return None
    return generate(cluster_id, drafted_by=None)


def generate(cluster_id: str | None = None, drafted_by: UserContext | None = None) -> dict:
    """Draft a skill from a ready cluster and test it. `drafted_by` is the reviewer who asked, or None
    when the learning worker drafted it on its own."""
    ready = [c for c in clusters() if c["ready"]]
    if cluster_id:
        ready = [c for c in ready if c["cluster_id"] == cluster_id]
    if not ready:
        raise HTTPException(409, "No cluster is ready (needs 3 episodes from 2 users)")
    cluster = ready[0]
    episodes = list(db.app_db()[db.EPISODES].find({"cluster_id": cluster["cluster_id"]}))
    # The model drafts from a recent sample: a cluster can hold dozens of near-identical episodes
    sample = _sample(episodes, MAX_DRAFT_EPISODES)

    usage = llm.Usage()
    raw = llm.complete(SKILL_RULES, [{"role": "user", "content": json.dumps([
        {"intent": e["intent"], "parameters": e["parameters"], "method": e["method"],
         "pipeline": e["pipeline"]} for e in sample])}], usage, schema=SKILL_SCHEMA)
    parameters, template = _parse_draft(raw)

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
        "parameters": parameters,
        "pipeline_template": json_util.dumps(template),
        "required_fields": required,
        "metric_versions": metric_versions,
        "source_episodes": [e["episode_id"] for e in episodes],
        "drafted_from": [e["episode_id"] for e in sample],
        "drafted_by": drafted_by.user_id if drafted_by else AUTO_DRAFTER,
        "cluster_id": cluster["cluster_id"],
        "reviewed_by": None,
        "created_at": _now(),
    }
    skill["test_results"] = _test(skill, sample)
    db.app_db()[db.SKILLS].insert_one(skill)
    # actor None is recorded as "system": nobody asked for this draft
    audit.write(drafted_by, "skill_draft", "skill", skill["name"], {
        "version": skill["version"], "cluster_id": skill["cluster_id"], "drafted_by": skill["drafted_by"],
        "tests": skill["test_results"]})
    return _with_sources([_public(skill)])[0]


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
