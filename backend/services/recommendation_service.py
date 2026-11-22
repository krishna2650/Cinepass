from __future__ import annotations

import json
import re



from config import Config


class RecommendationError(RuntimeError):
    pass


def _json_object(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise RecommendationError("The recommendation service returned an invalid result.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RecommendationError("The recommendation service returned an invalid result.") from exc
    if not isinstance(data, dict):
        raise RecommendationError("The recommendation service returned an invalid result.")
    return data


def _clean(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", value if isinstance(value, str) else "").strip()[:limit]


def _validate(data: dict) -> list[dict[str, str]]:
    recommendations = data.get("recommendations")
    if not isinstance(recommendations, list) or len(recommendations) != 3:
        raise RecommendationError("The recommendation service returned an invalid result.")
    validated = []
    for item in recommendations:
        if not isinstance(item, dict):
            raise RecommendationError("The recommendation service returned an invalid result.")
        result = {
            "title": _clean(item.get("title"), 120),
            "year": _clean(item.get("year"), 20) or "Unknown",
            "genre": _clean(item.get("genre"), 80) or "Not available",
            "language": _clean(item.get("language"), 80) or "Not available",
            "reason": _clean(item.get("reason"), 220),
        }
        if not result["title"] or not result["reason"]:
            raise RecommendationError("The recommendation service returned an invalid result.")
        validated.append(result)
    return validated


def get_recommendations(preferences: dict[str, str]) -> list[dict[str, str]]:
    if not Config.OPENROUTER_API_KEY:
        raise RecommendationError("AI recommendations are unavailable. Configure the OpenRouter API key.")
    if not Config.OPENROUTER_MODEL:
        raise RecommendationError("AI recommendations are unavailable. Configure an OpenRouter model.")
    prompt = f"""You are a movie recommendation assistant.

Recommend exactly three real movies based on the user's preferences.
Mood: {preferences['mood']}
Preferred genre: {preferences['genre']}
Preferred language: {preferences['language']}
Additional request: {preferences['request']}

Return only valid JSON in this exact format:
{{"recommendations":[{{"title":"Movie title","year":"Release year or Unknown","genre":"Main genre","language":"Main language","reason":"A short reason explaining why the movie matches"}}]}}

Rules: return exactly three recommendations; recommend only real movies; keep each reason below 35 words; do not include markdown or text outside the JSON object."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=Config.OPENROUTER_API_KEY)
        response = client.chat.completions.create(
            model=Config.OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=650,
            response_format={"type": "json_object"},
            extra_headers={"HTTP-Referer": Config.APP_URL, "X-Title": Config.APP_NAME},
            timeout=Config.AI_TIMEOUT_SECONDS,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        raise RecommendationError("The recommendation service is currently unavailable.") from exc
    return _validate(_json_object(content))
