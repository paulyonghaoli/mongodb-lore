"""Seed the starting memories, including the deliberately WRONG net margin (contracts: The demo correction).

Usage:
  python -m scripts.seed_memories            # insert seeds that are missing
  python -m scripts.seed_memories --reset    # clear memories, sessions, episodes, skills, audit_log first
"""
import argparse
from datetime import datetime, timezone

from app import db, embeddings
from app.models import ROLES

SEEDS = [
    ("metric", "Net margin",
     "Net margin = (SUM(revenue) - SUM(supplier_cost)) / SUM(revenue)"),  # wrong on purpose: ignores returns
    ("metric", "Net revenue", "Net revenue = SUM(revenue) - SUM(returns). Returns are money refunded."),
    ("metric", "Return rate", "Return rate = SUM(returns) / SUM(revenue)"),
    ("metric", "Sales growth",
     "Sales growth = net revenue in a period / net revenue in the previous period - 1. "
     "Periods are calendar months."),
    ("decision", "Net margin demo access decision",
     "Keep supplier_cost restricted to finance_lead. Shared memory visibility does not grant access "
     "to restricted fields. Demonstrate the net margin memory change using the finance_lead persona; "
     "queries from analyst and store_manager that require supplier_cost must remain blocked by the guard."),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    d = db.app_db()
    if args.reset:
        for c in (db.MEMORIES, db.SESSIONS, db.EPISODES, db.SKILLS, db.AUDIT_LOG,
                  db.MEMORY_REVIEW_RUNS, db.MEMORY_REVIEW_ITEMS):
            d[c].delete_many({})
        print("cleared lore collections (sales untouched)")

    for mtype, title, content in SEEDS:
        memory_id = f"mem_{title.lower().replace(' ', '_')}_v1"
        if d[db.MEMORIES].find_one({"memory_id": memory_id}):
            continue
        d[db.MEMORIES].insert_one({
            "memory_id": memory_id, "type": mtype, "title": title, "content": content,
            "version": 1, "status": "active", "visibility": list(ROLES), "expires_at": None,
            "source": {"turn_id": None, "proposed_by": "seed"}, "approved_by": "seed",
            "created_at": datetime.now(timezone.utc), "forgotten": None,
            "embed_model": embeddings.model_name(),
            "embedding": embeddings.embed_one(f"{title}: {content}"),
        })
        print("seeded", memory_id)

    # The active deliberately-wrong definition must be visible to the finance lead
    # as well as the analyst; otherwise the central memory-on/off comparison cannot run.
    active_margin = d[db.MEMORIES].find_one(
        {"title": "Net margin", "status": "active"}, sort=[("version", -1)])
    if active_margin and set(active_margin.get("visibility", [])) != set(ROLES):
        d[db.MEMORIES].update_one(
            {"memory_id": active_margin["memory_id"]},
            {"$set": {"visibility": list(ROLES)}})
        print("widened active net margin memory visibility to all demo roles:",
              active_margin["memory_id"])


if __name__ == "__main__":
    main()
