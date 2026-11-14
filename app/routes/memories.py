"""Memory governance workstream: list, approve, reject, expire, forget."""
from fastapi import APIRouter, Depends

from .. import memory
from ..models import ApproveBody, ReasonBody, UserContext
from ..users import current_user, require_reviewer

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.get("")
def list_memories(status: str | None = None, user: UserContext = Depends(current_user)) -> list[dict]:
    return memory.list_for(user, status)


@router.post("/{memory_id}/approve")
def approve(memory_id: str, body: ApproveBody | None = None,
            user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    body = body or ApproveBody()
    return memory.approve(user, memory_id, body.visibility, body.expires_at)


@router.post("/{memory_id}/reject")
def reject(memory_id: str, body: ReasonBody, user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return memory.reject(user, memory_id, body.reason)


@router.post("/{memory_id}/expire")
def expire(memory_id: str, body: ReasonBody | None = None,
           user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return memory.expire(user, memory_id, (body or ReasonBody()).reason)


@router.post("/{memory_id}/forget")
def forget(memory_id: str, body: ReasonBody, user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return memory.forget(user, memory_id, body.reason)
