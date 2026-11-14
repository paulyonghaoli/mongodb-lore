"""MongoDB access.

Two handles:
- app_db(): read/write, for memories, sessions, episodes, skills, audit_log.
- business_db(): business data (sales). Use a read-only Atlas user via MONGODB_READONLY_URI.

Tests call set_databases() with mongomock databases.
"""
from pymongo import MongoClient
from pymongo.database import Database

from .config import get_settings

_app_db: Database | None = None
_business_db: Database | None = None

SALES = "sales"
MEMORIES = "memories"
SESSIONS = "sessions"
EPISODES = "episodes"
SKILLS = "skills"
AUDIT_LOG = "audit_log"
MEMORY_REVIEW_RUNS = "memory_review_runs"
MEMORY_REVIEW_ITEMS = "memory_review_items"


def set_databases(app: Database, business: Database | None = None) -> None:
    global _app_db, _business_db
    _app_db = app
    _business_db = business if business is not None else app


def app_db() -> Database:
    global _app_db
    if _app_db is None:
        s = get_settings()
        _app_db = MongoClient(s.mongodb_uri, tz_aware=True)[s.mongodb_db]
    return _app_db


def business_db() -> Database:
    global _business_db
    if _business_db is None:
        s = get_settings()
        uri = s.mongodb_readonly_uri or s.mongodb_uri
        _business_db = MongoClient(uri, tz_aware=True)[s.mongodb_db]
    return _business_db
