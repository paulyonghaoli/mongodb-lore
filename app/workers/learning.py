"""Learning worker: turns answered session turns into episodes.

Run:  python -m app.workers.learning               # turns saved from now on
      python -m app.workers.learning --backlog     # also older turns that were never processed
      python -m app.workers.learning --auto-draft  # also draft a skill when a cluster is ready

With --auto-draft the worker drafts and tests a skill as soon as a new episode lands in a ready
cluster that nothing was drafted from yet. The draft waits for a reviewer: only publishing offers
it to the agent.

Atlas pushes each new turn through a change stream on `sessions`; where change streams are not
available the worker polls. More than one worker can run against the same database: a turn is
claimed before it is processed, so it becomes at most one episode.

Each processed turn gets an `episode_status`: "extracted", "skipped: <why>", "rejected: <why>"
or "error: <what>".
"""
import argparse
import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from pymongo.errors import PyMongoError

from .. import db, skills

log = logging.getLogger("lore.learning")

OUTCOMES = ["answered", "user_confirmed"]
POLL_SECONDS = 5


def claim(turn: dict) -> bool:
    """Take the turn for this worker. False when another worker, or an earlier run, already has it."""
    taken = db.app_db()[db.SESSIONS].find_one_and_update(
        {"_id": turn["_id"], "episode_status": {"$exists": False}},
        {"$set": {"episode_status": "processing"}})
    return taken is not None


def draft(cluster_id: str) -> dict | None:
    """Draft a skill from the cluster if it is ready and has none. A failed draft never stops the worker."""
    try:
        skill = skills.draft_if_ready(cluster_id)
        if skill:
            log.info("cluster %s is ready: drafted %s v%s, tests %s. It waits for a reviewer.",
                     cluster_id, skill["name"], skill["version"], skill["test_results"])
        return skill
    except HTTPException as e:  # a draft the checks refused, or the cluster changed meanwhile
        log.warning("no draft from cluster %s: %s", cluster_id, e.detail)
    except Exception:
        log.exception("drafting from cluster %s failed", cluster_id)
    return None


def process(turn: dict, auto_draft: bool = False) -> str | None:
    """Extract one turn and record what happened on it. None when the turn was not ours to take."""
    if not claim(turn):
        return None
    ep = None
    try:
        ep, reason = skills.extract(turn)
        status = "extracted" if ep else reason
        log.info("turn %s (%s): %s%s", turn["turn_id"], turn.get("user_id"), status,
                 f" -> cluster {ep['cluster_id']}" if ep else "")
    except Exception as e:  # keep the worker alive
        log.exception("extraction failed for %s", turn.get("turn_id"))
        status = f"error: {e}"
    # The status is written before any drafting, so a slow or failed draft never leaves a turn "processing"
    db.app_db()[db.SESSIONS].update_one({"_id": turn["_id"]}, {"$set": {"episode_status": status}})
    if ep and auto_draft:
        draft(ep["cluster_id"])
    return status


def pending(since: datetime | None = None) -> list[dict]:
    """Answered turns nobody has processed, oldest first. `since` limits them to turns saved from then on."""
    query: dict = {"episode_status": {"$exists": False}, "outcome": {"$in": OUTCOMES}}
    if since is not None:
        query["ts"] = {"$gte": since}
    return list(db.app_db()[db.SESSIONS].find(query).sort("ts", 1))


def backlog(since: datetime | None = None, auto_draft: bool = False) -> int:
    """Process the pending turns. Returns how many this worker handled."""
    return sum(1 for turn in pending(since) if process(turn, auto_draft))


def run(include_backlog: bool = False, auto_draft: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    # By default only turns saved from now on: the older ones are mostly test questions,
    # and each costs a model call.
    since = None if include_backlog else datetime.now(timezone.utc)
    older = len(pending())
    if auto_draft:
        log.info("automatic drafting is on: a ready cluster with no skill gets a draft for the reviewer")
    if include_backlog:
        log.info("processing %d older turn(s) first", older)
        backlog(auto_draft=auto_draft)
    elif older:
        log.info("leaving %d older turn(s) untouched; run with --backlog to process them", older)

    match = {"$match": {"operationType": "insert", "fullDocument.outcome": {"$in": OUTCOMES}}}
    try:
        with db.app_db()[db.SESSIONS].watch([match]) as stream:
            log.info("watching sessions via change stream")
            backlog(since, auto_draft)  # anything saved while the stream was opening
            for change in stream:
                process(change["fullDocument"], auto_draft)
    except PyMongoError as e:
        log.warning("change streams unavailable (%s); polling every %ss", e, POLL_SECONDS)
        while True:
            backlog(since, auto_draft)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Turn answered session turns into episodes.")
    parser.add_argument("--backlog", action="store_true",
                        help="also process older answered turns that were never processed")
    parser.add_argument("--auto-draft", action="store_true",
                        help="draft and test a skill when a new episode lands in a ready cluster that has none")
    args = parser.parse_args()
    run(include_backlog=args.backlog, auto_draft=args.auto_draft)
