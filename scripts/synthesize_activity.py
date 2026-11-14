"""Synthesize agent activity: sessions, memories, episodes and audit events.

Gives the reviewer view, the skills workstream and memory leak tests something to work on
before the agent has real traffic. Every pipeline runs through the real guard as the asking
user and against the real `sales` data, so outcomes, row counts and numbers are real; only the
questions and the answer wording (a template, not the LLM) are scripted.

Every document written carries `synthetic: True`; seeds from seed_memories are left alone.

Usage:
  python -m scripts.synthesize_activity                       # replace earlier synthetic docs
  python -m scripts.synthesize_activity --approve-correction  # also make Net margin v2 active
  python -m scripts.synthesize_activity --clear               # only remove synthetic docs
"""
import argparse
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import json_util

from app import db, embeddings, skills
from app.agent import to_jsonable
from app.guard import GuardError, guard_pipeline
from app.memory import slug
from app.models import ROLES
from app.users import get_user
from scripts.seed_memories import SEEDS

BASE = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)
LORE = (db.MEMORIES, db.SESSIONS, db.EPISODES, db.SKILLS, db.AUDIT_LOG)
RATIO_KEYS = {"net_margin", "return_rate", "sales_growth"}


def d(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ---------- pipelines (the same shapes the agent writes) ----------

RATIOS = {
    # wrong on purpose: the seeded v1 definition that ignores returns
    "net_margin_v1": {"$divide": [{"$subtract": ["$revenue", "$cost"]}, "$revenue"]},
    "net_margin_v2": {"$divide": [{"$subtract": [{"$subtract": ["$revenue", "$returns"]}, "$cost"]},
                                  {"$subtract": ["$revenue", "$returns"]}]},
    "return_rate": {"$divide": ["$returns", "$revenue"]},
}
OUT_NAME = {"net_margin_v1": "net_margin", "net_margin_v2": "net_margin", "return_rate": "return_rate"}


def ratio_by(groups: list[str], start: str, end: str, ratio: str, match: dict | None = None) -> list[dict]:
    sums = {"revenue": {"$sum": "$revenue"}, "returns": {"$sum": "$returns"}}
    if ratio.startswith("net_margin"):
        sums["cost"] = {"$sum": "$supplier_cost"}
    gid: Any = f"${groups[0]}" if len(groups) == 1 else {g: f"${g}" for g in groups}
    proj = {"_id": 0, **({groups[0]: "$_id"} if len(groups) == 1 else {g: f"$_id.{g}" for g in groups})}
    proj[OUT_NAME[ratio]] = {"$round": [RATIOS[ratio], 4]}
    return [
        {"$match": {"date": {"$gte": d(start), "$lt": d(end)}, **(match or {})}},
        {"$group": {"_id": gid, **sums}},
        {"$project": proj},
        {"$sort": {OUT_NAME[ratio]: -1 if ratio == "return_rate" else 1}},
    ]


def revenue_by(group: str, start: str, end: str, match: dict | None = None, month: bool = False) -> list[dict]:
    gid = {"$month": "$date"} if month else f"${group}"
    return [
        {"$match": {"date": {"$gte": d(start), "$lt": d(end)}, **(match or {})}},
        {"$group": {"_id": gid, "net_revenue": {"$sum": {"$subtract": ["$revenue", "$returns"]}}}},
        {"$project": {"_id": 0, group: "$_id", "net_revenue": {"$round": ["$net_revenue", 2]}}},
        {"$sort": {group: 1}},
    ]


GROWTH = [
    {"$match": {"date": {"$gte": d("2026-08-01"), "$lt": d("2026-10-01")}}},
    {"$group": {"_id": {"region": "$region", "month": {"$month": "$date"}},
                "net": {"$sum": {"$subtract": ["$revenue", "$returns"]}}}},
    {"$group": {"_id": "$_id.region",
                "aug": {"$sum": {"$cond": [{"$eq": ["$_id.month", 8]}, "$net", 0]}},
                "sep": {"$sum": {"$cond": [{"$eq": ["$_id.month", 9]}, "$net", 0]}}}},
    {"$project": {"_id": 0, "region": "$_id",
                  "sales_growth": {"$round": [{"$subtract": [{"$divide": ["$sep", "$aug"]}, 1]}, 4]}}},
    {"$sort": {"region": 1}},
]

NET_MARGIN_V2 = ("Net margin = (SUM(revenue) - SUM(returns) - SUM(supplier_cost)) / "
                 "(SUM(revenue) - SUM(returns)). Returns are refunded money and must come out of "
                 "revenue before margin.")


def rr_episode(start: str, end: str) -> dict:
    return {"intent": "Rank categories by return rate for <period>",
            "parameters": {"start": start, "end": end}, "group_fields": ["category"],
            "method": ["Filter sales to the period", "Sum revenue and returns by category",
                       "Return rate = returns / revenue", "Sort by return rate, highest first"]}


# ---------- the scripted conversations ----------
# (session_id, user, day offset, turns). A turn may carry `propose` (a memory the user states)
# and `episode` (what the learning worker would extract from it).

CONVERSATIONS = [
    ("s_syn01", "fatima", 0, [
        {"q": "What was net margin by region in Q3?", "metrics": ["net_margin@1"],
         "p": ratio_by(["region"], "2026-07-01", "2026-10-01", "net_margin_v1"),
         "episode": {"intent": "Rank regions by net margin for <period>",
                     "parameters": {"start": "2026-07-01", "end": "2026-10-01"}, "group_fields": ["region"],
                     "method": ["Filter sales to the period", "Sum revenue and supplier cost by region",
                                "Net margin per the company definition", "Sort ascending"]}},
        {"q": "That's not right. Net margin has to take returns out first: (revenue - returns - "
              "supplier cost) / (revenue - returns). Redo it.", "metrics": [],
         "p": ratio_by(["region"], "2026-07-01", "2026-10-01", "net_margin_v2"),
         "propose": ("metric", "Net margin", NET_MARGIN_V2)},
        {"q": "Which East store has the weakest net margin since July?", "metrics": [],
         "p": ratio_by(["store_name"], "2026-07-01", "2026-11-01", "net_margin_v2", {"region": "East"})},
    ]),
    ("s_syn02", "alex", 1, [
        {"q": "What was net margin by region in Q3?", "metrics": ["net_margin@1"],
         "p": ratio_by(["region"], "2026-07-01", "2026-10-01", "net_margin_v1")},  # guard rejects
        {"q": "Then show me return rate by region in Q3.", "metrics": ["return_rate@1"],
         "p": ratio_by(["region"], "2026-07-01", "2026-10-01", "return_rate")},
        {"q": "Break that down by category.", "metrics": ["return_rate@1"],
         "p": ratio_by(["region", "category"], "2026-07-01", "2026-10-01", "return_rate")},
    ]),
    ("s_syn03", "sam", 2, [
        {"q": "Return rate by store in October", "metrics": ["return_rate@1"],
         "p": ratio_by(["store_name"], "2026-10-01", "2026-11-01", "return_rate")},
        {"q": "How has Harbourfront's net revenue moved month by month?", "metrics": ["net_revenue@1"],
         "p": revenue_by("month", "2026-01-01", "2026-11-01", {"store_name": "Harbourfront"}, month=True)},
        {"q": "FYI: East stores extended the return window to 60 days on July 1.", "metrics": [],
         "p": ratio_by(["store_name"], "2026-07-01", "2026-11-01", "return_rate"),
         "propose": ("fact", "East return window",
                     "East stores extended the return window from 30 to 60 days on 2026-07-01.")},
    ]),
    ("s_syn04", "alex", 3, [
        {"q": "Return rate by category in September", "metrics": ["return_rate@1"],
         "p": ratio_by(["category"], "2026-09-01", "2026-10-01", "return_rate"),
         "episode": rr_episode("2026-09-01", "2026-10-01")},
        {"q": "Return rate should be returns divided by units sold, not revenue.", "metrics": [],
         "p": ratio_by(["category"], "2026-09-01", "2026-10-01", "return_rate"),
         "propose": ("metric", "Return rate", "Return rate = SUM(returns) / SUM(units)")},
    ]),
    ("s_syn05", "sam", 4, [
        {"q": "Return rate by category for August", "metrics": ["return_rate@1"],
         "p": ratio_by(["category"], "2026-08-01", "2026-09-01", "return_rate"),
         "episode": rr_episode("2026-08-01", "2026-09-01")},
        {"q": "Harbourfront's manager is off on medical leave, so treat its numbers as unreliable.",
         "metrics": [], "p": revenue_by("store_name", "2026-07-01", "2026-11-01"),
         "propose": ("fact", "Harbourfront staffing",
                     "Harbourfront's store manager is on medical leave; treat its numbers as unreliable.")},
    ]),
    ("s_syn06", "fatima", 5, [
        {"q": "Return rate by category in October", "metrics": ["return_rate@1"],
         "p": ratio_by(["category"], "2026-10-01", "2026-11-01", "return_rate"),
         "episode": rr_episode("2026-10-01", "2026-11-01")},
        {"q": "Net revenue by category year to date", "metrics": ["net_revenue@1"],
         "p": revenue_by("category", "2026-01-01", "2026-11-01")},
    ]),
    ("s_syn07", "alex", 6, [
        {"q": "Return rate by category in July", "metrics": ["return_rate@1"],
         "p": ratio_by(["category"], "2026-07-01", "2026-08-01", "return_rate"),
         "episode": rr_episode("2026-07-01", "2026-08-01")},
        {"q": "Sales growth by region, August to September", "metrics": ["sales_growth@1", "net_revenue@1"],
         "p": GROWTH},
    ]),
]

# Reviewer decisions on the proposals above (title -> action), applied by fatima
DECISIONS = {
    "East return window": ("approve", {"visibility": ["store_manager", "finance_lead"]}),
    "Return rate": ("reject", "Mixes CAD with units; return rate stays returns / revenue."),
    "Harbourfront staffing": ("forget", "Personal health information about an employee."),
}

# Memories with no source turn: written by the finance lead directly
STANDALONE = [
    {"type": "decision", "title": "Q4 targets basis",
     "content": "Q4 targets are set on net revenue, not gross revenue.", "status": "active", "day": 1},
    {"type": "fact", "title": "Summer Footwear promo",
     "content": "Footwear ran at 20% off list from 2026-07-01 to 2026-09-30.", "status": "expired",
     "expires_at": d("2026-09-30"), "day": 0},
]


# ---------- writing ----------

def fmt(k: str, v: Any) -> str:
    if k in RATIO_KEYS:
        return f"{v * 100:.1f}%"
    if isinstance(v, float):
        return f"${v:,.2f}"
    return str(v)


def answer_for(rows: list[dict]) -> str:
    if not rows:
        return "No rows matched that question."
    parts = []
    for r in rows[:8]:
        label = " / ".join(str(v) for k, v in r.items() if not isinstance(v, (int, float)) or k == "month")
        nums = ", ".join(f"{k.replace('_', ' ')} {fmt(k, v)}" for k, v in r.items()
                         if isinstance(v, (int, float)) and k != "month")
        parts.append(f"{label}: {nums}")
    more = f" (and {len(rows) - 8} more)" if len(rows) > 8 else ""
    return "; ".join(parts) + more + "."


class Writer:
    def __init__(self) -> None:
        self.app = db.app_db()

    def audit(self, ts: datetime, actor: str, action: str, kind: str, target: str, details: dict) -> None:
        role = get_user(actor).role
        self.app[db.AUDIT_LOG].insert_one({"ts": ts, "actor": actor, "role": role, "action": action,
                                           "target": {"kind": kind, "id": target}, "details": details,
                                           "synthetic": True})

    def memory(self, ts: datetime, user_id: str, mtype: str, title: str, content: str,
               turn_id: str | None) -> dict:
        latest = self.app[db.MEMORIES].find_one({"title": title}, sort=[("version", -1)])
        version = latest["version"] + 1 if latest else 1
        user = get_user(user_id)
        doc = {"memory_id": f"mem_{slug(title)}_v{version}", "type": mtype, "title": title,
               "content": content, "version": version, "status": "pending",
               "visibility": list(ROLES) if user.can_review else [user.role], "expires_at": None,
               "source": {"turn_id": turn_id, "proposed_by": user_id}, "approved_by": None,
               "created_at": ts, "forgotten": None, "embed_model": None, "embedding": None,
               "synthetic": True}
        self.app[db.MEMORIES].insert_one(doc)
        self.audit(ts, user_id, "memory_propose", "memory", doc["memory_id"], {"title": title, "version": version})
        return doc

    def approve(self, ts: datetime, doc: dict, visibility: list[str] | None = None) -> None:
        upd = {"status": "active", "approved_by": "fatima", "approved_at": ts,
               "embed_model": embeddings.model_name(),
               "embedding": embeddings.embed_one(f"{doc['title']}: {doc['content']}")}
        if visibility:
            upd["visibility"] = visibility
        self.app[db.MEMORIES].update_one({"memory_id": doc["memory_id"]}, {"$set": upd})
        old = [m["memory_id"] for m in self.app[db.MEMORIES].find(
            {"title": doc["title"], "status": "active", "memory_id": {"$ne": doc["memory_id"]}})]
        if old:
            self.app[db.MEMORIES].update_many({"memory_id": {"$in": old}},
                                              {"$set": {"status": "superseded", "superseded_by": doc["memory_id"]}})
        self.audit(ts, "fatima", "memory_approve", "memory", doc["memory_id"],
                   {"superseded": old, "visibility": upd.get("visibility", doc["visibility"])})

    def reject(self, ts: datetime, doc: dict, reason: str) -> None:
        self.app[db.MEMORIES].update_one({"memory_id": doc["memory_id"]}, {"$set": {
            "status": "rejected", "rejected": {"by": "fatima", "reason": reason, "at": ts}}})
        self.audit(ts, "fatima", "memory_reject", "memory", doc["memory_id"], {"reason": reason})

    def forget(self, ts: datetime, doc: dict, reason: str) -> None:
        self.app[db.MEMORIES].update_one({"memory_id": doc["memory_id"]}, {"$set": {
            "status": "forgotten", "embedding": None, "forgotten": {"by": "fatima", "reason": reason, "at": ts}}})
        self.audit(ts, "fatima", "memory_forget", "memory", doc["memory_id"],
                   {"reason": reason, "previous_status": "pending"})

    def turn(self, ts: datetime, session_id: str, n: int, user_id: str, spec: dict) -> dict:
        user = get_user(user_id)
        turn_id = f"{session_id}_t{n}"
        pipeline = spec["p"]
        execution: dict[str, Any] = {"status": "ok", "attempts": 1, "row_count": 0, "columns": []}
        gov: dict[str, Any] = {"row_filter": user.rows, "removed_fields": user.hidden_fields}
        try:
            safe, gov = guard_pipeline(user, "sales", pipeline)
            rows = to_jsonable(list(db.business_db()[db.SALES].aggregate(safe)))
            outcome, answer = "answered", answer_for(rows)
            execution.update(row_count=len(rows), columns=list(rows[0]) if rows else [])
        except GuardError as e:
            rows, outcome = [], "rejected"
            execution["status"] = "rejected"
            gov = {**gov, "rejected": e.reason, "hidden_fields_referenced": e.hidden_fields_referenced}
            answer = f"I can't run that query: {e.reason}."

        memory_ids = [m["memory_id"] for m in self.app[db.MEMORIES].find(
            {"status": "active", "visibility": user.role}, {"memory_id": 1})]
        doc = {"session_id": session_id, "turn_id": turn_id, "user_id": user_id, "role": user.role,
               "question": spec["q"], "used_memory": True, "memory_ids": memory_ids, "skill": None,
               "collection": "sales", "pipeline": json_util.dumps(pipeline),
               "metrics_used": spec["metrics"], "execution": execution, "answer": answer,
               "outcome": outcome, "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
               "ts": ts, "synthetic": True, "answer_source": "template",
               "episode_status": "extracted" if spec.get("episode") and outcome == "answered" else "skipped"}
        self.app[db.SESSIONS].insert_one(doc)
        self.audit(ts, user_id, "query", "collection", "sales", {
            "turn_id": turn_id, "question": spec["q"], "status": execution["status"],
            "filters": gov.get("row_filter"), "removed_fields": gov.get("removed_fields"),
            "rejected": gov.get("rejected"), "hidden_fields_referenced": gov.get("hidden_fields_referenced", []),
            "pipeline": doc["pipeline"]})
        if doc["episode_status"] == "extracted":
            self.episode(ts, doc, spec["episode"])
        return doc

    def episode(self, ts: datetime, turn: dict, e: dict) -> None:
        ep = {"episode_id": f"ep_{turn['turn_id']}", "turn_id": turn["turn_id"], "user_id": turn["user_id"],
              "intent": e["intent"], "parameters": e["parameters"], "metrics": turn["metrics_used"],
              "collection": "sales", "group_fields": e["group_fields"], "method": e["method"],
              "pipeline": turn["pipeline"], "embed_model": embeddings.model_name(),
              "embedding": embeddings.embed_one(e["intent"] + "\n" + "\n".join(e["method"])),
              "created_at": ts, "synthetic": True}
        ep["structure"] = skills._structure_key(ep)
        ep["cluster_id"] = skills._assign_cluster(ep)
        self.app[db.EPISODES].insert_one(ep)


def clear() -> None:
    """Remove synthetic docs only. The database is shared: never touch anyone else's."""
    mems = db.app_db()[db.MEMORIES]
    syn_ids = [m["memory_id"] for m in mems.find({"synthetic": True}, {"memory_id": 1})]
    # Re-activate only what a synthetic approval superseded
    mems.update_many({"status": "superseded", "superseded_by": {"$in": syn_ids}},
                     {"$set": {"status": "active"}, "$unset": {"superseded_by": ""}})
    for c in LORE:
        n = db.app_db()[c].delete_many({"synthetic": True}).deleted_count
        print(f"  removed {n} synthetic docs from {c}")


def ensure_seeds() -> None:
    for mtype, title, content in SEEDS:
        mid = f"mem_{slug(title)}_v1"
        if db.app_db()[db.MEMORIES].find_one({"memory_id": mid}):
            continue
        db.app_db()[db.MEMORIES].insert_one({
            "memory_id": mid, "type": mtype, "title": title, "content": content, "version": 1,
            "status": "active", "visibility": list(ROLES), "expires_at": None,
            "source": {"turn_id": None, "proposed_by": "seed"}, "approved_by": "seed",
            "created_at": BASE - timedelta(days=7), "forgotten": None,
            "embed_model": embeddings.model_name(), "embedding": embeddings.embed_one(f"{title}: {content}")})
        print("  seeded", mid)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="only remove synthetic docs")
    ap.add_argument("--approve-correction", action="store_true",
                    help="approve Net margin v2 (default: leave it pending for the live demo)")
    args = ap.parse_args()

    clear()
    if args.clear:
        return
    ensure_seeds()
    w = Writer()

    for s in STANDALONE:
        ts = BASE + timedelta(days=s["day"], hours=-2)
        doc = w.memory(ts, "fatima", s["type"], s["title"], s["content"], None)
        w.approve(ts + timedelta(minutes=5), doc)
        if s["status"] == "expired":
            w.app[db.MEMORIES].update_one({"memory_id": doc["memory_id"]},
                                          {"$set": {"status": "expired", "expires_at": s["expires_at"]}})
            w.audit(ts + timedelta(minutes=6), "fatima", "memory_expire", "memory", doc["memory_id"],
                    {"reason": "promo ended"})

    for session_id, user_id, day, turns in CONVERSATIONS:
        for n, spec in enumerate(turns, 1):
            ts = BASE + timedelta(days=day, minutes=4 * n)
            turn = w.turn(ts, session_id, n, user_id, spec)
            print(f"  {turn['turn_id']:10} {user_id:6} {turn['outcome']:8} rows={turn['execution']['row_count']:<3} "
                  f"{spec['q'][:60]}")
            if "propose" in spec:
                mtype, title, content = spec["propose"]
                mem = w.memory(ts + timedelta(seconds=30), user_id, mtype, title, content, turn["turn_id"])
                act = DECISIONS.get(title)
                later = ts + timedelta(hours=3)
                if title == "Net margin" and args.approve_correction:
                    w.approve(later, mem)
                elif act and act[0] == "approve":
                    w.approve(later, mem, act[1]["visibility"])
                elif act and act[0] == "reject":
                    w.reject(later, mem, act[1])
                elif act and act[0] == "forget":
                    w.forget(later, mem, act[1])

    app = db.app_db()
    print("\nmemories by status:", {r["_id"]: r["n"] for r in app[db.MEMORIES].aggregate(
        [{"$group": {"_id": "$status", "n": {"$sum": 1}}}])})
    for c in (db.SESSIONS, db.EPISODES, db.AUDIT_LOG):
        print(f"{c}: {app[c].count_documents({'synthetic': True})} synthetic")
    for c in skills.clusters():
        print(f"cluster {c['cluster_id']}: {c['episodes']} episodes, users {c['users']}, ready={c['ready']}"
              f"  ({c['intent']})")


if __name__ == "__main__":
    main()
