import pytest

from app.guard import GuardError, guard_pipeline
from app.users import get_user

Q3 = [{"$group": {"_id": "$region", "rev": {"$sum": "$revenue"}}}]


def test_store_manager_gets_row_filter_and_unset_first():
    safe, gov = guard_pipeline(get_user("sam"), "sales", Q3)
    assert safe[0] == {"$match": {"region": "East"}}
    assert safe[1] == {"$unset": ["supplier_cost"]}
    assert gov["row_filter"] == {"region": "East"}
    assert gov["removed_fields"] == ["supplier_cost"]


def test_finance_lead_has_no_filters():
    safe, gov = guard_pipeline(get_user("fatima"), "sales", Q3)
    assert safe[0] == Q3[0]
    assert gov["removed_fields"] == []


@pytest.mark.parametrize("pipeline", [
    [{"$group": {"_id": "$category", "c": {"$sum": "$supplier_cost"}}}],
    [{"$match": {"supplier_cost": {"$gt": 0}}}],
    [{"$project": {"supplier_cost": 1}}],
    [{"$addFields": {"x": {"$divide": ["$supplier_cost.value", 2]}}}],
])
def test_hidden_field_reference_rejected(pipeline):
    with pytest.raises(GuardError) as e:
        guard_pipeline(get_user("alex"), "sales", pipeline)
    assert e.value.hidden_fields_referenced == ["supplier_cost"]


def test_finance_lead_may_use_supplier_cost():
    guard_pipeline(get_user("fatima"), "sales",
                   [{"$group": {"_id": "$category", "c": {"$sum": "$supplier_cost"}}}])


@pytest.mark.parametrize("pipeline", [
    [{"$lookup": {"from": "memories", "as": "m", "pipeline": []}}],
    [{"$out": "x"}],
    [{"$merge": {"into": "x"}}],
    [{"$unionWith": "memories"}],
    [{"$match": {"$where": "true"}}],
    [{"$group": {"_id": None, "x": {"$accumulator": {}}}}],
    [{"$addFields": {"x": {"$function": {"body": "", "args": [], "lang": "js"}}}}],
    [{"$facet": {"a": [{"$out": "x"}]}}],
])
def test_banned_stages_and_operators_rejected(pipeline):
    with pytest.raises(GuardError):
        guard_pipeline(get_user("fatima"), "sales", pipeline)


def test_only_sales_collection():
    with pytest.raises(GuardError):
        guard_pipeline(get_user("fatima"), "memories", [{"$match": {}}])


def test_row_filter_cannot_be_escaped_by_later_match():
    # The user's $match comes first, so a later $match can only narrow further
    safe, _ = guard_pipeline(get_user("sam"), "sales", [{"$match": {"region": "West"}}])
    assert safe[0] == {"$match": {"region": "East"}}
