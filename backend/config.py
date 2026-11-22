import os
from pathlib import Path

from dotenv import load_dotenv

# Load from .env in the backend folder or project root
_env_path = Path(__file__).resolve().parent / ".env"
if not _env_path.exists():
    _env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


def as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_NAME = os.getenv("APP_NAME", "Cinepass")
    APP_URL = os.getenv("APP_URL", "http://127.0.0.1:5000")
    SECRET_KEY = os.getenv("SECRET_KEY", "cinepass-super-secret-key-production-grade-2026")
    DEBUG = as_bool(os.getenv("FLASK_DEBUG"), False)

    # MongoDB Configuration
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "cinepass_db")
    MONGODB_TIMEOUT_MS = int(os.getenv("MONGODB_TIMEOUT_MS", "3000"))
    # Fallback to embedded document store if MongoDB is offline / unreachable
    ALLOW_FALLBACK_DB = as_bool(os.getenv("ALLOW_FALLBACK_DB", "true"), True)

    # Razorpay Payment Configuration (Test Mode default)
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_cinepass2026key")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "cinepass_test_secret_99887766")
    CONVENIENCE_FEE_PER_TICKET = float(os.getenv("CONVENIENCE_FEE_PER_TICKET", "30.0"))
    GST_PERCENTAGE = float(os.getenv("GST_PERCENTAGE", "18.0"))

    # Booking & Seat Lock Settings
    SEAT_LOCK_TIMEOUT_SECONDS = int(os.getenv("SEAT_LOCK_TIMEOUT_SECONDS", "480"))  # 8 minutes

    # AI Configurations
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto").strip()
    SUMMARY_OPENROUTER_MODEL = os.getenv("SUMMARY_OPENROUTER_MODEL", "google/gemini-2.5-flash-lite").strip()

    SUMMARY_PROVIDER = os.getenv("SUMMARY_PROVIDER", "gemini").strip().lower()
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    # Admin Account
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@cinepass.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "CinePass@Admin2026")

    # Scraper & Request timeouts
    REQUEST_TIMEOUT_SECONDS = 12
    AI_TIMEOUT_SECONDS = 30
    HOMEPAGE_MOVIE_LIMIT = 30

    @classmethod
    def validate(cls) -> None:
        if cls.SUMMARY_PROVIDER not in {"gemini", "openai", "openrouter"}:
            cls.SUMMARY_PROVIDER = "gemini"
