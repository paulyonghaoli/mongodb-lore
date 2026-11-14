"""Skills workstream, offline: mongomock, hash embeddings and a fake LLM.

session turn -> episode -> cluster -> draft skill -> tests -> publish / retire -> offered to the agent.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from bson import json_util
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import OperationFailure

from app import audit, db, embeddings, llm, skills
from app.guard import GuardError
from app.main import app
from app.users import get_user
from app.workers import learning


def day(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def rate_pipeline(start, end, group: str = "category") -> list[dict]:
    """Return rate by one field for a period, in the shape the agent writes (no $round: mongomock lacks it)."""
    return [
        {"$match": {"date": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": f"${group}", "revenue": {"$sum": "$revenue"}, "returns": {"$sum": "$returns"}}},
        {"$project": {"_id": 0, group: "$_id", "return_rate": {"$divide": ["$returns", "$revenue"]}}},
        {"$sort": {group: 1}},
    ]


def make_turn(turn_id: str, user_id: str, start: str = "2026-09-01", end: str = "2026-10-01",
              group: str = "category", **over) -> dict:
    """A session turn as app/agent.py saves it."""
    turn = {
        "session_id": turn_id.rsplit("_t", 1)[0], "turn_id": turn_id, "user_id": user_id,
        "role": get_user(user_id).role, "question": f"Return rate by {group} from {start} to {end}",
        "used_memory": True, "memory_ids": ["mem_return_rate_v1"], "skill": None, "collection": "sales",
        "pipeline": json_util.dumps(rate_pipeline(day(start), day(end), group)),
        "metrics_used": ["return_rate@1"], "outcome": "answered", "ts": datetime.now(timezone.utc),
    }
    turn.update(over)
    return turn


class FakeLLM:
    """Stands in for llm.complete. Answers the episode and the skill prompts from what it is sent."""

    def __init__(self):
        self.calls: list[dict] = []
        self.episode: dict = {}        # fields to override in the episode answer
        self.template: list | None = None  # template to return instead of the faithful one
        self.skill: dict = {}          # fields to override in the skill answer

    def __call__(self, system, messages, usage, schema=None, **kw):
        self.calls.append({"system": system, "messages": messages, "schema": schema})
        payload = json.loads(messages[0]["content"])
        if schema is skills.EPISODE_SCHEMA:
            start, end = re.findall(r"\d{4}-\d{2}-\d{2}", payload["pipeline"])[:2]
            group = re.search(r'"_id": "\$(\w+)"', payload["pipeline"]).group(1)
            return {"intent": f"Rank {group} by return rate for <period>",
                    "parameters_json": json.dumps({"start": start, "end": end}),
                    "method": ["Filter to the period", f"Group by {group}", "Divide returns by revenue"],
                    "group_fields": [group], **self.episode}
        if schema is skills.SKILL_SCHEMA:
            group = re.search(r'"_id": "\$(\w+)"', payload[0]["pipeline"]).group(1)
            return {"name": f"return_rate_by_{group}", "description": f"Return rate by {group} for a date range",
                    "parameters_json": json.dumps({"start": "ISO date, inclusive", "end": "ISO date, exclusive"}),
                    "pipeline_template_json": json.dumps(self.template or rate_pipeline("{{start}}", "{{end}}", group)),
                    **self.skill}
        raise AssertionError("unexpected prompt")


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "complete", fake)
    return fake


@pytest.fixture
def sales(mock_db, monkeypatch):
    """A little sales data whose return rate differs by month, region and category."""
    mock_db[db.SALES].insert_many([
        {"date": day(f"2026-{month:02d}-05"), "store_id": region[0] + "00", "store_name": f"{region} store",
         "region": region, "category": category, "product": "tent", "units": 2, "revenue": 100.0,
         "returns": float(month + 3 * r + 7 * c), "supplier_cost": 50.0, "discount": 0.0}
        for month in (8, 9, 10) for r, region in enumerate(("East", "West")) for c, category in enumerate(("Camping", "Home"))
    ])
    # mongomock lacks $unset; swap in the equivalent $project exclusion (same trick as tests/test_agent.py)
    real_guard = skills.guard_pipeline

    def guard(*a, **kw):
        safe, gov = real_guard(*a, **kw)
        return [{"$project": {f: 0 for f in s["$unset"]}} if "$unset" in s else s for s in safe], gov

    monkeypatch.setattr(skills, "guard_pipeline", guard)
    return mock_db


PERIODS = [("s_a_t1", "alex", "2026-09-01", "2026-10-01"), ("s_b_t1", "sam", "2026-08-01", "2026-09-01"),
           ("s_c_t1", "fatima", "2026-10-01", "2026-11-01")]


@pytest.fixture
def ready_cluster(fake_llm, sales) -> str:
    """Three episodes of the same analysis from three users."""
    for turn_id, user_id, start, end in PERIODS:
        skills.extract_episode(make_turn(turn_id, user_id, start, end))
    (cluster,) = skills.clusters()
    assert cluster["ready"]
    return cluster["cluster_id"]


@pytest.fixture
def client():
    return TestClient(app)


def episodes_count() -> int:
    return db.app_db()[db.EPISODES].count_documents({})


# ---------- rendering, offering, staleness ----------

def test_render_replaces_params_and_dates():
    tpl = [{"$match": {"date": {"$gte": "{{start}}", "$lt": "{{end}}"}, "region": "{{region}}"}}]
    out = skills.render(tpl, {"start": "2026-07-01", "end": "2026-10-01", "region": "East"})
    assert out[0]["$match"]["date"]["$gte"] == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert out[0]["$match"]["region"] == "East"


def test_skill_needing_hidden_field_not_offered():
    db.app_db()[db.SKILLS].insert_one({
        "name": "region_margin_ranking", "version": 1, "status": "published",
        "required_fields": ["revenue", "returns", "supplier_cost"], "pipeline_template": "[]",
        "parameters": {}, "description": "", "metric_versions": {"net_margin": 2}})
    assert [s["name"] for s in skills.offered_to(get_user("fatima"))] == ["region_margin_ranking"]
    assert skills.offered_to(get_user("alex")) == []


def test_new_metric_version_marks_skill_stale():
    db.app_db()[db.SKILLS].insert_one({"name": "s", "version": 1, "status": "published",
                                       "required_fields": [], "metric_versions": {"net_margin": 1}})
    assert skills.mark_stale_for_metric("net_margin", 2) == ["s"]
    assert db.app_db()[db.SKILLS].find_one({"name": "s"})["status"] == "stale"


# ---------- session turn -> episode ----------

def test_answered_turn_becomes_episode(fake_llm):
    ep = skills.extract_episode(make_turn("s_a_t1", "alex"))
    assert (ep["turn_id"], ep["user_id"]) == ("s_a_t1", "alex")
    assert ep["intent"] == "Rank category by return rate for <period>"
    assert ep["parameters"] == {"start": "2026-09-01", "end": "2026-10-01"}
    assert ep["structure"] == {"collection": "sales", "metrics": ["return_rate@1"],
                               "parameter_names": ["end", "start"], "group_fields": ["category"]}
    assert ep["cluster_id"].startswith("c_")
    assert "embedding" not in ep  # the returned view never carries the vector
    stored = db.app_db()[db.EPISODES].find_one({"turn_id": "s_a_t1"})
    assert stored["embedding"] and stored["embed_model"].startswith("hash-")
    assert stored["pipeline"] == make_turn("s_a_t1", "alex")["pipeline"]  # the method is kept, never the rows


@pytest.mark.parametrize("change", [
    {"outcome": "rejected"},                       # blocked by the guard
    {"outcome": "failed"},                         # the query did not run
    {"skill": {"name": "x", "parameters": {}}},    # the turn reused a skill: nothing new to learn
    {"used_memory": False},                        # the "without memory" half of a replay
])
def test_turns_that_never_become_episodes(fake_llm, change):
    assert skills.extract_episode(make_turn("s_a_t1", "alex", **change)) is None
    assert fake_llm.calls == []  # decided before any model call
    assert episodes_count() == 0


def test_episode_rejected_when_a_parameter_value_is_not_in_the_pipeline(fake_llm):
    fake_llm.episode = {"parameters_json": json.dumps({"start": "2026-09-01", "end": "2026-10-01", "region": "East"})}
    assert skills.extract_episode(make_turn("s_a_t1", "alex")) is None
    assert episodes_count() == 0


def test_one_episode_per_turn_named_after_it(fake_llm):
    first = skills.extract_episode(make_turn("s_a_t1", "alex"))
    assert first["episode_id"] == "ep_s_a_t1"
    again, reason = skills.extract(make_turn("s_a_t1", "alex"))
    assert again is None and reason == "skipped: already extracted"
    assert episodes_count() == 1 and len(fake_llm.calls) == 1  # no second model call either


def test_extract_says_why_a_turn_gave_no_episode(fake_llm):
    assert skills.extract(make_turn("s_a_t1", "alex", outcome="rejected"))[1] == "skipped: outcome is rejected"
    assert skills.extract(make_turn("s_a_t2", "alex", used_memory=False))[1] == "skipped: memory was switched off"
    fake_llm.episode = {"parameters_json": json.dumps({"start": "2026-09-01", "end": "2026-10-01", "region": "East"})}
    assert skills.extract(make_turn("s_a_t3", "alex"))[1] == "rejected: parameter region is not a value in the query"


# ---------- clustering ----------

def test_same_analysis_for_another_period_joins_the_cluster(fake_llm):
    a = skills.extract_episode(make_turn("s_a_t1", "alex", "2026-09-01", "2026-10-01"))
    b = skills.extract_episode(make_turn("s_b_t1", "sam", "2026-08-01", "2026-09-01"))
    assert a["cluster_id"] == b["cluster_id"]


def test_different_group_field_starts_a_new_cluster(fake_llm):
    a = skills.extract_episode(make_turn("s_a_t1", "alex", group="category"))
    b = skills.extract_episode(make_turn("s_b_t1", "sam", group="region"))
    assert a["cluster_id"] != b["cluster_id"]
    # The wording alone is similar enough to merge them; the structure key is what keeps them apart.
    vec = {e["turn_id"]: e["embedding"] for e in db.app_db()[db.EPISODES].find()}
    assert embeddings.cosine(vec["s_a_t1"], vec["s_b_t1"]) >= skills.SIMILARITY_THRESHOLD


def test_different_metric_version_starts_a_new_cluster(fake_llm):
    a = skills.extract_episode(make_turn("s_a_t1", "alex"))
    b = skills.extract_episode(make_turn("s_b_t1", "sam", metrics_used=["return_rate@2"]))
    assert a["cluster_id"] != b["cluster_id"]


def test_cluster_is_ready_at_three_episodes_from_two_users(fake_llm):
    skills.extract_episode(make_turn("s_a_t1", "alex", "2026-09-01", "2026-10-01"))
    skills.extract_episode(make_turn("s_a_t2", "alex", "2026-08-01", "2026-09-01"))
    assert [c["ready"] for c in skills.clusters()] == [False]  # two episodes
    skills.extract_episode(make_turn("s_a_t3", "alex", "2026-10-01", "2026-11-01"))
    assert [c["ready"] for c in skills.clusters()] == [False]  # three episodes, one user
    skills.extract_episode(make_turn("s_b_t1", "sam", "2026-09-01", "2026-10-01"))
    (cluster,) = skills.clusters()
    assert cluster["ready"] and cluster["episodes"] == 4 and sorted(cluster["users"]) == ["alex", "sam"]


# ---------- drafting and testing ----------

def test_generate_needs_a_ready_cluster(fake_llm):
    skills.extract_episode(make_turn("s_a_t1", "alex"))
    with pytest.raises(HTTPException) as e:
        skills.generate()
    assert e.value.status_code == 409


def test_draft_from_ready_cluster(ready_cluster):
    s = skills.generate(ready_cluster)
    assert (s["name"], s["version"], s["status"], s["reviewed_by"]) == ("return_rate_by_category", 1, "draft", None)
    assert s["parameters"] == {"start": "ISO date, inclusive", "end": "ISO date, exclusive"}
    assert s["required_fields"] == ["category", "date", "returns", "revenue"]
    assert s["metric_versions"] == {"return_rate": 1}
    assert s["cluster_id"] == ready_cluster and len(s["source_episodes"]) == 3
    assert json.loads(s["pipeline_template"])[0]["$match"]["date"] == {"$gte": "{{start}}", "$lt": "{{end}}"}
    assert s["test_results"] == {"replay": "pass", "permissions": "pass"}


def test_replay_test_fails_when_the_template_changes_the_result(ready_cluster, fake_llm):
    fake_llm.template = rate_pipeline("{{start}}", "{{end}}", "region")  # groups by the wrong field
    s = skills.generate(ready_cluster)
    assert s["test_results"]["replay"] == "fail"


def test_generating_again_gives_the_next_version(ready_cluster):
    assert skills.generate(ready_cluster)["version"] == 1
    assert skills.generate(ready_cluster)["version"] == 2


def test_the_model_drafts_from_a_recent_sample_covering_several_users(fake_llm, sales):
    months = [("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-10-01"), ("2026-10-01", "2026-11-01")]
    for i in range(9):  # alex asks seven times, sam twice
        skills.extract_episode(make_turn(f"s_{i}_t1", "sam" if i in (0, 5) else "alex", *months[i % 3]))
    s = skills.generate()
    sent = json.loads(fake_llm.calls[-1]["messages"][0]["content"])
    assert len(sent) == skills.MAX_DRAFT_EPISODES
    assert len(s["source_episodes"]) == 9 and len(s["drafted_from"]) == skills.MAX_DRAFT_EPISODES
    users = {db.app_db()[db.EPISODES].find_one({"episode_id": i})["user_id"] for i in s["drafted_from"]}
    assert users == {"alex", "sam"}  # the minority user is in the sample
    assert len(s["test_details"]["replay"]) == skills.REPLAY_EPISODES


@pytest.mark.parametrize("broken, message", [
    ({"pipeline_template_json": "[{not json"}, "valid JSON"),
    ({"name": "Return Rate!"}, "snake_case"),
    ({"parameters_json": json.dumps({"start": "x"})}, "declares parameters ['start'] but its template uses ['end', 'start']"),
    ({"pipeline_template_json": json.dumps([{"$lookup": {"from": "memories", "as": "m"}}]),
      "parameters_json": "{}"}, "not allowed"),
])
def test_a_bad_draft_from_the_model_is_refused_and_not_saved(ready_cluster, fake_llm, broken, message):
    fake_llm.skill = broken
    with pytest.raises(HTTPException) as e:
        skills.generate(ready_cluster)
    assert e.value.status_code == 422 and message in e.value.detail
    assert db.app_db()[db.SKILLS].count_documents({}) == 0


def test_compare_results_looks_at_values_not_at_column_names_or_order():
    a = [{"category": "Camping", "revenue": 200.0, "return_rate": 0.1321}, {"category": "Home", "revenue": 100.0, "return_rate": 0.05}]
    renamed = [{"rate": 0.05, "cat": "Home", "sales": 100.0}, {"rate": 0.13214, "cat": "Camping", "sales": 200.0}]
    assert skills.compare_results(a, renamed) is None                      # other names, other order, rounding
    assert skills.compare_results(a, [{"c": "Camping", "r": 0.1321}, {"c": "Home", "r": 0.05}]) is None  # fewer columns
    assert skills.compare_results(a, [{"c": "Camping", "r": 0.20}, {"c": "Home", "r": 0.05}]) == "different numbers for Camping"
    assert skills.compare_results(a, a[:1]) == "different rows: 1 missing, 0 unexpected"
    assert skills.compare_results(a, [{"category": "East", "return_rate": 0.1321}, {"category": "Home", "return_rate": 0.05}]) \
        == "different rows: 1 missing, 1 unexpected"


def test_replay_passes_when_a_source_query_names_its_columns_differently(fake_llm, sales):
    other_names = [
        {"$match": {"date": {"$gte": day("2026-10-01"), "$lt": day("2026-11-01")}}},
        {"$group": {"_id": "$category", "sales": {"$sum": "$revenue"}, "refunds": {"$sum": "$returns"}}},
        {"$project": {"_id": 0, "cat": "$_id", "sales": 1, "rate": {"$divide": ["$refunds", "$sales"]}}},
        {"$sort": {"rate": -1}},
    ]
    skills.extract_episode(make_turn("s_a_t1", "alex", "2026-09-01", "2026-10-01"))
    skills.extract_episode(make_turn("s_b_t1", "sam", "2026-08-01", "2026-09-01"))
    skills.extract_episode(make_turn("s_c_t1", "fatima", "2026-10-01", "2026-11-01", pipeline=json_util.dumps(other_names)))
    s = skills.generate()
    assert [r["result"] for r in s["test_details"]["replay"]] == ["pass", "pass", "pass"]
    assert s["test_results"]["replay"] == "pass"


def test_test_details_say_what_was_run_and_for_whom(ready_cluster):
    s = skills.generate(ready_cluster)
    replay = s["test_details"]["replay"]
    assert sorted(r["user_id"] for r in replay) == ["alex", "fatima", "sam"]
    assert all(r["result"] == "pass" and r["rows"] == 2 and r["reason"] is None for r in replay)
    assert {r["user_id"]: r["result"] for r in s["test_details"]["permissions"]} == \
        {"fatima": "pass", "alex": "pass", "sam": "pass"}


def test_replay_detail_names_the_episode_that_failed(ready_cluster, fake_llm):
    fake_llm.template = rate_pipeline("{{start}}", "{{end}}", "region")
    s = skills.generate(ready_cluster)
    assert all(r["result"] == "fail" and r["reason"].startswith("different rows") for r in s["test_details"]["replay"])


def test_permission_test_fails_when_a_restricted_user_gets_other_rows(ready_cluster, monkeypatch):
    guarded = skills.guard_pipeline

    def leaky(user, *a, **kw):  # a guard that forgets the store manager's row filter
        safe, gov = guarded(user, *a, **kw)
        return [s for s in safe if not (user.user_id == "sam" and s == {"$match": {"region": "East"}})], gov

    monkeypatch.setattr(skills, "guard_pipeline", leaky)
    s = skills.generate(ready_cluster)
    by_user = {r["user_id"]: r for r in s["test_details"]["permissions"]}
    assert by_user["sam"]["result"] == "fail" and by_user["alex"]["result"] == "pass"
    assert s["test_results"] == {"replay": "pass", "permissions": "fail"}


def test_a_skill_needing_a_hidden_field_is_tested_only_for_users_who_may_run_it(fake_llm, sales):
    cost = [
        {"$match": {"date": {"$gte": day("2026-09-01"), "$lt": day("2026-10-01")}}},
        {"$group": {"_id": "$category", "revenue": {"$sum": "$revenue"}, "cost": {"$sum": "$supplier_cost"}}},
        {"$project": {"_id": 0, "category": "$_id", "cost_share": {"$divide": ["$cost", "$revenue"]}}},
        {"$sort": {"category": 1}},
    ]
    template = json.loads(json_util.dumps(cost).replace('{"$date": "2026-09-01T00:00:00Z"}', '"{{start}}"')
                          .replace('{"$date": "2026-10-01T00:00:00Z"}', '"{{end}}"'))
    fake_llm.template = template
    for turn_id in ("s_a_t1", "s_a_t2", "s_a_t3"):
        skills.extract_episode(make_turn(turn_id, "fatima", pipeline=json_util.dumps(cost), metrics_used=[]))
    db.app_db()[db.EPISODES].update_one({"turn_id": "s_a_t3"}, {"$set": {"user_id": "second_finance_user"}})
    s = skills.generate()
    assert "supplier_cost" in s["required_fields"]
    assert {r["user_id"]: (r["result"], r["reason"]) for r in s["test_details"]["permissions"]} == {
        "fatima": ("pass", None), "alex": ("not offered", "needs supplier_cost"), "sam": ("not offered", "needs supplier_cost")}
    assert s["test_results"]["permissions"] == "pass"


# ---------- where a skill came from ----------

def test_skill_list_says_where_each_skill_came_from(ready_cluster, mock_db):
    mock_db[db.SESSIONS].insert_many([make_turn(t, u, a, b) for t, u, a, b in PERIODS])
    mock_db[db.EPISODES].update_many({"user_id": {"$in": ["sam", "fatima"]}}, {"$set": {"synthetic": True}})
    drafted = skills.generate(ready_cluster)
    (listed,) = skills.list_all()
    assert drafted["sources"] == listed["sources"] == {"episodes": 3, "users": ["alex", "fatima", "sam"], "sample": 2}
    assert listed["example_question"].startswith("Return rate by category from ")


def test_clusters_show_structure_sample_count_and_skills_drafted(ready_cluster, mock_db):
    mock_db[db.EPISODES].update_one({"user_id": "sam"}, {"$set": {"synthetic": True}})
    skills.generate(ready_cluster)
    (cluster,) = skills.clusters()
    assert cluster["sample"] == 1 and cluster["structure"]["group_fields"] == ["category"]
    assert cluster["skills"] == [{"name": "return_rate_by_category", "version": 1, "status": "draft"}]


def test_cluster_episodes_are_for_the_reviewer_and_carry_the_question(ready_cluster, client, mock_db):
    mock_db[db.SESSIONS].insert_many([make_turn(t, u, a, b) for t, u, a, b in PERIODS])
    url = f"/api/skills/clusters/{ready_cluster}/episodes"
    assert client.get(url, headers={"X-User": "alex"}).status_code == 403  # other people's questions
    found = client.get(url, headers={"X-User": "fatima"}).json()
    assert sorted(e["user_id"] for e in found) == ["alex", "fatima", "sam"]
    assert all(e["question"].startswith("Return rate by category") and e["sample"] is False for e in found)
    assert all("pipeline" not in e and "embedding" not in e for e in found)


def test_learning_status_counts_what_became_of_answered_turns(fake_llm, mock_db, client):
    mock_db[db.SESSIONS].insert_many([
        make_turn("s_a_t1", "alex"), make_turn("s_a_t2", "alex", used_memory=False),
        make_turn("s_a_t3", "alex", outcome="rejected")])
    learning.backlog()
    mock_db[db.SESSIONS].insert_one(make_turn("s_b_t1", "sam"))  # saved after the worker last looked
    # activity written by scripts/synthesize_activity.py is counted apart from questions asked in the app
    mock_db[db.SESSIONS].insert_one(make_turn("s_syn_t1", "alex", synthetic=True, episode_status="extracted"))
    mock_db[db.EPISODES].insert_one({"episode_id": "ep_s_syn_t1", "turn_id": "s_syn_t1", "user_id": "alex", "cluster_id": "c_x",
                                     "intent": "x", "synthetic": True})
    status = client.get("/api/skills/learning", headers={"X-User": "sam"}).json()
    assert (status["extracted"], status["skipped"], status["waiting"]) == (1, 1, 1)
    assert (status["live_episodes"], status["sample_episodes"]) == (1, 1)


def test_only_the_reviewer_can_draft(ready_cluster, client):
    assert client.post("/api/skills/generate", json={"cluster_id": ready_cluster}, headers={"X-User": "alex"}).status_code == 403
    res = client.post("/api/skills/generate", json={"cluster_id": ready_cluster}, headers={"X-User": "fatima"})
    assert res.status_code == 200 and res.json()["status"] == "draft"


# ---------- publishing, retiring, offering ----------

def test_draft_with_failed_tests_cannot_be_published(ready_cluster, fake_llm):
    fake_llm.template = rate_pipeline("{{start}}", "{{end}}", "region")
    s = skills.generate(ready_cluster)
    with pytest.raises(HTTPException) as e:
        skills.publish(get_user("fatima"), s["name"])
    assert e.value.status_code == 409
    assert db.app_db()[db.SKILLS].find_one({"name": s["name"]})["status"] == "draft"


def test_publish_records_reviewer_retires_older_version_and_audits(ready_cluster):
    fatima = get_user("fatima")
    name = skills.generate(ready_cluster)["name"]
    skills.publish(fatima, name)
    skills.generate(ready_cluster)
    out = skills.publish(fatima, name)
    assert (out["version"], out["status"], out["reviewed_by"]) == (2, "published", "fatima")
    assert {s["version"]: s["status"] for s in skills.list_all()} == {1: "retired", 2: "published"}
    events = [e for e in audit.recent() if e["action"] == "skill_publish"]
    assert len(events) == 2
    assert all(e["actor"] == "fatima" and e["target"] == {"kind": "skill", "id": name} for e in events)


def test_publish_unknown_skill_is_404():
    with pytest.raises(HTTPException) as e:
        skills.publish(get_user("fatima"), "no_such_skill")
    assert e.value.status_code == 404


def test_only_published_skills_are_offered_and_retire_withdraws_them(ready_cluster):
    fatima, alex = get_user("fatima"), get_user("alex")
    name = skills.generate(ready_cluster)["name"]
    assert skills.offered_to(alex) == []  # a draft is never offered
    skills.publish(fatima, name)
    assert [s["name"] for s in skills.offered_to(alex)] == [name]
    skills.retire(fatima, name, "No longer used")
    assert skills.offered_to(alex) == []
    (event,) = [e for e in audit.recent() if e["action"] == "skill_retire"]
    assert event["details"] == {"reason": "No longer used"}


def test_render_for_fills_a_published_template(ready_cluster):
    name = skills.generate(ready_cluster)["name"]
    skills.publish(get_user("fatima"), name)
    pipeline = skills.render_for(get_user("alex"), name, {"start": "2026-09-01", "end": "2026-10-01"})
    assert pipeline[0]["$match"]["date"] == {"$gte": day("2026-09-01"), "$lt": day("2026-10-01")}


def test_render_for_refuses_a_draft_and_a_missing_parameter(ready_cluster):
    alex = get_user("alex")
    name = skills.generate(ready_cluster)["name"]
    with pytest.raises(GuardError):
        skills.render_for(alex, name, {"start": "2026-09-01", "end": "2026-10-01"})
    skills.publish(get_user("fatima"), name)
    with pytest.raises(GuardError):
        skills.render_for(alex, name, {"start": "2026-09-01"})


# ---------- routes ----------

def test_only_the_reviewer_can_publish_or_retire(ready_cluster, client):
    name = skills.generate(ready_cluster)["name"]
    assert client.post(f"/api/skills/{name}/publish", headers={"X-User": "alex"}).status_code == 403
    assert client.post(f"/api/skills/{name}/retire", json={"reason": "x"}, headers={"X-User": "sam"}).status_code == 403
    res = client.post(f"/api/skills/{name}/publish", headers={"X-User": "fatima"})
    assert res.status_code == 200 and res.json()["status"] == "published"


def test_skill_list_tells_each_user_whether_the_skill_is_offered(client):
    db.app_db()[db.SKILLS].insert_one({
        "name": "footwear_cost_share", "version": 1, "status": "published", "description": "", "parameters": {},
        "required_fields": ["category", "supplier_cost"], "pipeline_template": "[]", "metric_versions": {}})
    offered = {u: client.get("/api/skills", headers={"X-User": u}).json()["skills"][0]["offered_to_you"]
               for u in ("fatima", "alex", "sam")}
    assert offered == {"fatima": True, "alex": False, "sam": False}


def test_clusters_route_lists_readiness(ready_cluster, client):
    (cluster,) = client.get("/api/skills/clusters", headers={"X-User": "alex"}).json()
    assert cluster["cluster_id"] == ready_cluster and cluster["ready"] and cluster["episodes"] == 3


# ---------- learning worker ----------

def test_worker_extracts_answered_turns_once(fake_llm, mock_db):
    mock_db[db.SESSIONS].insert_many([make_turn("s_a_t1", "alex"), make_turn("s_b_t1", "sam", outcome="rejected")])
    learning.backlog()
    status = {t["turn_id"]: t.get("episode_status") for t in mock_db[db.SESSIONS].find()}
    assert status == {"s_a_t1": "extracted", "s_b_t1": None}  # the backlog only looks at answered turns
    learning.backlog()
    assert episodes_count() == 1  # a processed turn is not picked up again


def test_worker_marks_a_rejected_extraction(fake_llm, mock_db):
    fake_llm.episode = {"parameters_json": json.dumps({"start": "1999-01-01", "end": "2026-10-01"})}
    mock_db[db.SESSIONS].insert_one(make_turn("s_a_t1", "alex"))
    learning.backlog()
    status = mock_db[db.SESSIONS].find_one({"turn_id": "s_a_t1"})["episode_status"]
    assert status == "rejected: parameter start is not a value in the query"


def test_worker_keeps_going_after_a_turn_fails(fake_llm, mock_db):
    mock_db[db.SESSIONS].insert_many([make_turn("s_a_t1", "alex", pipeline="not json"), make_turn("s_b_t1", "sam")])
    learning.backlog()
    status = {t["turn_id"]: t["episode_status"] for t in mock_db[db.SESSIONS].find()}
    assert status["s_a_t1"].startswith("error:") and status["s_b_t1"] == "extracted"



def test_worker_records_why_a_turn_was_skipped(fake_llm, mock_db):
    mock_db[db.SESSIONS].insert_one(make_turn("s_a_t1", "alex", used_memory=False))
    learning.backlog()
    assert mock_db[db.SESSIONS].find_one({"turn_id": "s_a_t1"})["episode_status"] == "skipped: memory was switched off"
    assert episodes_count() == 0 and fake_llm.calls == []


def test_a_turn_can_be_claimed_only_once(fake_llm, mock_db):
    mock_db[db.SESSIONS].insert_one(make_turn("s_a_t1", "alex"))
    turn = mock_db[db.SESSIONS].find_one({"turn_id": "s_a_t1"})
    assert learning.claim(turn) is True    # the first worker takes it
    assert learning.claim(turn) is False   # the second finds it taken
    assert learning.process(turn) is None  # and leaves it alone
    assert episodes_count() == 0 and fake_llm.calls == []


def test_two_workers_given_the_same_turn_make_one_episode(fake_llm, mock_db):
    mock_db[db.SESSIONS].insert_one(make_turn("s_a_t1", "alex"))
    event = mock_db[db.SESSIONS].find_one({"turn_id": "s_a_t1"})  # both workers receive the same insert event
    assert [learning.process(dict(event)), learning.process(dict(event))] == ["extracted", None]
    assert episodes_count() == 1 and len(fake_llm.calls) == 1


def test_worker_started_without_backlog_only_takes_newer_turns(fake_llm, mock_db):
    started = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    mock_db[db.SESSIONS].insert_many([make_turn("s_old_t1", "alex", ts=started - timedelta(hours=2)),
                                      make_turn("s_new_t1", "sam", ts=started + timedelta(minutes=5))])
    assert [t["turn_id"] for t in learning.pending(started)] == ["s_new_t1"]
    assert learning.backlog(started) == 1
    status = {t["turn_id"]: t.get("episode_status") for t in mock_db[db.SESSIONS].find()}
    assert status == {"s_old_t1": None, "s_new_t1": "extracted"}
    assert learning.backlog() == 1  # what --backlog adds: the older turn
    assert episodes_count() == 2


class FakeStream:
    """A change stream that delivers the given insert events and then ends."""

    def __init__(self, turns):
        self.changes = [{"fullDocument": t} for t in turns]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.changes)


def statuses(mock_db) -> dict:
    return {t["turn_id"]: t.get("episode_status") for t in mock_db[db.SESSIONS].find()}


def test_run_takes_turns_from_the_change_stream_and_leaves_older_ones(fake_llm, mock_db, monkeypatch):
    now = datetime.now(timezone.utc)
    mock_db[db.SESSIONS].insert_many([make_turn("s_old_t1", "alex", ts=now - timedelta(hours=2)),
                                      make_turn("s_new_t1", "sam", ts=now - timedelta(seconds=1))])
    arrived = mock_db[db.SESSIONS].find_one({"turn_id": "s_new_t1"})
    monkeypatch.setattr(mongomock.collection.Collection, "watch", lambda self, pipeline: FakeStream([arrived]), raising=False)
    learning.run()  # returns when the fake stream ends
    assert statuses(mock_db) == {"s_old_t1": None, "s_new_t1": "extracted"}


def test_run_with_backlog_also_takes_the_older_turns(fake_llm, mock_db, monkeypatch):
    mock_db[db.SESSIONS].insert_one(make_turn("s_old_t1", "alex", ts=datetime.now(timezone.utc) - timedelta(hours=2)))
    monkeypatch.setattr(mongomock.collection.Collection, "watch", lambda self, pipeline: FakeStream([]), raising=False)
    learning.run(include_backlog=True)
    assert statuses(mock_db) == {"s_old_t1": "extracted"}


def test_run_polls_when_change_streams_are_unavailable(fake_llm, mock_db, monkeypatch):
    class Stop(Exception):
        pass

    def no_watch(self, pipeline):
        raise OperationFailure("The $changeStream stage is only supported on replica sets")

    naps = []

    def nap(seconds):
        naps.append(seconds)
        if len(naps) == 1:  # a question is answered while the worker waits
            mock_db[db.SESSIONS].insert_one(make_turn("s_new_t1", "sam", ts=datetime.now(timezone.utc)))
        else:
            raise Stop

    mock_db[db.SESSIONS].insert_one(make_turn("s_old_t1", "alex", ts=datetime.now(timezone.utc) - timedelta(hours=2)))
    monkeypatch.setattr(mongomock.collection.Collection, "watch", no_watch, raising=False)
    monkeypatch.setattr(learning.time, "sleep", nap)
    with pytest.raises(Stop):
        learning.run()
    assert statuses(mock_db) == {"s_old_t1": None, "s_new_t1": "extracted"}
