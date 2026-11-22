from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from bson import ObjectId

from database import get_bookings_collection, get_movies_collection, get_reviews_collection
from utils.serializers import serialize_doc


class ReviewError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add_or_update_review(
    movie_id: str,
    user_id: str,
    user_name: str,
    rating: float,
    content: str,
    title: Optional[str] = None,
) -> dict[str, Any]:
    if not (1.0 <= rating <= 5.0):
        raise ReviewError("Rating must be between 1 and 5 stars.")
    if not content or len(content.strip()) < 5:
        raise ReviewError("Review text must be at least 5 characters.")

    reviews_coll = get_reviews_collection()
    bookings_coll = get_bookings_collection()

    # Check if user has a confirmed booking for this movie to assign verified viewer badge
    has_booked = bookings_coll.find_one({
        "user_id": user_id,
        "payment_status": "paid",
        "$or": [
            {"movie_id": movie_id},
            {"movie_id": str(movie_id)},
        ],
    }) is not None

    existing = reviews_coll.find_one({"movie_id": str(movie_id), "user_id": str(user_id)})
    now = _now()

    if existing:
        reviews_coll.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "rating": float(rating),
                "title": (title or "").strip()[:100],
                "content": content.strip()[:1000],
                "is_verified_booking": has_booked,
                "updated_at": now,
            }}
        )
        rev = reviews_coll.find_one({"_id": existing["_id"]})
    else:
        new_doc = {
            "movie_id": str(movie_id),
            "user_id": str(user_id),
            "user_name": user_name,
            "rating": float(rating),
            "title": (title or "").strip()[:100],
            "content": content.strip()[:1000],
            "is_verified_booking": has_booked,
            "helpful_count": 0,
            "reported": False,
            "created_at": now,
            "updated_at": now,
        }
        res = reviews_coll.insert_one(new_doc)
        new_doc["_id"] = res.inserted_id
        rev = new_doc

    _recalculate_movie_rating(movie_id)
    return serialize_doc(rev)


def list_movie_reviews(movie_id: str, sort_by: str = "newest", limit: int = 20) -> dict[str, Any]:
    reviews_coll = get_reviews_collection()
    query = {"movie_id": str(movie_id), "reported": {"$ne": True}}

    sort_order = [("created_at", -1)]
    if sort_by == "highest_rating":
        sort_order = [("rating", -1), ("created_at", -1)]
    elif sort_by == "lowest_rating":
        sort_order = [("rating", 1), ("created_at", -1)]

    cursor = reviews_coll.find(query).sort(sort_order).limit(limit)
    reviews = [serialize_doc(r) for r in cursor]

    # Calculate average
    all_revs = list(reviews_coll.find({"movie_id": str(movie_id)}))
    total_count = len(all_revs)
    avg_rating = round(sum(r.get("rating", 0.0) for r in all_revs) / total_count, 1) if total_count > 0 else None

    return {
        "reviews": reviews,
        "total_count": total_count,
        "average_rating": avg_rating,
    }


def delete_review(review_id: str, user_id: str, is_admin: bool = False) -> bool:
    reviews_coll = get_reviews_collection()
    rev = reviews_coll.find_one({"_id": ObjectId(review_id)})
    if not rev:
        rev = reviews_coll.find_one({"id": review_id})
    if not rev:
        raise ReviewError("Review not found.")

    if not is_admin and str(rev.get("user_id")) != str(user_id):
        raise ReviewError("You do not have permission to delete this review.")

    reviews_coll.delete_one({"_id": rev["_id"]})
    _recalculate_movie_rating(str(rev.get("movie_id")))
    return True


def report_review(review_id: str) -> bool:
    reviews_coll = get_reviews_collection()
    reviews_coll.update_one({"_id": ObjectId(review_id)}, {"$set": {"reported": True, "reported_at": _now()}})
    return True


def _recalculate_movie_rating(movie_id: str):
    try:
        reviews_coll = get_reviews_collection()
        all_revs = list(reviews_coll.find({"movie_id": str(movie_id)}))
        if not all_revs:
            return
        avg = round(sum(r.get("rating", 0.0) for r in all_revs) / len(all_revs), 1)
        # Update movie document if desired, keeping IMDb / seed rating intact or augmenting
        movies_coll = get_movies_collection()
        movies_coll.update_one(
            {"_id": ObjectId(movie_id)},
            {"$set": {"user_rating": avg, "review_count": len(all_revs)}}
        )
    except Exception:
        pass
