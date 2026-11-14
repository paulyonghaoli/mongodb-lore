"""Analyst agent workstream: /api/ask and the replay comparison."""
from fastapi import APIRouter, Depends, HTTPException

from .. import agent, llm
from ..models import AskRequest, UserContext
from ..users import all_users, current_user

router = APIRouter(prefix="/api", tags=["ask"])


@router.get("/users")
def users() -> list[dict]:
    return [u.model_dump() for u in all_users().values()]


@router.get("/me")
def me(user: UserContext = Depends(current_user)) -> dict:
    return user.model_dump()


@router.post("/ask")
def ask(body: AskRequest, user: UserContext = Depends(current_user)) -> dict:
    try:
        return agent.ask(user, body.question, body.session_id, body.use_memory)
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/replay")
def replay(body: AskRequest, user: UserContext = Depends(current_user)) -> dict:
    """Convenience for the interface: same question with and without memory."""
    try:
        without = agent.ask(user, body.question, body.session_id, use_memory=False, use_history=False)
        # No history on the second call, so the only difference is memory
        with_mem = agent.ask(user, body.question, without["session_id"], use_memory=True,
                             use_history=False)
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"without_memory": without, "with_memory": with_mem}
