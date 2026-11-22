from __future__ import annotations

from typing import Any, Optional
from bson import ObjectId

from database import (
    get_bookings_collection,
    get_movies_collection,
    get_reviews_collection,
    get_users_collection,
    get_watchlists_collection,
)
from utils.serializers import serialize_doc


def get_personalized_recommendations(user_id: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
    """Generates personalized movie recommendations using user watchlist, bookings, ratings, and genre affinities."""
    movies_coll = get_movies_collection()
    all_movies = list(movies_coll.find())

    if not user_id:
        # Default top-rated and trending
        sorted_movies = sorted(all_movies, key=lambda x: float(x.get("rating") or 0), reverse=True)
        return [serialize_doc(m) for m in sorted_movies[:limit]]

    # 1. Fetch user data
    users_coll = get_users_collection()
    user = None
    try:
        user = users_coll.find_one({"_id": ObjectId(user_id)})
    except Exception:
        pass
    if not user:
        user = users_coll.find_one({"id": user_id})

    # User preferences
    preferred_genres = set()
    if user and "preferences" in user and "favorite_genres" in user["preferences"]:
        for g in user["preferences"]["favorite_genres"]:
            preferred_genres.add(g.lower())

    # 2. Fetch watchlist
    watchlists_coll = get_watchlists_collection()
    watchlist_items = list(watchlists_coll.find({"user_id": user_id}))
    watchlist_movie_ids = {str(item["movie_id"]) for item in watchlist_items}

    # 3. Fetch past bookings
    bookings_coll = get_bookings_collection()
    user_bookings = list(bookings_coll.find({"user_id": user_id, "payment_status": "paid"}))
    booked_movie_ids = {str(b.get("movie_id")) for b in user_bookings}

    # 4. Fetch user reviews / ratings
    reviews_coll = get_reviews_collection()
    user_reviews = list(reviews_coll.find({"user_id": user_id}))
    reviewed_movie_ids = {str(r.get("movie_id")) for r in user_reviews}

    # Learn user genre preferences from highly rated movies or booked movies
    for b in user_bookings:
        m_id = str(b.get("movie_id"))
        for m in all_movies:
            if str(m.get("_id") or m.get("id")) == m_id:
                for g in m.get("genres") or []:
                    preferred_genres.add(g.lower())

    for r in user_reviews:
        if r.get("rating", 0) >= 4.0:
            m_id = str(r.get("movie_id"))
            for m in all_movies:
                if str(m.get("_id") or m.get("id")) == m_id:
                    for g in m.get("genres") or []:
                        preferred_genres.add(g.lower())

    # Score each movie
    scored_movies = []
    for m in all_movies:
        mid = str(m.get("_id") or m.get("id"))
        # Do not re-recommend already booked movies
        if mid in booked_movie_ids:
            continue

        score = float(m.get("rating") or 7.0)
        reasons = []

        # Boost if in watchlist
        if mid in watchlist_movie_ids:
            score += 3.0
            reasons.append("In your Watchlist")

        # Boost if matches preferred genres
        genres = [g.lower() for g in (m.get("genres") or [])]
        matched_g = [g for g in genres if g in preferred_genres]
        if matched_g:
            score += len(matched_g) * 1.5
            reasons.append(f"Matches your taste in {matched_g[0].title()}")

        if m.get("is_trending"):
            score += 0.8
            reasons.append("Trending this week")

        doc = serialize_doc(m)
        doc["recommendation_score"] = round(score, 2)
        doc["recommendation_reason"] = " • ".join(reasons) if reasons else "Critics' Choice"
        scored_movies.append(doc)

    scored_movies.sort(key=lambda x: x["recommendation_score"], reverse=True)
    return scored_movies[:limit]
