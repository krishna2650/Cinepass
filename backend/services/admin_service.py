from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from bson import ObjectId

from database import (
    get_bookings_collection,
    get_cinemas_collection,
    get_coupons_collection,
    get_movies_collection,
    get_payments_collection,
    get_reviews_collection,
    get_screens_collection,
    get_shows_collection,
    get_users_collection,
)
from utils.serializers import serialize_doc
from utils.validators import normalize_movie_title


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_platform_statistics() -> dict[str, Any]:
    bookings_coll = get_bookings_collection()
    users_coll = get_users_collection()
    movies_coll = get_movies_collection()
    cinemas_coll = get_cinemas_collection()
    shows_coll = get_shows_collection()

    all_paid_bookings = list(bookings_coll.find({"payment_status": "paid"}))
    total_revenue = sum(float(b.get("total_amount", 0.0)) for b in all_paid_bookings)
    total_tickets = sum(len(b.get("seats") or []) for b in all_paid_bookings)

    return {
        "total_revenue": round(total_revenue, 2),
        "total_tickets_sold": total_tickets,
        "total_bookings": len(all_paid_bookings),
        "total_users": users_coll.count_documents(),
        "total_movies": movies_coll.count_documents(),
        "total_cinemas": cinemas_coll.count_documents(),
        "total_active_shows": shows_coll.count_documents(),
    }


def admin_add_movie(data: dict[str, Any]) -> dict[str, Any]:
    movies_coll = get_movies_collection()
    title = data.get("title", "").strip()
    if not title:
        raise ValueError("Movie title is required.")

    normalized = normalize_movie_title(title)
    existing = movies_coll.find_one({"normalized_title": normalized})
    if existing:
        raise ValueError(f"Movie '{title}' already exists.")

    now = _now()
    doc = {
        "title": title,
        "normalized_title": normalized,
        "year": str(data.get("year", "2026")),
        "genres": data.get("genres", ["Drama"]),
        "language": data.get("language", "English"),
        "duration": data.get("duration", "120 minutes"),
        "director": data.get("director", "Unknown"),
        "cast": data.get("cast", []),
        "description": data.get("description", ""),
        "poster_url": data.get("poster_url", "/static/images/movie-placeholder.svg"),
        "backdrop_url": data.get("backdrop_url", ""),
        "trailer_url": data.get("trailer_url", ""),
        "rating": float(data.get("rating", 8.0)),
        "age_rating": data.get("age_rating", "UA"),
        "is_now_showing": bool(data.get("is_now_showing", True)),
        "is_coming_soon": bool(data.get("is_coming_soon", False)),
        "is_trending": bool(data.get("is_trending", False)),
        "created_at": now,
        "updated_at": now,
    }
    res = movies_coll.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)


def admin_update_movie(movie_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    movies_coll = get_movies_collection()
    updates["updated_at"] = _now()
    if "title" in updates:
        updates["normalized_title"] = normalize_movie_title(updates["title"])
    if "rating" in updates:
        updates["rating"] = float(updates["rating"])

    try:
        movies_coll.update_one({"_id": ObjectId(movie_id)}, {"$set": updates})
    except Exception:
        movies_coll.update_one({"id": movie_id}, {"$set": updates})

    updated = movies_coll.find_one({"_id": ObjectId(movie_id)}) if ObjectId.is_valid(movie_id) else movies_coll.find_one({"id": movie_id})
    return serialize_doc(updated)


def admin_delete_movie(movie_id: str) -> bool:
    movies_coll = get_movies_collection()
    try:
        movies_coll.delete_one({"_id": ObjectId(movie_id)})
    except Exception:
        movies_coll.delete_one({"id": movie_id})
    return True


def admin_add_cinema(data: dict[str, Any]) -> dict[str, Any]:
    cinemas_coll = get_cinemas_collection()
    name = data.get("name", "").strip()
    city = data.get("city", "Mumbai").strip()
    if not name or not city:
        raise ValueError("Cinema name and city are required.")

    now = _now()
    doc = {
        "name": name,
        "city": city,
        "location": data.get("location", ""),
        "address": data.get("address", ""),
        "amenities": data.get("amenities", ["Dolby Atmos", "Recliner", "Food Court"]),
        "screens_count": int(data.get("screens_count", 4)),
        "contact_phone": data.get("contact_phone", "+91 22 2840 5500"),
        "rating": float(data.get("rating", 4.5)),
        "image_url": data.get("image_url", "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80"),
        "created_at": now,
        "updated_at": now,
    }
    res = cinemas_coll.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)


def admin_schedule_show(data: dict[str, Any]) -> dict[str, Any]:
    shows_coll = get_shows_collection()
    movie_id = str(data.get("movie_id"))
    cinema_id = str(data.get("cinema_id"))
    screen_id = str(data.get("screen_id", "scr-1"))
    date = str(data.get("date"))
    start_time = str(data.get("start_time"))

    if not movie_id or not cinema_id or not date or not start_time:
        raise ValueError("Movie, cinema, date, and start_time are required.")

    now = _now()
    doc = {
        "movie_id": movie_id,
        "cinema_id": cinema_id,
        "screen_id": screen_id,
        "date": date,
        "start_time": start_time,
        "end_time": data.get("end_time", "11:30 PM"),
        "price_tiers": data.get("price_tiers", {
            "VIP": 550.0,
            "Platinum": 380.0,
            "Gold": 250.0,
            "Silver": 180.0,
        }),
        "status": "scheduled",
        "created_at": now,
        "updated_at": now,
    }
    res = shows_coll.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)


def admin_add_coupon(data: dict[str, Any]) -> dict[str, Any]:
    coupons_coll = get_coupons_collection()
    code = (data.get("code") or "").strip().upper()
    if not code:
        raise ValueError("Coupon code is required.")

    existing = coupons_coll.find_one({"code": code})
    if existing:
        raise ValueError(f"Coupon '{code}' already exists.")

    now = _now()
    doc = {
        "code": code,
        "discount_type": data.get("discount_type", "percentage"),
        "discount_value": float(data.get("discount_value", 20.0)),
        "min_amount": float(data.get("min_amount", 300.0)),
        "max_discount": float(data.get("max_discount", 150.0)),
        "active": bool(data.get("active", True)),
        "usage_limit": int(data.get("usage_limit", 1000)),
        "times_used": 0,
        "created_at": now,
        "updated_at": now,
    }
    res = coupons_coll.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)
