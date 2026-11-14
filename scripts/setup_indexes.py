"""Create regular and Vector Search indexes (contracts: Vector indexes).

memory_vec on memories, episode_vec on episodes; skills get none.
Usage: python -m scripts.setup_indexes
"""
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

from app import db
from app.config import get_settings


def regular() -> None:
    d = db.app_db()
    d[db.SALES].create_index([("region", ASCENDING), ("date", ASCENDING)])
    d[db.SALES].create_index([("store_id", ASCENDING), ("date", ASCENDING)])
    d[db.SALES].create_index([("category", ASCENDING), ("date", ASCENDING)])
    d[db.MEMORIES].create_index("memory_id", unique=True)
    d[db.MEMORIES].create_index([("title", ASCENDING), ("version", DESCENDING)])
    d[db.MEMORIES].create_index([("status", ASCENDING), ("visibility", ASCENDING)])
    d[db.SESSIONS].create_index([("session_id", ASCENDING), ("ts", ASCENDING)])
    d[db.EPISODES].create_index("cluster_id")
    d[db.SKILLS].create_index([("name", ASCENDING), ("version", DESCENDING)])
    d[db.AUDIT_LOG].create_index([("ts", DESCENDING)])
    # No TTL index on memories: the reviewer view must show expired and forgotten ones.
    print("regular indexes ok")


def vector() -> None:
    dim = get_settings().embedding_dim
    specs = {
        db.MEMORIES: SearchIndexModel(name="memory_vec", type="vectorSearch", definition={"fields": [
            {"type": "vector", "path": "embedding", "numDimensions": dim, "similarity": "cosine"},
            {"type": "filter", "path": "status"},
            {"type": "filter", "path": "visibility"},
            {"type": "filter", "path": "expires_at"},
        ]}),
        db.EPISODES: SearchIndexModel(name="episode_vec", type="vectorSearch", definition={"fields": [
            {"type": "vector", "path": "embedding", "numDimensions": dim, "similarity": "cosine"},
            {"type": "filter", "path": "cluster_id"},
        ]}),
    }
    for coll, model in specs.items():
        col = db.app_db()[coll]
        if coll not in db.app_db().list_collection_names():
            db.app_db().create_collection(coll)
        existing = {i["name"] for i in col.list_search_indexes()}
        if model.document["name"] in existing:
            print(f"{model.document['name']} exists")
            continue
        try:
            col.create_search_index(model)
            print(f"{model.document['name']} created (takes ~1 min to become queryable)")
        except OperationFailure as e:
            print(f"could not create {model.document['name']}: {e}")


if __name__ == "__main__":
    regular()
    vector()
