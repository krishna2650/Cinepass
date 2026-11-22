from __future__ import annotations

import re
import time
from urllib.parse import quote

try:
    import requests
    from bs4 import BeautifulSoup
    RequestException = requests.RequestException
except ImportError:
    requests = None
    BeautifulSoup = None
    RequestException = Exception


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "CineSuggestAI/1.0 (educational project)"}
CITATION_PATTERN = re.compile(r"\[\s*(?:\d+|[a-z]+)\s*\]", re.IGNORECASE)
LANGUAGE_NAMES = (
    "English", "Hindi", "Telugu", "Tamil", "Malayalam", "Kannada", "Marathi",
    "Bengali", "Punjabi", "Gujarati", "Urdu", "Spanish", "French", "German",
    "Italian", "Japanese", "Korean", "Mandarin", "Cantonese", "Arabic",
)
GENRE_PATTERNS = (
    ("Science Fiction", r"\b(?:science[ -]fiction|sci-fi)\b"),
    ("Action", r"\baction\b"),
    ("Adventure", r"\badventure\b"),
    ("Comedy", r"\bcomed(?:y|ic)\b"),
    ("Drama", r"\bdrama(?:tic)?\b"),
    ("Romance", r"\bromance|romantic\b"),
    ("Fantasy", r"\bfantasy\b"),
    ("Thriller", r"\bthriller\b"),
    ("Horror", r"\bhorror\b"),
    ("Animation", r"\banimat(?:ed|ion)\b"),
    ("Family", r"\bfamily film\b"),
    ("Crime", r"\bcrime\b"),
    ("Biography", r"\bbiograph(?:y|ical)\b"),
    ("Musical", r"\bmusical\b"),
    ("Sport", r"\bsports? film\b"),
)


class ScraperError(RuntimeError):
    pass


def _clean(value: str) -> str:
    value = CITATION_PATTERN.sub("", value or "")
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+\)", ")", value)
    return re.sub(r"\s+", " ", value).strip()


def _first_year(value: str) -> str:
    match = re.search(r"\b(18|19|20)\d{2}\b", value or "")
    return match.group(0) if match else "Not available"


def _table_value(table, labels: tuple[str, ...]) -> str:
    for row in table.find_all("tr"):
        heading, cell = row.find("th"), row.find("td")
        if heading and cell and _clean(heading.get_text(" ", strip=True)).casefold() in labels:
            for reference in cell.select("sup.reference"):
                reference.decompose()
            return _clean(cell.get_text(" ", strip=True))
    return "Not available"


def _table_list(table, labels: tuple[str, ...], limit: int = 5) -> list[str]:
    for row in table.find_all("tr"):
        heading, cell = row.find("th"), row.find("td")
        if heading and cell and _clean(heading.get_text(" ", strip=True)).casefold() in labels:
            values = [_clean(link.get_text(" ", strip=True)) for link in cell.find_all("a")]
            values = list(dict.fromkeys(value for value in values if value and not value.startswith("[")))
            return values[:limit] or ["Not available"]
    return ["Not available"]


def _language_value(table) -> str:
    labels = ("language", "languages", "original language")
    linked = _table_list(table, labels, limit=8)
    if linked != ["Not available"]:
        return ", ".join(linked)
    return _normalize_languages(_table_value(table, labels))


def _normalize_languages(value: str) -> str:
    value = _clean(value)
    if not value or value == "Not available":
        return "Not available"
    found = [name for name in LANGUAGE_NAMES if re.search(rf"\b{re.escape(name)}\b", value, re.IGNORECASE)]
    return ", ".join(dict.fromkeys(found)) if found else value


def _normalize_duration(value: str) -> str:
    value = _clean(value)
    return re.sub(r"(?<=\))\s+(?=\d+\s*(?:minutes?|hours?)\b)", "; ", value, flags=re.IGNORECASE)


def _infer_genres(description: str) -> list[str]:
    return [name for name, pattern in GENRE_PATTERNS if re.search(pattern, description, re.IGNORECASE)][:4]


def _description(soup: BeautifulSoup) -> str:
    content = soup.select_one(".mw-parser-output") or soup
    paragraphs = []
    for paragraph in content.find_all("p", recursive=False):
        for reference in paragraph.select("sup.reference"):
            reference.decompose()
        text = _clean(paragraph.get_text(" ", strip=True))
        if len(text) > 80:
            paragraphs.append(text)
        if len(" ".join(paragraphs)) >= 500:
            break
    return (" ".join(paragraphs)[:700]) or "Not available"


def _find_page_title(query: str, timeout: int) -> str | None:
    response = requests.get(
        WIKIPEDIA_API,
        params={"action": "query", "list": "search", "srsearch": f"{query} film", "format": "json", "srlimit": 8},
        headers=HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    results = response.json().get("query", {}).get("search", [])
    if not results:
        return None
    query_key = query.casefold()

    def relevance(item: dict) -> tuple[int, int]:
        title = item.get("title", "").casefold()
        snippet = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text(" ").casefold()
        score = 0
        if title.startswith(query_key) and "film" in title:
            score += 100
        if title == query_key and "film" in snippet:
            score += 90
        elif title == query_key:
            score += 70
        if query_key in title:
            score += 30
        if "film" in snippet:
            score += 10
        return score, -len(title)

    return max(results, key=relevance).get("title")


def fetch_movie_poster(query: str, timeout: int = 12) -> tuple[str, str]:
    """Return a Wikipedia thumbnail and source URL for a movie title."""
    try:
        title = _find_page_title(query, timeout)
        if not title:
            return "", ""
        time.sleep(0.45)
        response = requests.get(
            WIKIPEDIA_API,
            params={
                "action": "query", "titles": title, "prop": "pageimages",
                "piprop": "thumbnail|original", "pithumbsize": 700, "format": "json",
            },
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        poster_url = page.get("thumbnail", {}).get("source") or page.get("original", {}).get("source") or ""
        if not poster_url:
            time.sleep(0.45)
            article = requests.get(
                WIKIPEDIA_API,
                params={"action": "parse", "page": title, "prop": "text", "format": "json"},
                headers=HEADERS,
                timeout=timeout,
            )
            article.raise_for_status()
            html = article.json().get("parse", {}).get("text", {}).get("*", "")
            image = BeautifulSoup(html, "html.parser").select_one("table.infobox img")
            poster_url = image.get("src", "") if image else ""
            if poster_url.startswith("//"):
                poster_url = f"https:{poster_url}"
        source_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        return poster_url, source_url
    except (RequestException, ValueError) as exc:
        raise ScraperError("Movie poster could not be collected from Wikipedia.") from exc


def scrape_movie(query: str, timeout: int = 12) -> dict[str, object] | None:
    """Scrape a public Wikipedia movie article without accepting an arbitrary URL."""
    try:
        title = _find_page_title(query, timeout)
        if not title:
            return None
        response = requests.get(
            WIKIPEDIA_API,
            params={"action": "parse", "page": title, "prop": "text", "format": "json"},
            headers=HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        html = response.json().get("parse", {}).get("text", {}).get("*")
        if not html:
            return None
    except (RequestException, ValueError) as exc:
        raise ScraperError("Movie information could not be collected from the web.") from exc

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.infobox")
    if table is None:
        return None
    image = table.find("img")
    poster_url = image.get("src", "") if image else ""
    if poster_url.startswith("//"):
        poster_url = f"https:{poster_url}"
    title_text = _clean(title)
    released = _table_value(table, ("release date", "released"))
    genre_value = _table_value(table, ("genre", "genres"))
    description = _description(soup)
    genres = [_clean(part) for part in re.split(r"[,/;]", genre_value) if _clean(part)] if genre_value != "Not available" else _infer_genres(description)
    return {
        "title": title_text,
        "year": _first_year(released),
        "genres": genres[:4] or ["Not available"],
        "language": _language_value(table),
        "duration": _normalize_duration(_table_value(table, ("running time", "runtime"))),
        "director": _table_value(table, ("directed by", "director")),
        "cast": _table_list(table, ("starring", "cast")),
        "description": description,
        "poster_url": poster_url,
        "rating": None,
        "source_url": f"https://en.wikipedia.org/wiki/{quote(title_text.replace(' ', '_'))}",
        "data_source": "scraped",
    }


def normalize_movie_data(movie: dict) -> dict:
    """Clean both newly scraped movies and older documents already cached in MongoDB."""
    cleaned = dict(movie)
    for field in ("title", "year", "language", "duration", "director", "description"):
        if isinstance(cleaned.get(field), str):
            cleaned[field] = _clean(cleaned[field])
    cleaned["language"] = _normalize_languages(cleaned.get("language", ""))
    cleaned["duration"] = _normalize_duration(cleaned.get("duration", ""))
    if isinstance(cleaned.get("cast"), list):
        cleaned["cast"] = [_clean(value) for value in cleaned["cast"] if _clean(value)][:5]
    genres = [_clean(value) for value in cleaned.get("genres", []) if _clean(value) and _clean(value) != "Not available"]
    cleaned["genres"] = genres[:4] or _infer_genres(cleaned.get("description", "")) or ["Not available"]
    return cleaned
