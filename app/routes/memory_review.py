"""Reviewer endpoints for monthly query and memory hygiene."""
from fastapi import APIRouter, Depends

from .. import memory_review
from ..models import ReasonBody, UserContext
from ..users import current_user, require_reviewer

router = APIRouter(prefix="/api/memory-review", tags=["memory review"])


@router.get("/runs")
def list_runs(user: UserContext = Depends(current_user)) -> list[dict]:
    require_reviewer(user)
    return memory_review.list_runs()


@router.post("/run")
def run_monthly(month: str | None = None,
                user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return memory_review.run_monthly(month)


@router.get("/items")
def list_items(batch_id: str | None = None, item_type: str | None = None,
               status: str | None = "pending", limit: int = 500,
               user: UserContext = Depends(current_user)) -> list[dict]:
    require_reviewer(user)
    return memory_review.list_items(batch_id, item_type, status, min(limit, 1000))


@router.post("/items/{item_id}/retain")
def retain_item(item_id: str, user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return memory_review.retain_item(user, item_id)


@router.post("/items/{item_id}/delete")
def delete_item(item_id: str, body: ReasonBody,
                user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return memory_review.delete_item(user, item_id, body.reason)
