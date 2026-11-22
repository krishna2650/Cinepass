from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional

from bson import ObjectId
from flask import g, jsonify, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import DatabaseUnavailable, get_users_collection, get_watchlists_collection
from utils.serializers import serialize_doc


class AuthError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(Config.SECRET_KEY, salt="cinepass-user-auth-salt")


def generate_auth_token(user_id: str, role: str) -> str:
    s = _get_serializer()
    return s.dumps({"user_id": user_id, "role": role})


def verify_auth_token(token: str, max_age: int = 86400 * 14) -> Optional[dict[str, Any]]:
    """Verifies a JWT/itsdangerous token with 14-day validity."""
    s = _get_serializer()
    try:
        data = s.loads(token, max_age=max_age)
        return data
    except (SignatureExpired, BadSignature):
        return None


def get_current_user() -> Optional[dict[str, Any]]:
    """Extracts user from Authorization header or session."""
    user_id = None

    # Check Authorization header (Bearer <token>)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        payload = verify_auth_token(token)
        if payload:
            user_id = payload.get("user_id")

    # Fallback to session
    if not user_id and "user_id" in session:
        user_id = session.get("user_id")

    if not user_id:
        return None

    try:
        users = get_users_collection()
        user = users.find_one({"_id": ObjectId(user_id)})
        if user:
            return serialize_doc(user)
    except Exception:
        pass
    return None


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "message": "Authentication required. Please log in."}), 401
        g.user = user
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "message": "Authentication required. Please log in."}), 401
        if user.get("role") != "admin":
            return jsonify({"success": False, "message": "Administrative privileges required."}), 403
        g.user = user
        return f(*args, **kwargs)
    return decorated_function


def register_user(data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()

    if not name or len(name) < 2:
        raise AuthError("Please provide a valid full name.")
    if not email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        raise AuthError("Please provide a valid email address.")
    if not password or len(password) < 6:
        raise AuthError("Password must be at least 6 characters long.")

    users = get_users_collection()
    existing = users.find_one({"email": email})
    if existing:
        raise AuthError("An account with this email already exists.")

    password_hash = generate_password_hash(password, method="pbkdf2:sha256")
    user_doc = {
        "name": name,
        "email": email,
        "password_hash": password_hash,
        "phone": phone,
        "role": "user",
        "preferences": {
            "favorite_genres": data.get("favorite_genres") or [],
            "preferred_city": data.get("preferred_city") or "Mumbai",
        },
        "created_at": _now(),
        "updated_at": _now(),
    }

    result = users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    token = generate_auth_token(str(result.inserted_id), "user")

    serialized = serialize_doc(user_doc)
    serialized.pop("password_hash", None)
    return {"user": serialized, "token": token}


def authenticate_user(email: str, password: str) -> dict[str, Any]:
    email = (email or "").strip().lower()
    if not email or not password:
        raise AuthError("Email and password are required.")

    users = get_users_collection()
    user = users.find_one({"email": email})
    if not user:
        raise AuthError("Invalid email or password.")

    if not check_password_hash(user.get("password_hash", ""), password):
        raise AuthError("Invalid email or password.")

    user_id = str(user["_id"])
    role = user.get("role", "user")
    token = generate_auth_token(user_id, role)

    serialized = serialize_doc(user)
    serialized.pop("password_hash", None)
    return {"user": serialized, "token": token}


def update_profile(user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    users = get_users_collection()
    update_data: dict[str, Any] = {"updated_at": _now()}

    if "name" in updates:
        name = updates["name"].strip()
        if len(name) >= 2:
            update_data["name"] = name
    if "phone" in updates:
        update_data["phone"] = updates["phone"].strip()
    if "preferences" in updates and isinstance(updates["preferences"], dict):
        update_data["preferences"] = updates["preferences"]

    users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    updated = users.find_one({"_id": ObjectId(user_id)})
    serialized = serialize_doc(updated)
    if serialized:
        serialized.pop("password_hash", None)
    return serialized


def change_password(user_id: str, current_password: str, new_password: str) -> bool:
    if not new_password or len(new_password) < 6:
        raise AuthError("New password must be at least 6 characters long.")

    users = get_users_collection()
    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise AuthError("User not found.")

    if not check_password_hash(user.get("password_hash", ""), current_password):
        raise AuthError("Current password is incorrect.")

    new_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
    users.update_one({"_id": ObjectId(user_id)}, {"$set": {"password_hash": new_hash, "updated_at": _now()}})
    return True


def ensure_admin_account():
    """Seeds or updates the default admin account on startup."""
    try:
        users = get_users_collection()
        admin_email = Config.ADMIN_EMAIL.lower()
        admin_user = users.find_one({"email": admin_email})
        admin_hash = generate_password_hash(Config.ADMIN_PASSWORD, method="pbkdf2:sha256")

        if not admin_user:
            users.insert_one({
                "name": "Cinepass Administrator",
                "email": admin_email,
                "password_hash": admin_hash,
                "phone": "+91 9999999999",
                "role": "admin",
                "preferences": {"favorite_genres": [], "preferred_city": "Mumbai"},
                "created_at": _now(),
                "updated_at": _now(),
            })
        else:
            users.update_one(
                {"email": admin_email},
                {"$set": {"role": "admin", "password_hash": admin_hash, "updated_at": _now()}}
            )
    except Exception:
        pass


def toggle_watchlist(user_id: str, movie_id: str) -> dict[str, Any]:
    watchlists = get_watchlists_collection()
    existing = watchlists.find_one({"user_id": user_id, "movie_id": movie_id})
    if existing:
        watchlists.delete_one({"_id": existing["_id"]})
        return {"in_watchlist": False, "message": "Removed from watchlist."}
    else:
        watchlists.insert_one({
            "user_id": user_id,
            "movie_id": movie_id,
            "added_at": _now(),
        })
        return {"in_watchlist": True, "message": "Added to watchlist."}


def get_user_watchlist(user_id: str) -> list[str]:
    watchlists = get_watchlists_collection()
    items = watchlists.find({"user_id": user_id})
    return [str(item["movie_id"]) for item in items]
