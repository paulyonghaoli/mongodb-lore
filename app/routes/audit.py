"""Data and access workstream: audit log."""
from fastapi import APIRouter, Depends

from .. import audit
from ..agent import to_jsonable
from ..models import UserContext
from ..users import current_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def recent(limit: int = 100, action: str | None = None,
           user: UserContext = Depends(current_user)) -> list[dict]:
    events = audit.recent(limit, action)
    if not user.can_review:
        events = [e for e in events if e["actor"] == user.user_id]
    return to_jsonable(events)
