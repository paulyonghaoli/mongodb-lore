import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient

def init_other_collections():
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    DB_NAME = os.getenv("MONGODB_DB", "lore")
    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]

    # 确保其他核心集合存在
    collections = ["memories", "sessions", "episodes", "skills", "audit_log"]
    existing = db.list_collection_names()

    for col in collections:
        if col not in existing:
            # 通过插入并删除一个临时文档来创建集合
            db[col].insert_one({"_init": True})
            db[col].delete_one({"_init": True})
            print(f"创建集合: {col}")

    # 注意：Atlas 向量搜索索引 (memory_vec 和 episode_vec) 需在 MongoDB Atlas UI 中或通过 Atlas Search API 创建
    print("初始化完成。请记得在 MongoDB Atlas 中为 `memories` 配置 `memory_vec` 向量索引（1024维，voyage-4，余弦相似度）。")


if __name__ == "__main__":
    init_other_collections()