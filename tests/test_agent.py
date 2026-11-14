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
