from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app import audit, memory
from app.models import ProposedMemory
from app.users import get_user

FATIMA, ALEX, SAM = get_user("fatima"), get_user("alex"), get_user("sam")
NM2 = ProposedMemory(type="metric", title="Net margin",
                     content="(SUM(revenue) - SUM(returns) - SUM(supplier_cost)) / (SUM(revenue) - SUM(returns))")


def active(title="Net margin", content="wrong", visibility=None):
    m = memory.propose(FATIMA, ProposedMemory(type="metric", title=title, content=content), None, visibility)
    return memory.approve(FATIMA, m["memory_id"])


def ids(mems):
    return {m["memory_id"] for m in mems}


def test_pending_memory_is_not_retrieved():
    m = memory.propose(ALEX, NM2, "s_1_t1")
    assert m["status"] == "pending"
    assert m["visibility"] == ["analyst"]
    assert memory.retrieve(ALEX, "net margin by region") == []


def test_correction_supersedes_previous_version():
    v1 = active()
    v2 = memory.approve(FATIMA, memory.propose(FATIMA, NM2, "s_2_t1")["memory_id"])
    assert v2["version"] == 2
    got = memory.retrieve(ALEX, "What was net margin by region in Q3?")
    assert ids(got) == {v2["memory_id"]}
    assert v1["memory_id"] not in ids(got)


def test_use_memory_false_returns_nothing():
    active()
    assert memory.retrieve(ALEX, "net margin", use_memory=False) == []


def test_visibility_is_enforced():
    finance_only = active(title="Footwear cost note", content="footwear supplier cost is high",
                          visibility=["finance_lead"])
    assert finance_only["memory_id"] in ids(memory.retrieve(FATIMA, "footwear cost note"))
    assert memory.retrieve(ALEX, "footwear cost note") == []
    assert memory.retrieve(SAM, "footwear cost note") == []


def test_non_reviewer_cannot_widen_visibility():
    with pytest.raises(HTTPException):
        memory.propose(SAM, NM2, None, visibility=["finance_lead", "analyst", "store_manager"])


def test_expired_memory_is_never_retrieved_and_is_audited():
    m = active()
    memory.expire(FATIMA, m["memory_id"], "wrong definition")
    assert memory.retrieve(ALEX, "net margin") == []
    assert audit.recent(action="memory_expire")[0]["target"]["id"] == m["memory_id"]


def test_past_expires_at_is_swept():
    m = memory.propose(FATIMA, NM2, None)
    memory.approve(FATIMA, m["memory_id"], expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert memory.retrieve(ALEX, "net margin") == []
    events = audit.recent(action="memory_expire")
    assert events and events[0]["actor"] == "system"


def test_forget_keeps_content_for_audit_but_never_retrieves():
    m = active()
    out = memory.forget(FATIMA, m["memory_id"], "Promotion ended")
    assert out["status"] == "forgotten"
    assert out["content"] == "wrong"
    assert out["forgotten"]["by"] == "fatima"
    assert memory.retrieve(ALEX, "net margin") == []
    assert audit.recent(action="memory_forget")[0]["details"]["reason"] == "Promotion ended"


def test_forget_requires_reason():
    m = active()
    with pytest.raises(HTTPException):
        memory.forget(FATIMA, m["memory_id"], "")
