import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGODB_DB", "lore")]

# 更新后的正确索引定义语法
index_definition = {
    "name": "memory_vec",
    "type": "vectorSearch",  # 显式指定索引类型为 vectorSearch
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 1024,
                "similarity": "cosine"
            },
            {
                "type": "filter",
                "path": "status"
            },
            {
                "type": "filter",
                "path": "visibility"
            },
            {
                "type": "filter",
                "path": "expires_at"
            }
        ]
    }
}

try:
    # 删除可能存在的残缺索引（如果之前创建失败过）
    try:
        db["memories"].drop_search_index("memory_vec")
    except Exception:
        pass

    db.command("createSearchIndexes", "memories", indexes=[index_definition])
    print("成功提交 `memory_vec` 向量索引创建请求！")
except Exception as e:
    print(f"创建索引失败: {e}")