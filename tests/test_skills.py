from datetime import datetime, timezone

from app import db, skills
from app.users import get_user


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
