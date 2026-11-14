import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGODB_DB", "lore")

# 基础配置数据
REGIONS_STORES = {
    "East": ["Harbourfront", "Scarborough", "Markham", "Downtown", "Vaughan"],
    "West": ["Kitsilano", "Richmond", "Surrey", "Burnaby", "Victoria"],
    "North": ["Barrie", "Orillia", "Sudbury", "Thunder Bay", "North Bay"],
    "South": ["Mississauga", "Oakville", "Hamilton", "London", "Windsor"]
}

CATEGORIES_PRODUCTS = {
    "Camping": ["2-person tent", "Sleeping bag", "Camping stove", "Lantern", "Backpack", "Trekking poles", "Hammock",
                "Water filter", "Cooler", "Multi-tool"],
    "Apparel": ["Rain jacket", "Fleece pullover", "Hiking pants", "Merino socks", "Base layer top", "Base layer bottom",
                "Beanie", "Gloves", "Windbreaker", "Cargo shorts"],
    "Footwear": ["Trail running shoes", "Hiking boots", "Water sandals", "Camp booties", "Approach shoes",
                 "Winter boots", "Socks 3-pack", "Gaiters", "Insoles", "Laces"],
    "Home": ["Patio chair", "Hammock stand", "Solar string lights", "Picnic blanket", "Portable grill", "Fire pit",
             "Thermos", "Enamel mug set", "Lantern speaker", "Campsite rug"]
}


def generate_sales_data():
    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]
    sales_collection = db["sales"]

    # 清空旧数据（可选）
    sales_collection.drop()

    start_date = datetime(2026, 1, 1)
    end_date = datetime(2026, 10, 31)

    current_date = start_date
    batch = []
    total_inserted = 0

    print("开始生成并插入销售数据...")

    while current_date <= end_date:
        is_q3 = (7 <= current_date.month <= 9)

        for region, stores in REGIONS_STORES.items():
            for store_idx, store_name in enumerate(stores):
                store_id = f"{region[0]}{store_idx:02d}"

                # 每个类别随机选 2-3 个产品生成每日交易
                for category, products in CATEGORIES_PRODUCTS.items():
                    # 限制产品数量以控制总文档数在 10万 - 30万 之间
                    sampled_products = random.sample(products, 3)

                    for product in sampled_products:
                        units = random.randint(1, 10)

                        # 单价基准
                        unit_price = random.uniform(20.0, 300.0)
                        revenue = round(units * unit_price, 2)

                        # 规则：Footwear 具有最高的供应商成本占比 (70% - 85%)
                        if category == "Footwear":
                            cost_share = random.uniform(0.70, 0.85)
                        else:
                            cost_share = random.uniform(0.40, 0.65)
                        supplier_cost = round(revenue * cost_share, 2)

                        # 规则：East 区在 Q3 具有高退货率
                        if region == "East" and is_q3:
                            return_rate = random.uniform(0.25, 0.45)
                        else:
                            return_rate = random.uniform(0.02, 0.10)
                        returns = round(revenue * return_rate, 2)

                        # 规则：Harbourfront 门店从 7 月起利润开始受损（成本或退货异常推高）
                        if store_name == "Harbourfront" and current_date.month >= 7:
                            supplier_cost = round(revenue * 0.85, 2)  # 利润受损

                        discount = random.choice([0.0, 0.0, 0.0, 0.10, 0.15, 0.20])

                        doc = {
                            "date": current_date,
                            "store_id": store_id,
                            "store_name": store_name,
                            "region": region,
                            "category": category,
                            "product": product,
                            "units": units,
                            "revenue": revenue,
                            "returns": returns,
                            "supplier_cost": supplier_cost,
                            "discount": discount
                        }
                        batch.append(doc)

                        # 批量插入以提高性能
                        if len(batch) >= 5000:
                            sales_collection.insert_many(batch)
                            total_inserted += len(batch)
                            batch = []

        current_date += timedelta(days=1)

    if batch:
        sales_collection.insert_many(batch)
        total_inserted += len(batch)

    print(f"数据注入完成！共向 `sales` 集合插入了 {total_inserted} 条文档。")

    # 创建常用查询索引以优化沙箱性能
    print("正在创建索引...")
    sales_collection.create_index([("region", 1), ("date", 1)])
    sales_collection.create_index([("store_name", 1), ("date", 1)])
    sales_collection.create_index([("category", 1)])
    print("索引创建完毕。")


if __name__ == "__main__":
    generate_sales_data()