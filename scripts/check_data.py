"""Check the sales data in the cluster against the contracts (Business data schema, Patterns).

Run it from a machine that can reach the Sandbox (the cloud dev session cannot).
Usage: python -m scripts.check_data
Exits non-zero if a required check fails.
"""
import sys
from datetime import datetime, timezone

from app import db

FIELDS = {"date": datetime, "store_id": str, "store_name": str, "region": str, "category": str,
          "product": str, "units": int, "revenue": float, "returns": float,
          "supplier_cost": float, "discount": float}
REGIONS = {"East", "West", "North", "South"}
CATEGORIES = {"Camping", "Apparel", "Footwear", "Home"}

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{f'  ({detail})' if detail else ''}")
    if not ok:
        failures.append(label)


def d(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def sums(group: str, start: str, end: str, match: dict | None = None) -> dict:
    pipeline = [
        {"$match": {"date": {"$gte": d(start), "$lt": d(end)}, **(match or {})}},
        {"$group": {"_id": f"${group}", "rev": {"$sum": "$revenue"}, "ret": {"$sum": "$returns"},
                    "cost": {"$sum": "$supplier_cost"}}},
    ]
    return {r["_id"]: r for r in db.business_db()[db.SALES].aggregate(pipeline)}


def wrong_margin(r: dict) -> float:
    return (r["rev"] - r["cost"]) / r["rev"]


def right_margin(r: dict) -> float:
    net = r["rev"] - r["ret"]
    return (net - r["cost"]) / net


def main() -> None:
    col = db.business_db()[db.SALES]
    print(f"database: {col.database.name}  collection: {col.name}\n")

    # --- shape ---
    n = col.estimated_document_count()
    check(100_000 <= n <= 300_000, "document count 100k-300k", f"{n:,}")
    if n == 0:
        sys.exit(1)
    sample = list(col.aggregate([{"$sample": {"size": 200}}]))
    for f, t in FIELDS.items():
        bad = [s for s in sample if not isinstance(s.get(f), t) and not (t is float and isinstance(s.get(f), int))]
        check(not bad, f"field {f} is {t.__name__}", f"{len(bad)}/200 sampled wrong" if bad else "")
    extra = {k for s in sample for k in s} - set(FIELDS) - {"_id"}
    check(not extra, "no unexpected fields", ", ".join(sorted(extra)))

    lo = col.find_one(sort=[("date", 1)])["date"]
    hi = col.find_one(sort=[("date", -1)])["date"]
    check(lo.date().isoformat() == "2026-01-01" and hi.date().isoformat() == "2026-10-31",
          "dates 2026-01-01 to 2026-10-31", f"{lo.date()} to {hi.date()}")
    check(set(col.distinct("region")) == REGIONS, "regions", ", ".join(sorted(col.distinct("region"))))
    check(set(col.distinct("category")) == CATEGORIES, "categories", ", ".join(sorted(col.distinct("category"))))
    stores = list(col.aggregate([{"$group": {"_id": "$region", "s": {"$addToSet": "$store_id"}}}]))
    per_region = {s["_id"]: len(s["s"]) for s in stores}
    check(all(v == 5 for v in per_region.values()) and len(per_region) == 4, "5 stores per region", str(per_region))
    hb = col.find_one({"store_name": "Harbourfront"}, {"store_id": 1, "region": 1})
    check(bool(hb) and hb["region"] == "East", "Harbourfront exists in East", str(hb and hb.get("store_id")))

    # --- planted patterns ---
    print()
    q3 = sums("region", "2026-07-01", "2026-10-01")
    rr = {k: v["ret"] / v["rev"] for k, v in q3.items()}
    print("Q3 by region      return rate   margin (wrong def)   margin (correct def)")
    for k in sorted(q3):
        print(f"  {k:6}           {rr[k]:7.1%}       {wrong_margin(q3[k]):7.1%}              {right_margin(q3[k]):7.1%}")
    if "East" in q3:
        others = [k for k in q3 if k != "East"]
        check(all(rr["East"] > rr[o] for o in others), "East has the highest Q3 return rate")
        wrong_rank = sorted(q3, key=lambda k: wrong_margin(q3[k]))
        right_rank = sorted(q3, key=lambda k: right_margin(q3[k]))
        check(right_rank[0] == "East", "East has the weakest Q3 margin under the correct definition",
              f"weakest: {right_rank[0]}")
        avg = lambda f: sum(f(q3[o]) for o in others) / len(others)  # noqa: E731
        gap_wrong = avg(wrong_margin) - wrong_margin(q3["East"])
        gap_right = avg(right_margin) - right_margin(q3["East"])
        check(gap_right - gap_wrong >= 0.10,
              "East's margin gap widens by 10+ points under the correct definition (demo correction visible)",
              f"gap {gap_wrong:.1%} -> {gap_right:.1%}; weakest under wrong def: {wrong_rank[0]}")

    print()
    before = sums("store_name", "2026-01-01", "2026-07-01", {"region": "East"})
    after = sums("store_name", "2026-07-01", "2026-11-01", {"region": "East"})
    drops = {k: right_margin(after[k]) - right_margin(before[k]) for k in after if k in before}
    for k, v in sorted(drops.items(), key=lambda x: x[1]):
        print(f"  {k:14} margin change since July: {v:+.1%}")
    if drops:
        check(min(drops, key=drops.get) == "Harbourfront", "Harbourfront loses the most margin from July")

    print()
    cats = sums("category", "2026-01-01", "2026-11-01")
    share = {k: v["cost"] / (v["rev"] - v["ret"]) for k, v in cats.items()}
    for k, v in sorted(share.items(), key=lambda x: -x[1]):
        print(f"  {k:9} supplier cost share of net revenue: {v:.1%}")
    if share:
        check(max(share, key=share.get) == "Footwear", "Footwear has the highest supplier cost share")

    print(f"\n{'All checks passed' if not failures else f'{len(failures)} check(s) failed: ' + '; '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
