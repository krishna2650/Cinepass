from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo.errors import PyMongoError

from database import (
    DatabaseUnavailable,
    get_cinemas_collection,
    get_movies_collection,
    get_screens_collection,
    get_shows_collection,
)
from utils.serializers import serialize_doc


SUPPORTED_CITIES = [
    {"id": "mumbai", "name": "Mumbai", "state": "Maharashtra", "is_metro": True},
    {"id": "delhi-ncr", "name": "Delhi-NCR", "state": "Delhi / Haryana / UP", "is_metro": True},
    {"id": "bengaluru", "name": "Bengaluru", "state": "Karnataka", "is_metro": True},
    {"id": "hyderabad", "name": "Hyderabad", "state": "Telangana", "is_metro": True},
    {"id": "chennai", "name": "Chennai", "state": "Tamil Nadu", "is_metro": True},
    {"id": "pune", "name": "Pune", "state": "Maharashtra", "is_metro": False},
    {"id": "kolkata", "name": "Kolkata", "state": "West Bengal", "is_metro": True},
    {"id": "ahmedabad", "name": "Ahmedabad", "state": "Gujarat", "is_metro": False},
    {"id": "chandigarh", "name": "Chandigarh", "state": "Punjab / Haryana", "is_metro": False},
    {"id": "kochi", "name": "Kochi", "state": "Kerala", "is_metro": False},
]


def list_cities() -> list[dict[str, Any]]:
    return SUPPORTED_CITIES


def list_cinemas(
    city: Optional[str] = None,
    search: Optional[str] = None,
    amenity: Optional[str] = None,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if city and city.lower() != "all":
        # match case-insensitively
        query["city"] = {"$regex": f"^{re.escape(city)}$", "$options": "i"}

    if search:
        query["$or"] = [
            {"name": {"$regex": re.escape(search), "$options": "i"}},
            {"location": {"$regex": re.escape(search), "$options": "i"}},
            {"address": {"$regex": re.escape(search), "$options": "i"}},
        ]

    cinemas = list(get_cinemas_collection().find(query))

    if amenity:
        amenity_lower = amenity.strip().lower()
        cinemas = [
            c for c in cinemas
            if any(amenity_lower in str(a).lower() for a in (c.get("amenities") or []))
        ]

    return [serialize_doc(c) for c in cinemas]


def get_cinema(cinema_id: str) -> Optional[dict[str, Any]]:
    try:
        cinema = get_cinemas_collection().find_one({"_id": ObjectId(cinema_id)})
        if not cinema:
            # try finding by string id if stored that way
            cinema = get_cinemas_collection().find_one({"id": cinema_id})
        return serialize_doc(cinema)
    except Exception:
        cinema = get_cinemas_collection().find_one({"id": cinema_id})
        return serialize_doc(cinema)


def get_screens_for_cinema(cinema_id: str) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"$or": [{"cinema_id": cinema_id}, {"cinema_id": str(cinema_id)}]}
    try:
        query["$or"].append({"cinema_id": ObjectId(cinema_id)})
    except Exception:
        pass
    screens = list(get_screens_collection().find(query))
    return [serialize_doc(s) for s in screens]


def get_shows(
    movie_id: Optional[str] = None,
    cinema_id: Optional[str] = None,
    city: Optional[str] = None,
    date: Optional[str] = None,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}

    if movie_id:
        movie_or = [{"movie_id": movie_id}, {"movie_id": str(movie_id)}]
        try:
            movie_or.append({"movie_id": ObjectId(movie_id)})
        except Exception:
            pass
        query["$or"] = movie_or

    if cinema_id:
        cinema_or = [{"cinema_id": cinema_id}, {"cinema_id": str(cinema_id)}]
        try:
            cinema_or.append({"cinema_id": ObjectId(cinema_id)})
        except Exception:
            pass
        if "$or" in query:
            query = {"$and": [{"$or": query["$or"]}, {"$or": cinema_or}]}
        else:
            query["$or"] = cinema_or

    if date:
        query["date"] = date

    raw_shows = list(get_shows_collection().find(query).sort("start_time", 1))

    # Pre-fetch movies, cinemas, screens for fast lookup
    movies_coll = get_movies_collection()
    cinemas_coll = get_cinemas_collection()
    screens_coll = get_screens_collection()

    results = []
    for s in raw_shows:
        show = serialize_doc(s)

        # Lookup movie
        m_id = str(show.get("movie_id"))
        movie_doc = None
        try:
            movie_doc = movies_coll.find_one({"_id": ObjectId(m_id)})
        except Exception:
            movie_doc = movies_coll.find_one({"id": m_id})
        if movie_doc:
            show["movie"] = serialize_doc(movie_doc)

        # Lookup cinema
        c_id = str(show.get("cinema_id"))
        cinema_doc = None
        try:
            cinema_doc = cinemas_coll.find_one({"_id": ObjectId(c_id)})
        except Exception:
            cinema_doc = cinemas_coll.find_one({"id": c_id})
        if cinema_doc:
            show["cinema"] = serialize_doc(cinema_doc)

        # Lookup screen
        sc_id = str(show.get("screen_id"))
        screen_doc = None
        try:
            screen_doc = screens_coll.find_one({"_id": ObjectId(sc_id)})
        except Exception:
            screen_doc = screens_coll.find_one({"id": sc_id})
        if screen_doc:
            show["screen"] = serialize_doc(screen_doc)

        # Filter by city if requested
        if city and city.lower() != "all":
            c_city = (show.get("cinema") or {}).get("city", "")
            if c_city.lower() != city.lower():
                continue

        results.append(show)

    return results


def get_show_by_id(show_id: str) -> Optional[dict[str, Any]]:
    shows = get_shows_collection()
    show_doc = None
    try:
        show_doc = shows.find_one({"_id": ObjectId(show_id)})
    except Exception:
        pass
    if not show_doc:
        show_doc = shows.find_one({"id": show_id})

    if not show_doc:
        return None

    show = serialize_doc(show_doc)
    # Populate movie, cinema, screen
    m_id = str(show.get("movie_id"))
    try:
        show["movie"] = serialize_doc(get_movies_collection().find_one({"_id": ObjectId(m_id)}))
    except Exception:
        show["movie"] = serialize_doc(get_movies_collection().find_one({"id": m_id}))

    c_id = str(show.get("cinema_id"))
    try:
        show["cinema"] = serialize_doc(get_cinemas_collection().find_one({"_id": ObjectId(c_id)}))
    except Exception:
        show["cinema"] = serialize_doc(get_cinemas_collection().find_one({"id": c_id}))

    sc_id = str(show.get("screen_id"))
    try:
        show["screen"] = serialize_doc(get_screens_collection().find_one({"_id": ObjectId(sc_id)}))
    except Exception:
        show["screen"] = serialize_doc(get_screens_collection().find_one({"id": sc_id}))

    return show
