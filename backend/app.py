from __future__ import annotations

from typing import Any
from flask import Flask, g, jsonify, render_template, request, session

from config import Config
from database import DatabaseUnavailable, initialize_database
from services.admin_service import (
    admin_add_cinema,
    admin_add_coupon,
    admin_add_movie,
    admin_delete_movie,
    admin_schedule_show,
    admin_update_movie,
    get_platform_statistics,
)
from services.auth_service import (
    AuthError,
    admin_required,
    authenticate_user,
    change_password,
    ensure_admin_account,
    get_current_user,
    get_user_watchlist,
    login_required,
    register_user,
    toggle_watchlist,
    update_profile,
)
from services.booking_service import (
    BookingError,
    calculate_booking_breakdown,
    get_seat_layout_for_show,
    list_cinema_snacks,
    lock_seats,
    unlock_seats,
    validate_coupon,
)
from services.cinema_service import (
    get_cinema,
    get_screens_for_cinema,
    get_show_by_id,
    get_shows,
    list_cities,
    list_cinemas,
)
from services.cinebot_service import ask_cinebot
from services.movie_scraper import ScraperError
from services.movie_service import (
    discover_movies,
    get_homepage_curated,
    get_movie,
    get_search_suggestions,
    get_similar_movies,
    list_movies,
    save_summary,
    search_or_scrape_movie,
)
from services.payment_service import (
    PaymentError,
    cancel_booking,
    confirm_booking_payment,
    create_payment_order,
    handle_failed_payment,
)
from services.personalization_service import get_personalized_recommendations
from services.review_service import (
    ReviewError,
    add_or_update_review,
    delete_review,
    list_movie_reviews,
    report_review,
)
from services.summary_service import SummaryError, generate_summary
from services.ticket_service import get_ticket_by_reference, validate_ticket
from utils.serializers import serialize_doc
from utils.validators import (
    ValidationError,
    validate_movie_query,
    validate_recommendation_input,
    validate_summary_input,
)


def error(message: str, status: int = 400):
    return jsonify({"success": False, "message": message}), status


def json_body() -> dict[str, Any]:
    if not request.is_json:
        raise ValidationError("Send a JSON request.")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Send a valid JSON object.")
    return payload


def create_app() -> Flask:
    Config.validate()
    app = Flask(__name__)
    app.config.from_object(Config)
    initialize_database(app)
    ensure_admin_account()

    # --- HTML Page Routes ---
    @app.get("/")
    def index():
        return render_template("index.html", app_name=app.config["APP_NAME"])

    @app.get("/ticket/<reference>")
    def ticket_page(reference):
        ticket = get_ticket_by_reference(reference)
        return render_template("index.html", app_name=app.config["APP_NAME"], target_ticket=ticket)

    # --- Movie Routes ---
    @app.get("/api/movies")
    def movies():
        try:
            limit = max(1, min(int(request.args.get("limit", app.config["HOMEPAGE_MOVIE_LIMIT"])), 100))
        except ValueError:
            limit = app.config["HOMEPAGE_MOVIE_LIMIT"]
        try:
            return jsonify({"success": True, "movies": list_movies(limit)})
        except DatabaseUnavailable:
            return error("The movie database is currently unavailable.", 503)

    @app.get("/api/movies/homepage")
    def homepage_data():
        try:
            return jsonify({"success": True, "data": get_homepage_curated()})
        except DatabaseUnavailable:
            return error("The movie database is currently unavailable.", 503)

    @app.get("/api/movies/discover")
    def discover():
        try:
            query = request.args.get("query")
            genre = request.args.get("genre")
            language = request.args.get("language")
            min_rating = float(request.args.get("min_rating", 0.0))
            year = request.args.get("year")
            sort_by = request.args.get("sort_by", "rating_desc")
            category = request.args.get("category")
            page = max(1, int(request.args.get("page", 1)))
            limit = max(1, min(int(request.args.get("limit", 24)), 60))

            res = discover_movies(
                query=query,
                genre=genre,
                language=language,
                min_rating=min_rating,
                year=year,
                sort_by=sort_by,
                category=category,
                page=page,
                limit=limit,
            )
            return jsonify({"success": True, **res})
        except Exception as exc:
            return error(str(exc), 500)

    @app.get("/api/movies/suggestions")
    def suggestions():
        q = request.args.get("q", "")
        return jsonify({"success": True, "suggestions": get_search_suggestions(q)})

    @app.get("/api/movies/<movie_id>")
    def movie_details(movie_id):
        m = get_movie(movie_id)
        if not m:
            return error("Movie not found.", 404)
        similar = get_similar_movies(movie_id, limit=6)
        return jsonify({"success": True, "movie": m, "similar_movies": similar})

    @app.post("/api/search")
    def search():
        try:
            query = validate_movie_query(json_body().get("query"))
            movie, source = search_or_scrape_movie(query, app.config["REQUEST_TIMEOUT_SECONDS"])
            if not movie:
                return error("Movie information could not be found.", 404)
            return jsonify({"success": True, "movie": movie, "source": source})
        except ValidationError as exc:
            return error(str(exc))
        except DatabaseUnavailable:
            return error("The movie database is currently unavailable.", 503)
        except ScraperError:
            return error("Movie information could not be collected from the web.", 502)

    @app.post("/api/summary")
    def summary():
        try:
            movie_id, regenerate = validate_summary_input(json_body())
            movie = get_movie(movie_id)
            if not movie:
                return error("Movie information could not be found.", 404)
            if movie.get("ai_summary") and not regenerate:
                result = {
                    "title": movie["title"],
                    "summary": movie["ai_summary"],
                    "genre": movie.get("summary_genre") or "Not available",
                    "mood": movie.get("summary_mood") or "Not available",
                    "suitable_for": movie.get("summary_suitable_for") or "Not available",
                }
                return jsonify({"success": True, "result": result, "provider": movie.get("summary_provider"), "source": "database"})
            result, provider = generate_summary(movie)
            save_summary(movie_id, result, provider)
            return jsonify({"success": True, "result": result, "provider": provider, "source": "generated"})
        except ValidationError as exc:
            return error(str(exc))
        except DatabaseUnavailable:
            return error("The movie database is currently unavailable.", 503)
        except SummaryError as exc:
            return error(str(exc), 503)

    # --- Cinema & Showtime Routes ---
    @app.get("/api/cinemas/cities")
    def cities():
        return jsonify({"success": True, "cities": list_cities()})

    @app.get("/api/cinemas")
    def cinemas():
        city = request.args.get("city")
        search_q = request.args.get("search")
        amenity = request.args.get("amenity")
        return jsonify({"success": True, "cinemas": list_cinemas(city=city, search=search_q, amenity=amenity)})

    @app.get("/api/cinemas/<cinema_id>")
    def cinema_detail(cinema_id):
        c = get_cinema(cinema_id)
        if not c:
            return error("Cinema not found.", 404)
        screens = get_screens_for_cinema(cinema_id)
        return jsonify({"success": True, "cinema": c, "screens": screens})

    @app.get("/api/cinemas/<cinema_id>/snacks")
    def snacks(cinema_id):
        return jsonify({"success": True, "snacks": list_cinema_snacks(cinema_id)})

    @app.get("/api/shows")
    def shows():
        movie_id = request.args.get("movie_id")
        cinema_id = request.args.get("cinema_id")
        city = request.args.get("city")
        date = request.args.get("date")
        shows_list = get_shows(movie_id=movie_id, cinema_id=cinema_id, city=city, date=date)
        return jsonify({"success": True, "shows": shows_list})

    @app.get("/api/shows/<show_id>")
    def show_detail(show_id):
        s = get_show_by_id(show_id)
        if not s:
            return error("Showtime not found.", 404)
        return jsonify({"success": True, "show": s})

    # --- Interactive Seat Selection & Locking Routes ---
    @app.get("/api/bookings/layout/<show_id>")
    def seat_layout(show_id):
        try:
            user = get_current_user()
            user_id = user["id"] if user else None
            session_id = request.headers.get("X-Session-ID") or request.cookies.get("session_id")
            layout = get_seat_layout_for_show(show_id, user_id=user_id, session_id=session_id)
            return jsonify({"success": True, **layout})
        except BookingError as exc:
            return error(str(exc), 404)
        except Exception as exc:
            return error(str(exc), 500)

    @app.post("/api/bookings/lock-seats")
    def lock_seat_endpoint():
        try:
            body = json_body()
            show_id = body.get("show_id")
            seat_ids = body.get("seat_ids", [])
            user = get_current_user()
            user_id = user["id"] if user else None
            session_id = request.headers.get("X-Session-ID") or request.cookies.get("session_id")

            res = lock_seats(show_id, seat_ids, user_id=user_id, session_id=session_id)
            return jsonify(res)
        except BookingError as exc:
            return error(str(exc), 409)
        except Exception as exc:
            return error(str(exc), 500)

    @app.post("/api/bookings/unlock-seats")
    def unlock_seat_endpoint():
        try:
            body = json_body()
            show_id = body.get("show_id")
            seat_ids = body.get("seat_ids", [])
            user = get_current_user()
            user_id = user["id"] if user else None
            session_id = request.headers.get("X-Session-ID") or request.cookies.get("session_id")

            unlock_seats(show_id, seat_ids, user_id=user_id, session_id=session_id)
            return jsonify({"success": True, "message": "Seats unlocked."})
        except Exception as exc:
            return error(str(exc), 500)

    @app.post("/api/bookings/calculate")
    def calculate_price():
        try:
            body = json_body()
            show_id = body.get("show_id")
            seat_ids = body.get("seat_ids", [])
            snacks_list = body.get("snacks", [])
            coupon_code = body.get("coupon_code")
            user = get_current_user()
            user_id = user["id"] if user else None

            breakdown = calculate_booking_breakdown(
                show_id=show_id,
                seat_ids=seat_ids,
                snacks=snacks_list,
                coupon_code=coupon_code,
                user_id=user_id,
            )
            return jsonify({"success": True, "breakdown": breakdown})
        except BookingError as exc:
            return error(str(exc), 400)
        except Exception as exc:
            return error(str(exc), 500)

    @app.post("/api/coupons/validate")
    def coupon_validation():
        try:
            body = json_body()
            code = body.get("code")
            subtotal = float(body.get("subtotal", 0.0))
            user = get_current_user()
            user_id = user["id"] if user else None

            res = validate_coupon(code, subtotal, user_id)
            return jsonify({"success": True, **res})
        except Exception as exc:
            return error(str(exc), 500)

    # --- Payment Gateway Routes ---
    @app.post("/api/payments/create-order")
    @login_required
    def payment_order():
        try:
            body = json_body()
            show_id = body.get("show_id")
            seat_ids = body.get("seat_ids", [])
            snacks_list = body.get("snacks", [])
            coupon_code = body.get("coupon_code")
            session_id = request.headers.get("X-Session-ID")

            order_data = create_payment_order(
                show_id=show_id,
                seat_ids=seat_ids,
                user=g.user,
                snacks=snacks_list,
                coupon_code=coupon_code,
                session_id=session_id,
            )
            return jsonify({"success": True, **order_data})
        except (BookingError, PaymentError) as exc:
            return error(str(exc), 400)
        except Exception as exc:
            return error(f"Failed to create payment order: {exc}", 500)

    @app.post("/api/payments/verify")
    def payment_verification():
        try:
            body = json_body()
            order_id = body.get("razorpay_order_id")
            payment_id = body.get("razorpay_payment_id")
            signature = body.get("razorpay_signature")
            bypass_sig = bool(body.get("simulate_success_for_test", False))

            res = confirm_booking_payment(
                order_id=order_id,
                payment_id=payment_id,
                signature=signature,
                bypass_signature_for_test=bypass_sig,
            )
            return jsonify(res)
        except PaymentError as exc:
            return error(str(exc), 400)
        except Exception as exc:
            return error(str(exc), 500)

    @app.post("/api/payments/failed")
    def payment_failed():
        try:
            body = json_body()
            order_id = body.get("order_id")
            reason = body.get("reason", "Payment failed or cancelled.")
            handle_failed_payment(order_id, reason)
            return jsonify({"success": True, "message": "Failed payment handled."})
        except Exception as exc:
            return error(str(exc), 500)

    # --- Digital Ticket & QR Code Validation Routes ---
    @app.get("/api/tickets/<reference>")
    def ticket_detail(reference):
        ticket = get_ticket_by_reference(reference)
        if not ticket:
            return error("Ticket not found.", 404)
        return jsonify({"success": True, "ticket": ticket})

    @app.get("/api/tickets/validate/<reference>")
    def ticket_verify(reference):
        """Public ticket authenticity verification endpoint."""
        val = validate_ticket(reference)
        status_code = 200 if val["valid"] else 400
        return jsonify(val), status_code

    # --- User Authentication & Profile Routes ---
    @app.post("/api/auth/register")
    def register():
        try:
            res = register_user(json_body())
            session["user_id"] = res["user"]["id"]
            return jsonify({"success": True, **res})
        except AuthError as exc:
            return error(str(exc), 400)

    @app.post("/api/auth/login")
    def login():
        try:
            body = json_body()
            res = authenticate_user(body.get("email"), body.get("password"))
            session["user_id"] = res["user"]["id"]
            return jsonify({"success": True, **res})
        except AuthError as exc:
            return error(str(exc), 401)

    @app.post("/api/auth/logout")
    def logout():
        session.pop("user_id", None)
        return jsonify({"success": True, "message": "Logged out successfully."})

    @app.get("/api/auth/me")
    def current_user():
        u = get_current_user()
        if not u:
            return jsonify({"success": False, "user": None})
        return jsonify({"success": True, "user": u})

    @app.put("/api/auth/profile")
    @login_required
    def user_profile():
        try:
            updated = update_profile(g.user["id"], json_body())
            return jsonify({"success": True, "user": updated})
        except Exception as exc:
            return error(str(exc), 400)

    @app.put("/api/auth/password")
    @login_required
    def user_password():
        try:
            body = json_body()
            change_password(g.user["id"], body.get("current_password"), body.get("new_password"))
            return jsonify({"success": True, "message": "Password changed successfully."})
        except AuthError as exc:
            return error(str(exc), 400)

    @app.get("/api/auth/watchlist")
    @login_required
    def user_watchlist():
        movie_ids = get_user_watchlist(g.user["id"])
        movies_list = []
        for mid in movie_ids:
            m = get_movie(mid)
            if m:
                movies_list.append(m)
        return jsonify({"success": True, "watchlist": movies_list})

    @app.post("/api/auth/watchlist/<movie_id>")
    @login_required
    def watchlist_toggle(movie_id):
        res = toggle_watchlist(g.user["id"], movie_id)
        return jsonify({"success": True, **res})

    @app.get("/api/auth/bookings")
    @login_required
    def user_bookings():
        from database import get_bookings_collection
        coll = get_bookings_collection()
        bookings_cursor = coll.find({"user_id": g.user["id"]}).sort("created_at", -1)
        items = [serialize_doc(b) for b in bookings_cursor]
        return jsonify({"success": True, "bookings": items})

    @app.post("/api/bookings/<booking_id>/cancel")
    @login_required
    def booking_cancel(booking_id):
        try:
            res = cancel_booking(booking_id, g.user["id"])
            return jsonify(res)
        except (BookingError, PaymentError) as exc:
            return error(str(exc), 400)
        except Exception as exc:
            return error(str(exc), 500)

    # --- Reviews and Ratings Routes ---
    @app.get("/api/reviews/movie/<movie_id>")
    def reviews_get(movie_id):
        sort_by = request.args.get("sort_by", "newest")
        return jsonify({"success": True, **list_movie_reviews(movie_id, sort_by=sort_by)})

    @app.post("/api/reviews/movie/<movie_id>")
    @login_required
    def reviews_post(movie_id):
        try:
            body = json_body()
            rev = add_or_update_review(
                movie_id=movie_id,
                user_id=g.user["id"],
                user_name=g.user["name"],
                rating=float(body.get("rating", 5.0)),
                content=body.get("content", ""),
                title=body.get("title"),
            )
            return jsonify({"success": True, "review": rev})
        except ReviewError as exc:
            return error(str(exc), 400)
        except Exception as exc:
            return error(str(exc), 500)

    @app.delete("/api/reviews/<review_id>")
    @login_required
    def reviews_delete(review_id):
        try:
            is_admin = g.user.get("role") == "admin"
            delete_review(review_id, g.user["id"], is_admin=is_admin)
            return jsonify({"success": True, "message": "Review deleted."})
        except ReviewError as exc:
            return error(str(exc), 400)

    @app.post("/api/reviews/<review_id>/report")
    def reviews_report(review_id):
        report_review(review_id)
        return jsonify({"success": True, "message": "Review reported for moderation."})

    # --- AI CineBot & Personalized Recommendations Routes ---
    @app.post("/api/ai/cinebot")
    def ai_cinebot():
        try:
            body = json_body()
            message = body.get("message", "")
            city = body.get("city")
            genre = body.get("genre")
            language = body.get("language")
            res = ask_cinebot(message, city=city, genre=genre, language=language)
            return jsonify({"success": True, **res})
        except Exception as exc:
            return error(f"CineBot encountered an error: {exc}", 500)

    @app.get("/api/ai/personalized")
    def ai_personalized():
        user = get_current_user()
        user_id = user["id"] if user else None
        limit = max(1, min(int(request.args.get("limit", 8)), 20))
        recommendations = get_personalized_recommendations(user_id=user_id, limit=limit)
        return jsonify({"success": True, "recommendations": recommendations})

    # --- Admin Dashboard Routes ---
    @app.get("/api/admin/stats")
    @admin_required
    def admin_stats():
        return jsonify({"success": True, "stats": get_platform_statistics()})

    @app.get("/api/admin/movies")
    @admin_required
    def admin_movies_list():
        return jsonify({"success": True, "movies": list_movies(limit=100)})

    @app.post("/api/admin/movies")
    @admin_required
    def admin_movie_create():
        try:
            m = admin_add_movie(json_body())
            return jsonify({"success": True, "movie": m})
        except Exception as exc:
            return error(str(exc), 400)

    @app.put("/api/admin/movies/<movie_id>")
    @admin_required
    def admin_movie_edit(movie_id):
        try:
            m = admin_update_movie(movie_id, json_body())
            return jsonify({"success": True, "movie": m})
        except Exception as exc:
            return error(str(exc), 400)

    @app.delete("/api/admin/movies/<movie_id>")
    @admin_required
    def admin_movie_remove(movie_id):
        admin_delete_movie(movie_id)
        return jsonify({"success": True, "message": "Movie deleted."})

    @app.post("/api/admin/cinemas")
    @admin_required
    def admin_cinema_create():
        try:
            c = admin_add_cinema(json_body())
            return jsonify({"success": True, "cinema": c})
        except Exception as exc:
            return error(str(exc), 400)

    @app.post("/api/admin/shows")
    @admin_required
    def admin_show_create():
        try:
            s = admin_schedule_show(json_body())
            return jsonify({"success": True, "show": s})
        except Exception as exc:
            return error(str(exc), 400)

    @app.post("/api/admin/coupons")
    @admin_required
    def admin_coupon_create():
        try:
            cp = admin_add_coupon(json_body())
            return jsonify({"success": True, "coupon": cp})
        except Exception as exc:
            return error(str(exc), 400)

    @app.get("/api/admin/bookings")
    @admin_required
    def admin_bookings_list():
        from database import get_bookings_collection
        coll = get_bookings_collection()
        items = [serialize_doc(b) for b in coll.find().sort("created_at", -1).limit(50)]
        return jsonify({"success": True, "bookings": items})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=app.config["DEBUG"])
