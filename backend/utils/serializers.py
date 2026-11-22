from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId


def serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    return value


def serialize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    result = serialize_value(doc)
    if "_id" in result:
        result["id"] = result.pop("_id")
    elif "id" not in result and "_id" not in result:
        result["id"] = None
    return result


def serialize_movie(movie: dict[str, Any] | None) -> dict[str, Any] | None:
    return serialize_doc(movie)
