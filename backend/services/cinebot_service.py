from __future__ import annotations

import json
import re
from typing import Any, Optional

from config import Config
from database import get_cinemas_collection, get_movies_collection, get_shows_collection
from services.cinema_service import get_shows
from services.movie_service import discover_movies, get_movie_by_slug_or_id
from utils.serializers import serialize_doc


def ask_cinebot(
    message: str,
    city: Optional[str] = None,
    genre: Optional[str] = None,
    language: Optional[str] = None,
) -> dict[str, Any]:
    """CineBot AI Cinema Assistant:
    Grounded in the real movie catalog and real cinema showtimes.
    """
    clean_msg = (message or "").strip().lower()
    if not clean_msg:
        return {
            "reply": "Hello! I'm CineBot, your personal cinema assistant. How can I help you today? You can ask me for movie recommendations, what's good for a family night, or available showtimes in your city!",
            "suggested_movies": [],
            "suggested_shows": [],
        }

    movies_coll = get_movies_collection()
    all_movies = list(movies_coll.find())

    # Detect intent:
    # 1. Showtime query
    is_showtime_query = any(w in clean_msg for w in ["showtime", "show time", "theatre", "theater", "cinema", "timing", "tickets", "playing"])
    # 2. Similar movies query
    is_similar_query = any(w in clean_msg for w in ["similar to", "like ", "movies like"])
    # 3. Mood / Genre query
    mood_match = None
    mood_map = {
        "thriller": "Thriller",
        "romantic": "Romance",
        "romance": "Romance",
        "comedy": "Comedy",
        "funny": "Comedy",
        "horror": "Horror",
        "scifi": "Science Fiction",
        "sci-fi": "Science Fiction",
        "science fiction": "Science Fiction",
        "action": "Action",
        "drama": "Drama",
        "family": "Family",
        "kid": "Family",
        "adventure": "Adventure",
        "happy": "Comedy",
        "emotional": "Drama",
        "excited": "Action",
    }
    for k, v in mood_map.items():
        if k in clean_msg:
            mood_match = v
            break

    suggested_movies = []
    suggested_shows = []
    reply = ""

    # Check if user mentioned a specific movie title
    matched_movie = None
    for m in all_movies:
        m_title = m.get("title", "").lower()
        if m_title and len(m_title) > 3 and m_title in clean_msg:
            matched_movie = m
            break

    if is_showtime_query:
        target_movie_id = str(matched_movie["_id"]) if matched_movie else None
        shows = get_shows(movie_id=target_movie_id, city=city)
        if shows:
            suggested_shows = shows[:5]
            if matched_movie:
                reply = f"Here are the confirmed showtimes for **{matched_movie['title']}** in {city or 'all cities'}. You can click directly on any showtime to choose your seats!"
            else:
                reply = f"Here are today's available showtimes in {city or 'your city'}:"
        else:
            reply = f"Currently, no live showtimes are scheduled matching your query for {city or 'the selected location'}. Please browse our Now Showing section or select another city."

    elif is_similar_query and matched_movie:
        m_genres = matched_movie.get("genres") or []
        candidates = [
            m for m in all_movies
            if m["_id"] != matched_movie["_id"] and any(g in (m.get("genres") or []) for g in m_genres)
        ]
        candidates.sort(key=lambda x: float(x.get("rating") or 0), reverse=True)
        suggested_movies = [serialize_doc(c) for c in candidates[:4]]
        reply = f"If you enjoyed **{matched_movie['title']}**, you'll definitely love these high-caliber titles with similar storytelling and intensity:"

    elif mood_match:
        candidates = [
            m for m in all_movies
            if mood_match.lower() in [g.lower() for g in (m.get("genres") or [])]
        ]
        candidates.sort(key=lambda x: float(x.get("rating") or 0), reverse=True)
        suggested_movies = [serialize_doc(c) for c in candidates[:4]]
        reply = f"Here are the highest-rated **{mood_match}** movies currently featured on Cinepass. Each offers stellar performances and an unforgettable cinematic experience:"

    elif "tonight" in clean_msg or "recommend" in clean_msg or "watch" in clean_msg:
        trending = sorted(all_movies, key=lambda x: float(x.get("rating") or 0), reverse=True)
        suggested_movies = [serialize_doc(c) for c in trending[:4]]
        reply = "For an extraordinary movie night, here are top picks hand-selected from our catalog based on critics' acclaim and audience popularity:"

    else:
        # General response with top movies
        top_picks = sorted(all_movies, key=lambda x: float(x.get("rating") or 0), reverse=True)[:3]
        suggested_movies = [serialize_doc(c) for c in top_picks]
        reply = f"I've analyzed our cinema catalog. Here are standout recommendations currently featured on Cinepass. Feel free to ask about specific genres, actors, or showtimes!"

    # If LLM API key is present, enhance the natural language commentary while preserving the factual movie list
    if (Config.OPENROUTER_API_KEY or Config.GEMINI_API_KEY or Config.OPENAI_API_KEY) and suggested_movies:
        try:
            titles = [m.get("title") for m in suggested_movies]
            llm_reply = _enhance_with_llm(message, titles)
            if llm_reply:
                reply = llm_reply
        except Exception:
            pass

    return {
        "reply": reply,
        "suggested_movies": suggested_movies,
        "suggested_shows": suggested_shows,
    }


def _enhance_with_llm(user_message: str, recommended_titles: list[str]) -> Optional[str]:
    """Generates concise, charming AI response citing strictly the matched movies."""
    prompt = f"""You are CineBot, the premier cinema assistant for Cinepass.
The user asked: "{user_message}"
The platform matched these real catalog movies: {', '.join(recommended_titles)}.

Provide a warm, enthusiastic, 2-to-3 sentence cinema recommendation explaining why these specific movies are great choices.
Rules:
- Strictly mention only movies from the provided list.
- Do not invent fictitious movies, showtimes, or ticket pricing.
- Keep tone sophisticated and engaging like a cinema concierge."""

    if Config.SUMMARY_PROVIDER == "gemini" and Config.GEMINI_API_KEY:
        from google import genai
        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        resp = client.models.generate_content(model=Config.GEMINI_MODEL, contents=prompt)
        return resp.text.strip()
    elif Config.OPENAI_API_KEY:
        from openai import OpenAI
        client = OpenAI(api_key=Config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        return resp.choices[0].message.content.strip()
    elif Config.OPENROUTER_API_KEY:
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=Config.OPENROUTER_API_KEY)
        resp = client.chat.completions.create(
            model=Config.OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        return resp.choices[0].message.content.strip()
    return None
