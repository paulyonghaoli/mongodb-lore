"""Learning worker: turns finished session turns into episodes.

Run:  python -m app.workers.learning
Uses a change stream on `sessions` when available (Atlas), otherwise polls.
"""
import logging
import time

from pymongo.errors import PyMongoError

from .. import db, skills

log = logging.getLogger("lore.learning")


def process(turn: dict) -> None:
    col = db.app_db()[db.SESSIONS]
    try:
        ep = skills.extract_episode(turn)
        status = "extracted" if ep else "rejected"
        log.info("turn %s -> %s %s", turn["turn_id"], status, ep and ep["cluster_id"])
    except Exception as e:  # keep the worker alive
        log.exception("extraction failed for %s", turn.get("turn_id"))
        status = f"error: {e}"
    col.update_one({"_id": turn["_id"]}, {"$set": {"episode_status": status}})


def backlog() -> None:
    for turn in db.app_db()[db.SESSIONS].find(
            {"episode_status": {"$exists": False}, "outcome": {"$in": ["answered", "user_confirmed"]}}):
        process(turn)


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    backlog()
    match = {"$match": {"operationType": "insert",
                        "fullDocument.outcome": {"$in": ["answered", "user_confirmed"]}}}
    try:
        with db.app_db()[db.SESSIONS].watch([match]) as stream:
            log.info("watching sessions via change stream")
            for change in stream:
                process(change["fullDocument"])
    except PyMongoError as e:
        log.warning("change streams unavailable (%s); polling every 5s", e)
        while True:
            backlog()
            time.sleep(5)


if __name__ == "__main__":
    run()
