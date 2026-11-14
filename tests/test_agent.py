"""Agent loop with a mocked LLM: guard applied, turn saved, history scoped to the user."""
import json
from datetime import datetime, timezone

import pytest

from app import agent, db, llm
from app.users import get_user


@pytest.fixture
def sales(mock_db):
    rows = []
    for region in ("East", "West"):
        for day in (1, 2):
            rows.append({"date": datetime(2026, 7, day, tzinfo=timezone.utc), "store_id": region[0] + "00",
                         "store_name": f"{region} store", "region": region, "category": "Camping",
                         "product": "tent", "units": 2, "revenue": 100.0, "returns": 10.0,
                         "supplier_cost": 50.0, "discount": 0.0})
    mock_db[db.SALES].insert_many(rows)
    return mock_db


@pytest.fixture
def fake_llm(monkeypatch):
    calls: list[dict] = []
    pipeline = [{"$group": {"_id": "$region", "revenue": {"$sum": "$revenue"}}},
                {"$sort": {"_id": 1}}]

    def complete(system, messages, usage, schema=None, **kw):
        calls.append({"system": system, "messages": messages, "schema": schema})
        if schema is None:
            return "Revenue by region."
        return {"interpretation": "revenue by region", "collection": "sales",
                "pipeline_json": json.dumps(pipeline), "metrics_used": [], "skill": None,
                "proposed_memory": None, "assumptions": []}

    monkeypatch.setattr(llm, "complete", complete)

    # mongomock lacks $unset; swap in the equivalent $project exclusion
    real_guard = agent.guard_pipeline

    def guard(*a, **kw):
        safe, gov = real_guard(*a, **kw)
        return [{"$project": {f: 0 for f in ([s["$unset"]] if isinstance(s["$unset"], str) else s["$unset"])}}
                if "$unset" in s else s for s in safe], gov

    monkeypatch.setattr(agent, "guard_pipeline", guard)
    return calls


def test_store_manager_only_gets_east(sales, fake_llm):
    res = agent.ask(get_user("sam"), "Revenue by region", use_memory=False)
    assert res["outcome"] == "answered"
    assert [r["_id"] for r in res["rows"]] == ["East"]
    assert "supplier_cost" not in fake_llm[0]["system"]


def test_finance_lead_gets_all_regions(sales, fake_llm):
    res = agent.ask(get_user("fatima"), "Revenue by region", use_memory=False)
    assert [r["_id"] for r in res["rows"]] == ["East", "West"]


def test_turn_saved_without_rows(sales, fake_llm):
    res = agent.ask(get_user("alex"), "Revenue by region", use_memory=False)
    turn = sales[db.SESSIONS].find_one({"turn_id": res["turn_id"]})
    assert turn["outcome"] == "answered" and turn["execution"]["row_count"] == 2
    assert "rows" not in turn


def test_follow_up_sees_own_history(sales, fake_llm):
    first = agent.ask(get_user("alex"), "Revenue by region", use_memory=False)
    agent.ask(get_user("alex"), "Now just East", session_id=first["session_id"], use_memory=False)
    plan_msgs = [c for c in fake_llm if c["schema"] is not None]
    assert "Revenue by region" in plan_msgs[-1]["messages"][0]["content"]


def test_history_never_crosses_users(sales, fake_llm):
    first = agent.ask(get_user("fatima"), "Revenue by region", use_memory=False)
    agent.ask(get_user("sam"), "Now just East", session_id=first["session_id"], use_memory=False)
    plan_msgs = [c for c in fake_llm if c["schema"] is not None]
    assert "Earlier in this conversation" not in plan_msgs[-1]["messages"][0]["content"]


def test_replay_style_call_skips_history(sales, fake_llm):
    first = agent.ask(get_user("alex"), "Revenue by region", use_memory=False)
    agent.ask(get_user("alex"), "Revenue by region", session_id=first["session_id"], use_history=False)
    plan_msgs = [c for c in fake_llm if c["schema"] is not None]
    assert "Earlier in this conversation" not in plan_msgs[-1]["messages"][0]["content"]


# ---------- review fixes: turn IDs, skills without memory, repair with a skill ----------

SKILL_TEMPLATE = [{"$match": {"region": "{{region}}"}},
                  {"$group": {"_id": "$region", "revenue": {"$sum": "$revenue"}}}]


def _publish_skill(mock_db, name="region_revenue"):
    from bson import json_util
    mock_db[db.SKILLS].insert_one({
        "name": name, "version": 1, "status": "published", "description": "Revenue for one region",
        "parameters": {"region": "Region name"}, "pipeline_template": json_util.dumps(SKILL_TEMPLATE),
        "required_fields": ["region", "revenue"], "metric_versions": {}})


def _plan(pipeline=None, skill=None):
    return {"interpretation": "x", "collection": "sales",
            "pipeline_json": json.dumps(pipeline or []), "metrics_used": [],
            "skill": skill and {"name": skill[0], "parameters_json": json.dumps(skill[1])},
            "proposed_memory": None, "assumptions": []}


@pytest.fixture
def scripted_llm(monkeypatch, fake_llm):
    """Planning calls return the queued plans in order; explaining returns text."""
    plans: list[dict] = []
    systems: list[str] = []

    def complete(system, messages, usage, schema=None, **kw):
        if schema is None:
            return "ok"
        systems.append(system)
        return plans.pop(0)

    monkeypatch.setattr(llm, "complete", complete)
    return plans, systems


def test_turn_ids_never_repeat_after_a_delete(sales, fake_llm):
    first = agent.ask(get_user("alex"), "Revenue by region", use_memory=False)
    sid = first["session_id"]
    agent.ask(get_user("alex"), "Again", session_id=sid, use_memory=False)
    sales[db.SESSIONS].delete_one({"turn_id": f"{sid}_t1"})  # e.g. the monthly review deleted it
    third = agent.ask(get_user("alex"), "Once more", session_id=sid, use_memory=False)
    assert third["turn_id"] == f"{sid}_t3"
    ids = [t["turn_id"] for t in sales[db.SESSIONS].find({"session_id": sid})]
    assert len(ids) == len(set(ids))


def test_skills_are_not_offered_without_memory(sales, scripted_llm):
    plans, systems = scripted_llm
    _publish_skill(sales)
    plans += [_plan([{"$count": "n"}]), _plan([{"$count": "n"}])]
    agent.ask(get_user("fatima"), "Revenue", use_memory=False)
    agent.ask(get_user("fatima"), "Revenue", use_memory=True)
    assert "region_revenue" not in systems[0]
    assert "region_revenue" in systems[1]


def test_repair_renders_a_skill_chosen_by_the_replan(sales, scripted_llm, monkeypatch):
    from pymongo.errors import OperationFailure
    plans, _ = scripted_llm
    _publish_skill(sales)
    plans += [_plan([{"$count": "n"}]), _plan(skill=("region_revenue", {"region": "West"}))]

    real = db.business_db()
    calls = {"n": 0}

    class FailsOnce:
        def __getitem__(self, name):
            col = real[name]

            class Col:
                def aggregate(self, pipeline):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        raise OperationFailure("bad pipeline")
                    return col.aggregate(pipeline)
            return Col()

    monkeypatch.setattr(agent.db, "business_db", lambda: FailsOnce())
    res = agent.ask(get_user("fatima"), "Revenue for West", use_memory=True)
    assert res["outcome"] == "answered"
    assert res["skill_used"]["name"] == "region_revenue"
    assert [r["_id"] for r in res["rows"]] == ["West"]


def test_unavailable_skill_is_a_clean_rejection(sales, scripted_llm):
    plans, _ = scripted_llm
    plans.append(_plan(skill=("no_such_skill", {})))
    res = agent.ask(get_user("alex"), "Revenue", use_memory=True)
    assert res["outcome"] == "rejected"
    assert "not available" in res["answer"]
