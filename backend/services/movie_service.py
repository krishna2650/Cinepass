from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo.errors import DuplicateKeyError, PyMongoError

from database import DatabaseUnavailable, get_movies_collection
from services.movie_scraper import normalize_movie_data, scrape_movie
from utils.serializers import serialize_movie
from utils.validators import normalize_movie_title


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_movies(limit: int = 50, skip: int = 0) -> list[dict[str, Any]]:
    try:
        cursor = get_movies_collection().find().sort("rating", -1).skip(skip).limit(limit)
        return [serialize_movie(normalize_movie_data(m)) for m in cursor]
    except PyMongoError as exc:
        raise DatabaseUnavailable("The movie database is currently unavailable.") from exc


def get_movie(movie_id: str) -> dict[str, Any] | None:
    try:
        coll = get_movies_collection()
        movie = None
        try:
            movie = coll.find_one({"_id": ObjectId(movie_id)})
        except Exception:
            pass
        if not movie:
            movie = coll.find_one({"id": movie_id})
        return serialize_movie(normalize_movie_data(movie)) if movie else None
    except PyMongoError as exc:
        raise DatabaseUnavailable("The movie database is currently unavailable.") from exc


def get_movie_by_slug_or_id(identifier: str) -> dict[str, Any] | None:
    coll = get_movies_collection()
    movie = None
    try:
        movie = coll.find_one({"_id": ObjectId(identifier)})
    except Exception:
        pass
    if not movie:
        movie = coll.find_one({"normalized_title": normalize_movie_title(identifier)})
    return serialize_movie(normalize_movie_data(movie)) if movie else None


def discover_movies(
    query: Optional[str] = None,
    genre: Optional[str] = None,
    language: Optional[str] = None,
    min_rating: Optional[float] = None,
    year: Optional[str] = None,
    sort_by: str = "rating_desc",
    category: Optional[str] = None,
    page: int = 1,
    limit: int = 24,
) -> dict[str, Any]:
    """Advanced movie discovery with multi-field search, filters, sorting, and pagination."""
    coll = get_movies_collection()
    filter_dict: dict[str, Any] = {}

    if query:
        clean_q = re.escape(query.strip())
        filter_dict["$or"] = [
            {"title": {"$regex": clean_q, "$options": "i"}},
            {"director": {"$regex": clean_q, "$options": "i"}},
            {"cast": {"$regex": clean_q, "$options": "i"}},
            {"description": {"$regex": clean_q, "$options": "i"}},
        ]

    if genre and genre.lower() != "all":
        filter_dict["genres"] = {"$regex": f"^{re.escape(genre)}$", "$options": "i"}

    if language and language.lower() != "all":
        filter_dict["language"] = {"$regex": re.escape(language), "$options": "i"}

    if min_rating and min_rating > 0:
        filter_dict["rating"] = {"$gte": float(min_rating)}

    if year and year.lower() != "all":
        filter_dict["year"] = {"$regex": re.escape(year)}

    if category:
        cat = category.lower()
        if cat == "now_showing":
            filter_dict["$or"] = [{"is_now_showing": True}, {"status": "now_showing"}]
        elif cat == "coming_soon":
            filter_dict["$or"] = [{"is_coming_soon": True}, {"status": "coming_soon"}]
        elif cat == "trending":
            filter_dict["$or"] = [{"is_trending": True}, {"rating": {"$gte": 8.0}}]
        elif cat == "top_rated":
            filter_dict["rating"] = {"$gte": 8.3}
        elif cat == "popular":
            filter_dict["$or"] = [{"is_popular": True}, {"rating": {"$gte": 7.8}}]

    total_count = coll.count_documents(filter_dict)

    # Sort options
    sort_fields = [("rating", -1)]
    if sort_by == "rating_asc":
        sort_fields = [("rating", 1)]
    elif sort_by == "year_desc":
        sort_fields = [("year", -1)]
    elif sort_by == "year_asc":
        sort_fields = [("year", 1)]
    elif sort_by == "title_asc":
        sort_fields = [("title", 1)]
    elif sort_by == "newest":
        sort_fields = [("created_at", -1)]

    skip = max(0, (page - 1) * limit)
    cursor = coll.find(filter_dict).sort(sort_fields).skip(skip).limit(limit)
    items = [serialize_movie(normalize_movie_data(m)) for m in cursor]

    total_pages = max(1, (total_count + limit - 1) // limit)
    return {
        "movies": items,
        "page": page,
        "limit": limit,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def get_search_suggestions(query: str, limit: int = 8) -> list[dict[str, Any]]:
    if not query or len(query.strip()) < 2:
        return []
    clean_q = re.escape(query.strip())
    coll = get_movies_collection()
    cursor = coll.find(
        {"$or": [
            {"title": {"$regex": clean_q, "$options": "i"}},
            {"cast": {"$regex": clean_q, "$options": "i"}},
            {"director": {"$regex": clean_q, "$options": "i"}},
        ]}
    ).limit(limit)

    suggestions = []
    for m in cursor:
        suggestions.append({
            "id": str(m.get("_id") or m.get("id")),
            "title": m.get("title"),
            "year": m.get("year"),
            "genres": m.get("genres", []),
            "language": m.get("language"),
            "rating": m.get("rating"),
            "poster_url": m.get("poster_url"),
        })
    return suggestions


def get_similar_movies(movie_id: str, limit: int = 6) -> list[dict[str, Any]]:
    current = get_movie(movie_id)
    if not current:
        return []

    genres = current.get("genres") or []
    coll = get_movies_collection()
    query: dict[str, Any] = {
        "id": {"$ne": current.get("id")},
    }
    if genres:
        query["genres"] = {"$in": genres}

    similar = list(coll.find(query).limit(limit))
    return [serialize_movie(normalize_movie_data(m)) for m in similar]


def get_homepage_curated() -> dict[str, Any]:
    """Returns curated groups for the cinema homepage."""
    coll = get_movies_collection()
    all_movies = list(coll.find())
    serialized = [serialize_movie(normalize_movie_data(m)) for m in all_movies]

    now_showing = [m for m in serialized if m.get("is_now_showing") or m.get("status") == "now_showing"]
    coming_soon = [m for m in serialized if m.get("is_coming_soon") or m.get("status") == "coming_soon"]
    trending = [m for m in serialized if m.get("is_trending") or (m.get("rating") and float(m.get("rating")) >= 8.2)]
    top_rated = sorted([m for m in serialized if m.get("rating")], key=lambda x: float(x.get("rating") or 0), reverse=True)[:10]

    # Fallback groupings if tags are sparse
    if not now_showing:
        now_showing = serialized[:8]
    if not coming_soon:
        coming_soon = serialized[8:14] if len(serialized) >= 14 else serialized[:6]
    if not trending:
        trending = top_rated[:8]

    # Collect distinct genres and languages
    all_genres = set()
    all_languages = set()
    all_years = set()
    for m in serialized:
        for g in m.get("genres") or []:
            if g and g != "Not available":
                all_genres.add(g)
        lang = m.get("language")
        if lang and lang != "Not available":
            for l in re.split(r"[,/|]+", lang):
                cleaned_l = l.strip()
                if cleaned_l:
                    all_languages.add(cleaned_l)
        y = m.get("year")
        if y and y.isdigit():
            all_years.add(y)

    return {
        "hero_carousel": (trending[:5] or serialized[:5]),
        "now_showing": now_showing[:12],
        "coming_soon": coming_soon[:8],
        "trending": trending[:10],
        "top_rated": top_rated[:10],
        "available_genres": sorted(list(all_genres)),
        "available_languages": sorted(list(all_languages)),
        "available_years": sorted(list(all_years), reverse=True),
    }


def search_or_scrape_movie(query: str, timeout: int) -> tuple[dict | None, str]:
    normalized = normalize_movie_title(query)
    try:
        collection = get_movies_collection()
        existing = collection.find_one({"normalized_title": normalized})
        if existing:
            return serialize_movie(normalize_movie_data(existing)), "database"
    except PyMongoError as exc:
        raise DatabaseUnavailable("The movie database is currently unavailable.") from exc

    scraped = normalize_movie_data(scrape_movie(query, timeout) or {})
    if not scraped or not scraped.get("title"):
        return None, "scraped"
    scraped.update({
        "normalized_title": normalized,
        "ai_summary": None,
        "summary_genre": None,
        "summary_mood": None,
        "summary_suitable_for": None,
        "summary_provider": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    try:
        result = collection.update_one({"normalized_title": normalized}, {"$setOnInsert": scraped}, upsert=True)
        if result.upserted_id:
            scraped["_id"] = result.upserted_id
            return serialize_movie(normalize_movie_data(scraped)), "scraped"
        existing = collection.find_one({"normalized_title": normalized})
        return serialize_movie(normalize_movie_data(existing)), "database"
    except DuplicateKeyError:
        existing = collection.find_one({"normalized_title": normalized})
        return serialize_movie(normalize_movie_data(existing)), "database"
    except PyMongoError as exc:
        raise DatabaseUnavailable("The movie database is currently unavailable.") from exc


def save_summary(movie_id: str, summary: dict[str, str], provider: str) -> None:
    try:
        coll = get_movies_collection()
        update_doc = {
            "ai_summary": summary["summary"],
            "summary_genre": summary["genre"],
            "summary_mood": summary["mood"],
            "summary_suitable_for": summary["suitable_for"],
            "summary_provider": provider,
            "updated_at": _now(),
        }
        try:
            coll.update_one({"_id": ObjectId(movie_id)}, {"$set": update_doc})
        except Exception:
            coll.update_one({"id": movie_id}, {"$set": update_doc})
    except PyMongoError as exc:
        raise DatabaseUnavailable("The movie database is currently unavailable.") from exc
