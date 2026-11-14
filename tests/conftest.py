import os

os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["VECTOR_BACKEND"] = "local"

import mongomock
import pytest

from app import db
from app.config import get_settings


@pytest.fixture(autouse=True)
def mock_db():
    get_settings.cache_clear()
    client = mongomock.MongoClient(tz_aware=True)
    db.set_databases(client["lore_test"])
    yield client["lore_test"]
