"""Skills workstream: list, clusters, generate (manual trigger), publish, retire."""
from fastapi import APIRouter, Depends

from .. import skills
from ..models import GenerateSkillBody, ReasonBody, UserContext
from ..users import current_user, require_reviewer

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills(user: UserContext = Depends(current_user)) -> dict:
    offered = {s["name"] for s in skills.offered_to(user)}
    return {"skills": [{**s, "offered_to_you": s["name"] in offered and s["status"] == "published"}
                       for s in skills.list_all()]}


@router.get("/clusters")
def list_clusters(user: UserContext = Depends(current_user)) -> list[dict]:
    return skills.clusters()


@router.post("/generate")
def generate(body: GenerateSkillBody | None = None, user: UserContext = Depends(current_user)) -> dict:
    return skills.generate((body or GenerateSkillBody()).cluster_id)


@router.post("/{name}/publish")
def publish(name: str, user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return skills.publish(user, name)


@router.post("/{name}/retire")
def retire(name: str, body: ReasonBody, user: UserContext = Depends(current_user)) -> dict:
    require_reviewer(user)
    return skills.retire(user, name, body.reason)
