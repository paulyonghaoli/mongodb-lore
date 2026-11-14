"""Query guard (contracts: Agent output, User context).

Every business query passes through guard_pipeline() before it runs:
1. Only the `sales` collection.
2. Only allowlisted stages; banned operators rejected anywhere in the pipeline.
3. Any reference to a field hidden from the user is rejected.
4. The user's row filter is added as the first $match.
5. Hidden fields are $unset before the agent's stages run.
6. A final $limit caps rows returned.
"""
from typing import Any

from .models import UserContext

ALLOWED_COLLECTIONS = {"sales"}
ALLOWED_STAGES = {
    "$match", "$group", "$project", "$addFields", "$set",
    "$sort", "$limit", "$skip", "$unwind", "$count",
}
BANNED_OPERATORS = {
    "$lookup", "$graphLookup", "$unionWith", "$out", "$merge",
    "$function", "$where", "$accumulator",
}


def _walk(node: Any):
    """Yield every dict key and every string value in a nested structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield ("key", key)
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, str):
        yield ("str", node)


class GuardError(Exception):
    """The pipeline was rejected. `reason` is safe to show the user."""

    def __init__(self, reason: str, hidden_fields_referenced: list[str] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.hidden_fields_referenced = hidden_fields_referenced or []


def _field_root(path: str) -> str:
    return path.split(".", 1)[0]


def find_hidden_references(pipeline: list[dict], hidden: list[str]) -> list[str]:
    hidden_set = set(hidden)
    found: set[str] = set()

    def walk(node: Any, parent_operator: str | None = None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                root = _field_root(key)
                # In $project, 0/null means exclude this input field. Its name
                # appears as a key, but no hidden data is read or returned.
                excluded = parent_operator == "$project" and value in (0, None, False)
                if root in hidden_set and not excluded:
                    found.add(root)
                next_operator = key if key.startswith("$") else parent_operator
                walk(value, next_operator)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_operator)
        elif isinstance(node, str) and node.startswith("$") and not node.startswith("$$"):
            # "$supplier_cost", "$supplier_cost.x"; ignore "$$vars".
            root = _field_root(node[1:])
            if root in hidden_set:
                found.add(root)

    walk(pipeline)
    return sorted(found)


def validate(collection: str, pipeline: list[dict]) -> None:
    if collection not in ALLOWED_COLLECTIONS:
        raise GuardError(f"Collection {collection!r} is not allowed")
    if not isinstance(pipeline, list) or not pipeline:
        raise GuardError("Pipeline must be a non-empty list of stages")
    for i, stage in enumerate(pipeline):
        if not isinstance(stage, dict) or len(stage) != 1:
            raise GuardError(f"Stage {i} must be an object with exactly one operator")
        op = next(iter(stage))
        if op not in ALLOWED_STAGES:
            raise GuardError(f"Stage {op!r} is not allowed")
    for kind, value in _walk(pipeline):
        if kind == "key" and value in BANNED_OPERATORS:
            raise GuardError(f"Operator {value!r} is not allowed")


def guard_pipeline(
    user: UserContext, collection: str, pipeline: list[dict], max_rows: int = 500
) -> tuple[list[dict], dict]:
    """Return (safe_pipeline, governance) or raise GuardError.

    governance is returned to the interface and written to the audit log:
    { row_filter, removed_fields, max_rows }
    """
    validate(collection, pipeline)
    refs = find_hidden_references(pipeline, user.hidden_fields)
    if refs:
        raise GuardError(
            f"The query uses fields you are not allowed to see: {', '.join(refs)}",
            hidden_fields_referenced=refs,
        )

    safe: list[dict] = []
    if user.rows:
        safe.append({"$match": dict(user.rows)})
    if user.hidden_fields:
        safe.append({"$unset": list(user.hidden_fields)})
    safe.extend(pipeline)
    safe.append({"$limit": max_rows})

    governance = {
        "row_filter": dict(user.rows),
        "removed_fields": list(user.hidden_fields),
        "max_rows": max_rows,
    }
    return safe, governance
