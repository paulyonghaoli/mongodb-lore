"""Hand-written reference pipelines for the demo questions (contracts: Demo questions).

These use the CORRECT definitions and run with full access. Output goes to
docs/expected_answers.json and is the accuracy test set for scripts/run_eval.py.
Usage: python -m scripts.expected_answers
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app import db
from app.agent import to_jsonable


def d(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def net_margin_by(field: str, start: str, end: str, extra_match: dict | None = None) -> list[dict]:
    match = {"date": {"$gte": d(start), "$lt": d(end)}, **(extra_match or {})}
    return [
        {"$match": match},
        {"$group": {"_id": f"${field}", "revenue": {"$sum": "$revenue"},
                    "returns": {"$sum": "$returns"}, "cost": {"$sum": "$supplier_cost"}}},
        {"$project": {"_id": 0, field: "$_id", "net_margin": {"$round": [{"$divide": [
            {"$subtract": [{"$subtract": ["$revenue", "$returns"]}, "$cost"]},
            {"$subtract": ["$revenue", "$returns"]}]}, 4]}}},
        {"$sort": {"net_margin": 1}},
    ]


QUESTIONS = {
    "q1_q3_net_margin_by_region": net_margin_by("region", "2026-07-01", "2026-10-01"),
    "q4_east_store_margin_since_july": net_margin_by("store_name", "2026-07-01", "2026-11-01",
                                                     {"region": "East"}),
    "q6_net_margin_by_category": net_margin_by("category", "2026-01-01", "2026-11-01"),
    "q7_return_rate_by_category_september": [
        {"$match": {"date": {"$gte": d("2026-09-01"), "$lt": d("2026-10-01")}}},
        {"$group": {"_id": "$category", "revenue": {"$sum": "$revenue"}, "returns": {"$sum": "$returns"}}},
        {"$project": {"_id": 0, "category": "$_id",
                      "return_rate": {"$round": [{"$divide": ["$returns", "$revenue"]}, 4]}}},
        {"$sort": {"category": 1}},
    ],
    "q8_sales_growth_by_region_aug_to_sep": [
        {"$match": {"date": {"$gte": d("2026-08-01"), "$lt": d("2026-10-01")}}},
        {"$group": {"_id": {"region": "$region", "month": {"$month": "$date"}},
                    "net": {"$sum": {"$subtract": ["$revenue", "$returns"]}}}},
        {"$group": {"_id": "$_id.region",
                    "aug": {"$sum": {"$cond": [{"$eq": ["$_id.month", 8]}, "$net", 0]}},
                    "sep": {"$sum": {"$cond": [{"$eq": ["$_id.month", 9]}, "$net", 0]}}}},
        {"$project": {"_id": 0, "region": "$_id",
                      "sales_growth": {"$round": [{"$subtract": [{"$divide": ["$sep", "$aug"]}, 1]}, 4]}}},
        {"$sort": {"region": 1}},
    ],
}


def main() -> None:
    out = {}
    for key, pipeline in QUESTIONS.items():
        out[key] = to_jsonable(list(db.business_db()[db.SALES].aggregate(pipeline)))
        print(key, json.dumps(out[key], indent=1))
    path = Path(__file__).resolve().parent.parent / "docs" / "expected_answers.json"
    path.write_text(json.dumps(out, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
