"""Identity and policy: builds the user context every component reads."""
import json
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException

from .models import UserContext

USERS_FILE = Path(__file__).with_name("users.json")


@lru_cache
def all_users() -> dict[str, UserContext]:
    data = json.loads(USERS_FILE.read_text())
    return {u["user_id"]: UserContext(**u) for u in data}


def get_user(user_id: str) -> UserContext:
    user = all_users().get(user_id)
    if user is None:
        raise KeyError(user_id)
    return user


def current_user(x_user: str = Header(..., alias="X-User")) -> UserContext:
    """FastAPI dependency: the interface sends the user ID in X-User."""
    try:
        return get_user(x_user)
    except KeyError:
        raise HTTPException(status_code=401, detail=f"Unknown user {x_user!r}")


def require_reviewer(user: UserContext) -> None:
    if not user.can_review:
        raise HTTPException(status_code=403, detail="Reviewer permission required")
