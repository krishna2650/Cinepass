from __future__ import annotations

import copy
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError


_client: Optional[MongoClient] = None
_database: Optional[Database] = None
_connection_error: Optional[str] = None
_using_fallback: bool = False
_fallback_db: Optional[FallbackDatabase] = None


class DatabaseUnavailable(RuntimeError):
    pass


class FallbackCursor:
    """Emulates a PyMongo cursor for our fallback database."""

    def __init__(self, items: list[dict[str, Any]]):
        self._items = items
        self._skip = 0
        self._limit = len(items)

    def sort(self, key_or_list: Any, direction: int = 1) -> FallbackCursor:
        sort_keys = []
        if isinstance(key_or_list, list):
            sort_keys = key_or_list
        elif isinstance(key_or_list, str):
            sort_keys = [(key_or_list, direction)]

        def sort_comparator(item):
            values = []
            for k, d in sort_keys:
                val = item.get(k)
                if val is None:
                    val = ""
                elif isinstance(val, (datetime, ObjectId)):
                    val = str(val)
                values.append(val if d == 1 or d == ASCENDING else -val if isinstance(val, (int, float)) else str(val))
            return tuple(values)

        try:
            self._items.sort(key=sort_comparator, reverse=direction in (-1, DESCENDING))
        except Exception:
            pass
        return self

    def skip(self, count: int) -> FallbackCursor:
        self._skip = max(0, count)
        return self

    def limit(self, count: int) -> FallbackCursor:
        self._limit = max(0, count)
        return self

    def __iter__(self):
        sliced = self._items[self._skip : self._skip + self._limit]
        return iter(copy.deepcopy(sliced))

    def __getitem__(self, index: int) -> dict[str, Any]:
        return copy.deepcopy(self._items[self._skip : self._skip + self._limit][index])


class FallbackCollection:
    """Thread-safe, persistent collection replicating PyMongo operations."""

    def __init__(self, name: str, parent_db: FallbackDatabase):
        self.name = name
        self.parent = parent_db
        self._lock = threading.RLock()

    def _matches(self, doc: dict[str, Any], query: dict[str, Any]) -> bool:
        if not query:
            return True
        for key, expected in query.items():
            if key == "$or":
                if not any(self._matches(doc, subq) for subq in expected):
                    return False
                continue
            if key == "$and":
                if not all(self._matches(doc, subq) for subq in expected):
                    return False
                continue

            val = doc.get(key)
            if isinstance(expected, dict):
                for op, op_val in expected.items():
                    if op == "$eq" and val != op_val:
                        return False
                    elif op == "$ne" and val == op_val:
                        return False
                    elif op == "$in":
                        if isinstance(val, (list, tuple, set)):
                            if not any(item in op_val for item in val):
                                return False
                        elif val not in op_val:
                            return False
                    elif op == "$nin":
                        if isinstance(val, (list, tuple, set)):
                            if any(item in op_val for item in val):
                                return False
                        elif val in op_val:
                            return False
                    elif op == "$gt" and not (val is not None and val > op_val):
                        return False
                    elif op == "$gte" and not (val is not None and val >= op_val):
                        return False
                    elif op == "$lt" and not (val is not None and val < op_val):
                        return False
                    elif op == "$lte" and not (val is not None and val <= op_val):
                        return False
                    elif op == "$regex":
                        pattern = op_val
                        flags = re.IGNORECASE if expected.get("$options") == "i" else 0
                        if not re.search(pattern, str(val or ""), flags=flags):
                            return False
                    elif op == "$exists":
                        if op_val and key not in doc:
                            return False
                        if not op_val and key in doc:
                            return False
            elif isinstance(expected, ObjectId):
                if str(val) != str(expected):
                    return False
            elif expected != val:
                # support string vs ObjectId comparison
                if key == "_id" and str(val) == str(expected):
                    continue
                return False
        return True

    def find(self, query: Optional[dict[str, Any]] = None, projection: Optional[dict[str, Any]] = None) -> FallbackCursor:
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            query = query or {}
            matched = [doc for doc in data if self._matches(doc, query)]
            return FallbackCursor(matched)

    def find_one(self, query: Optional[dict[str, Any]] = None, projection: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            query = query or {}
            for doc in data:
                if self._matches(doc, query):
                    return copy.deepcopy(doc)
            return None

    def insert_one(self, document: dict[str, Any]):
        with self._lock:
            doc = copy.deepcopy(document)
            if "_id" not in doc:
                doc["_id"] = ObjectId()
            elif isinstance(doc["_id"], str):
                try:
                    doc["_id"] = ObjectId(doc["_id"])
                except Exception:
                    pass
            data = self.parent.get_collection_data(self.name)
            data.append(doc)
            self.parent.save()

            class Result:
                def __init__(self, inserted_id):
                    self.inserted_id = inserted_id

            return Result(doc["_id"])

    def insert_many(self, documents: list[dict[str, Any]]):
        inserted_ids = []
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            for d in documents:
                doc = copy.deepcopy(d)
                if "_id" not in doc:
                    doc["_id"] = ObjectId()
                data.append(doc)
                inserted_ids.append(doc["_id"])
            self.parent.save()

            class Result:
                def __init__(self, ids):
                    self.inserted_ids = ids

            return Result(inserted_ids)

    def update_one(self, filter_query: dict[str, Any], update_ops: dict[str, Any], upsert: bool = False):
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            matched_doc = None
            for doc in data:
                if self._matches(doc, filter_query):
                    matched_doc = doc
                    break

            if matched_doc:
                self._apply_update(matched_doc, update_ops)
                self.parent.save()

                class Result:
                    matched_count = 1
                    modified_count = 1
                    upserted_id = None

                return Result()
            elif upsert:
                new_doc = copy.deepcopy(filter_query)
                if "$setOnInsert" in update_ops:
                    new_doc.update(update_ops["$setOnInsert"])
                if "$set" in update_ops:
                    new_doc.update(update_ops["$set"])
                if "_id" not in new_doc:
                    new_doc["_id"] = ObjectId()
                data.append(new_doc)
                self.parent.save()

                class Result:
                    matched_count = 0
                    modified_count = 0
                    upserted_id = new_doc["_id"]

                return Result()

            class Result:
                matched_count = 0
                modified_count = 0
                upserted_id = None

            return Result()

    def update_many(self, filter_query: dict[str, Any], update_ops: dict[str, Any]):
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            count = 0
            for doc in data:
                if self._matches(doc, filter_query):
                    self._apply_update(doc, update_ops)
                    count += 1
            if count > 0:
                self.parent.save()

            class Result:
                matched_count = count
                modified_count = count

            return Result()

    def _apply_update(self, doc: dict[str, Any], update_ops: dict[str, Any]):
        if "$set" in update_ops:
            for k, v in update_ops["$set"].items():
                doc[k] = copy.deepcopy(v)
        if "$unset" in update_ops:
            for k in update_ops["$unset"]:
                doc.pop(k, None)
        if "$inc" in update_ops:
            for k, v in update_ops["$inc"].items():
                doc[k] = doc.get(k, 0) + v
        if "$push" in update_ops:
            for k, v in update_ops["$push"].items():
                if k not in doc or not isinstance(doc[k], list):
                    doc[k] = []
                doc[k].append(copy.deepcopy(v))
        if "$pull" in update_ops:
            for k, v in update_ops["$pull"].items():
                if k in doc and isinstance(doc[k], list):
                    doc[k] = [item for item in doc[k] if item != v]

    def delete_one(self, filter_query: dict[str, Any]):
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            for i, doc in enumerate(data):
                if self._matches(doc, filter_query):
                    del data[i]
                    self.parent.save()

                    class Result:
                        deleted_count = 1

                    return Result()

            class Result:
                deleted_count = 0

            return Result()

    def delete_many(self, filter_query: dict[str, Any]):
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            initial_len = len(data)
            self.parent.set_collection_data(self.name, [doc for doc in data if not self._matches(doc, filter_query)])
            deleted = initial_len - len(self.parent.get_collection_data(self.name))
            if deleted > 0:
                self.parent.save()

            class Result:
                deleted_count = deleted

            return Result()

    def count_documents(self, filter_query: Optional[dict[str, Any]] = None) -> int:
        with self._lock:
            data = self.parent.get_collection_data(self.name)
            if not filter_query:
                return len(data)
            return sum(1 for doc in data if self._matches(doc, filter_query))

    def create_index(self, keys: Any, **kwargs):
        # Index creation is a no-op in memory/file fallback
        return str(keys)


class FallbackDatabase:
    """Thread-safe persistent JSON document engine for local fallback."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._lock = threading.RLock()
        self._collections: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _serialize_doc(self, obj: Any) -> Any:
        if isinstance(obj, ObjectId):
            return {"$oid": str(obj)}
        if isinstance(obj, datetime):
            return {"$date": obj.isoformat()}
        if isinstance(obj, list):
            return [self._serialize_doc(item) for item in obj]
        if isinstance(obj, dict):
            return {k: self._serialize_doc(v) for k, v in obj.items()}
        return obj

    def _deserialize_doc(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            if "$oid" in obj and len(obj) == 1:
                return ObjectId(obj["$oid"])
            if "$date" in obj and len(obj) == 1:
                return datetime.fromisoformat(obj["$date"])
            return {k: self._deserialize_doc(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deserialize_doc(item) for item in obj]
        return obj

    def _load(self):
        with self._lock:
            if self.filepath.exists():
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    self._collections = {
                        coll_name: [self._deserialize_doc(doc) for doc in docs]
                        for coll_name, docs in raw.items()
                    }
                except Exception:
                    self._collections = {}
            else:
                self._collections = {}

    def save(self):
        with self._lock:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            serialized = {
                coll_name: [self._serialize_doc(doc) for doc in docs]
                for coll_name, docs in self._collections.items()
            }
            tmp_path = self.filepath.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.filepath)

    def get_collection_data(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            if name not in self._collections:
                self._collections[name] = []
            return self._collections[name]

    def set_collection_data(self, name: str, data: list[dict[str, Any]]):
        with self._lock:
            self._collections[name] = data

    def __getitem__(self, name: str) -> FallbackCollection:
        return FallbackCollection(name, self)

    def __getattr__(self, name: str) -> FallbackCollection:
        return FallbackCollection(name, self)


def initialize_database(app) -> bool:
    """Connect to MongoDB on startup; if unavailable, activate resilient local fallback engine."""
    global _client, _database, _connection_error, _using_fallback, _fallback_db

    try:
        mongo_uri = app.config.get("MONGODB_URI", "mongodb://localhost:27017/")
        timeout = app.config.get("MONGODB_TIMEOUT_MS", 3000)
        _client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=timeout,
            connectTimeoutMS=timeout,
        )
        _client.admin.command("ping")
        db_name = app.config.get("MONGODB_DATABASE", "cinepass_db")
        _database = _client[db_name]

        # Setup MongoDB indexes
        _database.movies.create_index([("normalized_title", ASCENDING)], unique=True)
        _database.users.create_index([("email", ASCENDING)], unique=True)
        _database.bookings.create_index([("booking_reference", ASCENDING)], unique=True)
        _database.seat_locks.create_index([("show_id", ASCENDING), ("seat_id", ASCENDING)], unique=True)
        _database.seat_locks.create_index([("expires_at", ASCENDING)])
        _database.shows.create_index([("movie_id", ASCENDING), ("cinema_id", ASCENDING), ("date", ASCENDING)])
        _database.cinemas.create_index([("city", ASCENDING)])
        _database.coupons.create_index([("code", ASCENDING)], unique=True)

        _connection_error = None
        _using_fallback = False
        return True
    except Exception as exc:
        _client = None
        _database = None
        _connection_error = f"MongoDB connection failed: {exc}"

        if app.config.get("ALLOW_FALLBACK_DB", True):
            # Activate fallback file database
            storage_dir = Path(__file__).resolve().parent / "data"
            storage_file = storage_dir / "cinepass_store.json"
            _fallback_db = FallbackDatabase(storage_file)
            _using_fallback = True
            return True

        return False


def get_database() -> Database | FallbackDatabase:
    if _database is not None:
        return _database
    if _using_fallback and _fallback_db is not None:
        return _fallback_db
    raise DatabaseUnavailable(_connection_error or "The database is currently unavailable.")


def get_collection(name: str):
    db = get_database()
    return db[name]


def get_movies_collection():
    return get_collection("movies")


def get_users_collection():
    return get_collection("users")


def get_cinemas_collection():
    return get_collection("cinemas")


def get_screens_collection():
    return get_collection("screens")


def get_shows_collection():
    return get_collection("shows")


def get_seat_locks_collection():
    return get_collection("seat_locks")


def get_bookings_collection():
    return get_collection("bookings")


def get_payments_collection():
    return get_collection("payments")


def get_reviews_collection():
    return get_collection("reviews")


def get_coupons_collection():
    return get_collection("coupons")


def get_snacks_collection():
    return get_collection("snacks")


def get_watchlists_collection():
    return get_collection("watchlists")


def is_database_available() -> bool:
    return _database is not None or (_using_fallback and _fallback_db is not None)


def is_using_fallback() -> bool:
    return _using_fallback


def database_error_message() -> str:
    return _connection_error or "The database is currently unavailable."


def close_database(_: object = None) -> None:
    global _client, _database, _fallback_db
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _database = None
    _fallback_db = None
