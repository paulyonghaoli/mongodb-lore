"""Generate synthetic Northwind Outfitters sales (contracts: Business data schema).

Starter generator for the data workstream (Jimmy owns the final version).
One document per store, product and day, 2026-01-01 to 2026-10-31.
Full size: 20 stores x 40 products x 304 days = 243,200 documents.

Planted patterns (contracts: Patterns the data must contain):
- East has a high return rate in Q3 (net margin drops only under the correct definition).
- Harbourfront (E03) loses margin from July (deeper discounts, higher supplier cost).
- Footwear has the highest supplier cost share.

Usage:
  python -m scripts.generate_sales --drop
  python -m scripts.generate_sales --drop --products-per-category 3   # small, for local dev
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

from app import db

STORES = {
    "East": ["Riverside", "Old Town", "Harbourfront", "Maple Grove", "Lakeview"],
    "West": ["Summit", "Pacific Point", "Cedar Hills", "Canyon", "Bayshore"],
    "North": ["Pinecrest", "Aurora", "Frostline", "Timberline", "Northgate"],
    "South": ["Sunvale", "Magnolia", "Palm Court", "Riverbend", "Southpark"],
}

PRODUCTS = {
    "Camping": [("2-person tent", 129.99), ("4-person tent", 249.99), ("Sleeping bag", 89.99),
                ("Camp stove", 64.99), ("Headlamp", 29.99), ("Backpack 40L", 149.99),
                ("Water filter", 44.99), ("Camp chair", 39.99), ("Cooler", 119.99), ("Trekking poles", 79.99)],
    "Apparel": [("Rain jacket", 179.99), ("Fleece", 89.99), ("Base layer", 59.99), ("Hiking pants", 79.99),
                ("Down vest", 129.99), ("Sun hoodie", 54.99), ("Wool socks", 19.99), ("Beanie", 24.99),
                ("Gloves", 34.99), ("Insulated parka", 299.99)],
    "Footwear": [("Hiking boots", 219.99), ("Trail runners", 149.99), ("Sandals", 69.99),
                 ("Winter boots", 189.99), ("Camp slippers", 49.99), ("Approach shoes", 159.99),
                 ("Water shoes", 59.99), ("Rain boots", 89.99), ("Gaiters", 39.99), ("Insoles", 29.99)],
    "Home": [("Throw blanket", 69.99), ("Lantern", 49.99), ("Enamel mug set", 34.99), ("Cast-iron pan", 59.99),
             ("Hammock", 89.99), ("Picnic set", 79.99), ("Candle", 24.99), ("Doormat", 39.99),
             ("Wall map", 44.99), ("Plant pot", 29.99)],
}

# Supplier cost as a share of list price. Footwear is highest.
COST_SHARE = {"Camping": 0.50, "Apparel": 0.46, "Footwear": 0.64, "Home": 0.48}
BASE_RETURN_RATE = 0.05
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 1, tzinfo=timezone.utc)


def season_factor(cat: str, month: int) -> float:
    if cat in ("Camping", "Footwear"):
        return 1.4 if month in (5, 6, 7, 8) else 0.9
    if cat == "Apparel":
        return 1.3 if month in (1, 2, 10) else 1.0
    return 1.0


def generate(products_per_category: int, seed: int):
    rng = random.Random(seed)
    store_ids = {}
    for region, names in STORES.items():
        for i, name in enumerate(names, 1):
            store_ids[name] = (f"{region[0]}{i:02d}", region)

    day = START
    while day < END:
        q3 = day.month in (7, 8, 9)
        for name, (store_id, region) in store_ids.items():
            harbourfront_drop = name == "Harbourfront" and day.month >= 7
            for cat, items in PRODUCTS.items():
                for product, price in items[:products_per_category]:
                    units = max(0, int(rng.gauss(3 * season_factor(cat, day.month), 1.8)))
                    discount = rng.choice([0.0, 0.0, 0.0, 0.05, 0.10])
                    cost_share = COST_SHARE[cat]
                    if harbourfront_drop:
                        discount = rng.choice([0.15, 0.20, 0.25])
                        cost_share += 0.08
                    revenue = round(units * price * (1 - discount), 2)
                    return_rate = BASE_RETURN_RATE
                    if region == "East" and q3:
                        return_rate = 0.24
                    returned_units = sum(1 for _ in range(units) if rng.random() < return_rate)
                    returns = round(returned_units * price * (1 - discount), 2)
                    supplier_cost = round(units * price * cost_share * rng.uniform(0.97, 1.03), 2)
                    yield {
                        "date": day,
                        "store_id": store_id,
                        "store_name": name,
                        "region": region,
                        "category": cat,
                        "product": product,
                        "units": units,
                        "revenue": revenue,
                        "returns": returns,
                        "supplier_cost": supplier_cost,
                        "discount": discount,
                    }
        day += timedelta(days=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true", help="drop the sales collection first")
    ap.add_argument("--products-per-category", type=int, default=10)
    ap.add_argument("--seed", type=int, default=14)
    args = ap.parse_args()

    col = db.app_db()[db.SALES]
    if args.drop:
        col.drop()
    batch, total = [], 0
    for doc in generate(args.products_per_category, args.seed):
        batch.append(doc)
        if len(batch) == 5000:
            col.insert_many(batch)
            total += len(batch)
            batch = []
            print(f"\rinserted {total}", end="", flush=True)
    if batch:
        col.insert_many(batch)
        total += len(batch)
    print(f"\rinserted {total} sales documents")


if __name__ == "__main__":
    main()
