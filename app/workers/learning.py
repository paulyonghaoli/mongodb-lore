"""Learning worker: turns answered session turns into episodes.

Run:  python -m app.workers.learning             # turns saved from now on
      python -m app.workers.learning --backlog   # also older turns that were never processed

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


def process(turn: dict) -> str | None:
    """Extract one turn and record what happened on it. None when the turn was not ours to take."""
    if not claim(turn):
        return None
    try:
        ep, reason = skills.extract(turn)
        status = "extracted" if ep else reason
        log.info("turn %s (%s): %s%s", turn["turn_id"], turn.get("user_id"), status,
                 f" -> cluster {ep['cluster_id']}" if ep else "")
    except Exception as e:  # keep the worker alive
        log.exception("extraction failed for %s", turn.get("turn_id"))
        status = f"error: {e}"
    db.app_db()[db.SESSIONS].update_one({"_id": turn["_id"]}, {"$set": {"episode_status": status}})
    return status


def pending(since: datetime | None = None) -> list[dict]:
    """Answered turns nobody has processed, oldest first. `since` limits them to turns saved from then on."""
    query: dict = {"episode_status": {"$exists": False}, "outcome": {"$in": OUTCOMES}}
    if since is not None:
        query["ts"] = {"$gte": since}
    return list(db.app_db()[db.SESSIONS].find(query).sort("ts", 1))


def backlog(since: datetime | None = None) -> int:
    """Process the pending turns. Returns how many this worker handled."""
    return sum(1 for turn in pending(since) if process(turn))


def run(include_backlog: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    # By default only turns saved from now on: the older ones are mostly test questions,
    # and each costs a model call.
    since = None if include_backlog else datetime.now(timezone.utc)
    older = len(pending())
    if include_backlog:
        log.info("processing %d older turn(s) first", older)
        backlog()
    elif older:
        log.info("leaving %d older turn(s) untouched; run with --backlog to process them", older)

    match = {"$match": {"operationType": "insert", "fullDocument.outcome": {"$in": OUTCOMES}}}
    try:
        with db.app_db()[db.SESSIONS].watch([match]) as stream:
            log.info("watching sessions via change stream")
            backlog(since)  # anything saved while the stream was opening
            for change in stream:
                process(change["fullDocument"])
    except PyMongoError as e:
        log.warning("change streams unavailable (%s); polling every %ss", e, POLL_SECONDS)
        while True:
            backlog(since)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Turn answered session turns into episodes.")
    parser.add_argument("--backlog", action="store_true",
                        help="also process older answered turns that were never processed")
    run(include_backlog=parser.parse_args().backlog)
