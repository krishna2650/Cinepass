from __future__ import annotations

import hashlib
import hmac
import random
import sys
from pathlib import Path
import unittest

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from config import Config
from app import create_app
from database import (
    get_bookings_collection,
    get_cinemas_collection,
    get_movies_collection,
    get_seat_locks_collection,
    get_shows_collection,
)


class CinepassProductionTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Config.ALLOW_FALLBACK_DB = True
        cls.app = create_app()

    def setUp(self):
        self.client = self.app.test_client()
        # Clean up temporary seat locks so tests start from a clean slate
        get_seat_locks_collection().delete_many({})

    def test_01_homepage_and_movies_endpoint(self):
        """Tests that the homepage loads successfully and returns 200."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Cinepass", res.data)

        # Test /api/movies
        res_movies = self.client.get("/api/movies")
        self.assertEqual(res_movies.status_code, 200)
        data = res_movies.get_json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["movies"]), 0)

    def test_02_homepage_curated_data(self):
        """Tests homepage curated endpoint with hero, trending, now showing, genres."""
        res = self.client.get("/api/movies/homepage")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIn("hero_carousel", data)
        self.assertIn("now_showing", data)
        self.assertIn("trending", data)
        self.assertIn("available_genres", data)
        self.assertIn("available_languages", data)
        self.assertGreater(len(data["now_showing"]), 0)

    def test_03_movie_discovery_and_search_suggestions(self):
        """Tests search suggestions and discovery with filters."""
        # Search suggestions
        res = self.client.get("/api/movies/suggestions?q=Interstellar")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(any("Interstellar" in m["title"] for m in data["suggestions"]))

        # Discovery with genre filter
        res_disc = self.client.get("/api/movies/discover?genre=Action&min_rating=7.0")
        self.assertEqual(res_disc.status_code, 200)
        disc_data = res_disc.get_json()
        self.assertTrue(disc_data["success"])
        self.assertIn("movies", disc_data)

    def test_04_movie_details_and_similar_movies(self):
        """Tests movie details retrieval by ID along with similar movie recommendations."""
        movies_coll = get_movies_collection()
        movie = movies_coll.find_one({"title": "Interstellar"})
        self.assertIsNotNone(movie)
        movie_id = str(movie["_id"])

        res = self.client.get(f"/api/movies/{movie_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["movie"]["title"], "Interstellar")
        self.assertIn("similar_movies", data)

    def test_05_cinema_discovery_and_showtimes(self):
        """Tests city listing, cinema filtering, and showtimes lookup."""
        # Cities
        res_cities = self.client.get("/api/cinemas/cities")
        self.assertEqual(res_cities.status_code, 200)
        cities = res_cities.get_json()["cities"]
        self.assertTrue(any(c["name"] == "Mumbai" for c in cities))

        # Cinemas in Mumbai
        res_cinemas = self.client.get("/api/cinemas?city=Mumbai")
        self.assertEqual(res_cinemas.status_code, 200)
        cinemas = res_cinemas.get_json()["cinemas"]
        self.assertGreater(len(cinemas), 0)

        # Shows for Mumbai
        res_shows = self.client.get("/api/shows?city=Mumbai")
        self.assertEqual(res_shows.status_code, 200)
        shows = res_shows.get_json()["shows"]
        self.assertGreater(len(shows), 0)

    def test_06_user_auth_flow_register_login_profile(self):
        """Tests user registration, login, profile update, and authentication tokens."""
        rand_email = f"testuser_{random.randint(10000, 99999)}@cinepass.com"
        reg_payload = {
            "name": "Jane Tester",
            "email": rand_email,
            "password": "SecurePassword123",
            "phone": "+91 9876543210",
        }

        # 1. Register
        res_reg = self.client.post("/api/auth/register", json=reg_payload)
        self.assertEqual(res_reg.status_code, 200)
        reg_data = res_reg.get_json()
        self.assertTrue(reg_data["success"])
        self.assertIn("token", reg_data)
        token = reg_data["token"]

        # 2. Login
        res_login = self.client.post("/api/auth/login", json={
            "email": rand_email,
            "password": "SecurePassword123",
        })
        self.assertEqual(res_login.status_code, 200)
        login_data = res_login.get_json()
        self.assertTrue(login_data["success"])

        # 3. Profile update
        res_prof = self.client.put(
            "/api/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Jane Updated", "phone": "+91 9999911111"},
        )
        self.assertEqual(res_prof.status_code, 200)
        self.assertEqual(res_prof.get_json()["user"]["name"], "Jane Updated")

        # 4. Watchlist toggle
        movie = get_movies_collection().find_one()
        movie_id = str(movie["_id"])
        res_wl = self.client.post(
            f"/api/auth/watchlist/{movie_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res_wl.status_code, 200)
        self.assertTrue(res_wl.get_json()["in_watchlist"])

    def test_07_interactive_seat_selection_and_atomic_locking(self):
        """Tests seat layout loading, atomic seat locking, conflict detection, and unlock."""
        shows_coll = get_shows_collection()
        show = shows_coll.find_one()
        self.assertIsNotNone(show)
        show_id = str(show["_id"])

        # 1. Get layout
        res_layout = self.client.get(f"/api/bookings/layout/{show_id}")
        self.assertEqual(res_layout.status_code, 200)
        layout = res_layout.get_json()
        self.assertTrue(layout["success"])
        self.assertIn("sections", layout)

        test_seat = f"A{random.randint(1, 10)}"

        # 2. Lock seat
        client_a = self.app.test_client()
        lock_res = client_a.post(
            "/api/bookings/lock-seats",
            headers={"X-Session-ID": "test-session-alpha"},
            json={"show_id": show_id, "seat_ids": [test_seat]},
        )
        self.assertEqual(lock_res.status_code, 200)
        self.assertTrue(lock_res.get_json()["success"])

        # 3. Conflict Detection: Another customer trying to lock the same seat must be rejected with 409
        client_b = self.app.test_client()
        conflict_res = client_b.post(
            "/api/bookings/lock-seats",
            headers={"X-Session-ID": "test-session-beta"},
            json={"show_id": show_id, "seat_ids": [test_seat]},
        )
        self.assertEqual(conflict_res.status_code, 409)
        self.assertIn("locked by another customer", conflict_res.get_json()["message"])

        # 4. Release seats
        unlock_res = client_a.post(
            "/api/bookings/unlock-seats",
            headers={"X-Session-ID": "test-session-alpha"},
            json={"show_id": show_id, "seat_ids": [test_seat]},
        )
        self.assertEqual(unlock_res.status_code, 200)

    def test_08_server_calculated_pricing_and_coupons(self):
        """Tests that payment amounts are calculated strictly on the backend, verifying fees, GST, and coupons."""
        show = get_shows_collection().find_one()
        show_id = str(show["_id"])

        # Coupon validation
        res_cp = self.client.post("/api/coupons/validate", json={"code": "CINEPASS20", "subtotal": 500.0})
        self.assertEqual(res_cp.status_code, 200)
        self.assertTrue(res_cp.get_json()["valid"])
        self.assertEqual(res_cp.get_json()["discount"], 100.0)

        # Price calculation endpoint
        calc_res = self.client.post("/api/bookings/calculate", json={
            "show_id": show_id,
            "seat_ids": ["C1", "C2"],  # 2 Platinum seats
            "snacks": [{"id": "snk-1", "quantity": 1}],  # Popcorn ₹280
            "coupon_code": "CINEPASS20",
        })
        self.assertEqual(calc_res.status_code, 200)
        b = calc_res.get_json()["breakdown"]
        self.assertEqual(b["num_tickets"], 2)
        self.assertEqual(b["convenience_fee"], 60.0)  # ₹30 * 2
        self.assertEqual(b["gst"], 10.8)  # 18% of ₹60
        self.assertGreater(b["total_amount"], 0)

    def test_09_end_to_end_payment_order_and_signature_verification(self):
        """Tests complete booking order creation, payment signature verification, and digital ticket issuance."""
        # 1. Login user
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@cinepass.com",
            "password": Config.ADMIN_PASSWORD,
        })
        token = login_res.get_json()["token"]

        show = get_shows_collection().find_one()
        show_id = str(show["_id"])

        # Pick random unbooked seats
        seat_1 = f"D{random.randint(1, 8)}"
        seat_2 = f"D{random.randint(9, 16)}"
        # Clear any prior booking on these test seats
        get_bookings_collection().delete_many({"seat_ids": {"$in": [seat_1, seat_2]}})

        # 2. Create payment order
        order_res = self.client.post(
            "/api/payments/create-order",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "show_id": show_id,
                "seat_ids": [seat_1, seat_2],
                "coupon_code": "WELCOME50",
            },
        )
        self.assertEqual(order_res.status_code, 200, order_res.get_json())
        order_data = order_res.get_json()
        order_id = order_data["order_id"]
        booking_ref = order_data["booking_reference"]

        # 3. Generate authentic Razorpay HMAC signature
        secret = Config.RAZORPAY_KEY_SECRET.encode("utf-8")
        payment_id = f"pay_test_{random.randint(100000, 999999)}"
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        signature = hmac.new(secret, msg, hashlib.sha256).hexdigest()

        # 4. Verify payment
        verify_res = self.client.post("/api/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        self.assertEqual(verify_res.status_code, 200)
        booking = verify_res.get_json()["booking"]
        self.assertEqual(booking["payment_status"], "paid")
        self.assertEqual(booking["ticket_status"], "active")
        self.assertIn("qr_code_data", booking)

        # 5. Idempotency test: duplicate callback should return success without double processing
        dup_res = self.client.post("/api/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        self.assertEqual(dup_res.status_code, 200)
        self.assertTrue(dup_res.get_json()["already_processed"])

        # 6. Public QR Ticket Validation Endpoint
        val_res = self.client.get(f"/api/tickets/validate/{booking_ref}")
        self.assertEqual(val_res.status_code, 200)
        val_data = val_res.get_json()
        self.assertTrue(val_data["valid"])
        self.assertEqual(val_data["status"], "active")

    def test_10_booking_cancellation_and_refund_policy(self):
        """Tests that eligible bookings can be cancelled and verified refund amount calculated."""
        login_res = self.client.post("/api/auth/login", json={
            "email": "admin@cinepass.com",
            "password": Config.ADMIN_PASSWORD,
        })
        token = login_res.get_json()["token"]

        show = get_shows_collection().find_one()
        show_id = str(show["_id"])

        seat_1 = f"E{random.randint(1, 8)}"
        seat_2 = f"E{random.randint(9, 16)}"
        get_bookings_collection().delete_many({"seat_ids": {"$in": [seat_1, seat_2]}})

        order_res = self.client.post(
            "/api/payments/create-order",
            headers={"Authorization": f"Bearer {token}"},
            json={"show_id": show_id, "seat_ids": [seat_1, seat_2]},
        )
        order_data = order_res.get_json()
        order_id = order_data["order_id"]
        booking_id = order_data["booking_id"]
        booking_ref = order_data["booking_reference"]

        # Confirm payment
        self.client.post("/api/payments/verify", json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": f"pay_cancel_{random.randint(100, 999)}",
            "razorpay_signature": "simulated",
            "simulate_success_for_test": True,
        })

        # Cancel booking
        cancel_res = self.client.post(
            f"/api/bookings/{booking_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(cancel_res.status_code, 200)
        c_data = cancel_res.get_json()
        self.assertTrue(c_data["success"])
        self.assertGreater(c_data["refund_amount"], 0)

        # Validate ticket now must fail as cancelled
        val_res = self.client.get(f"/api/tickets/validate/{booking_ref}")
        self.assertEqual(val_res.status_code, 400)
        self.assertFalse(val_res.get_json()["valid"])
        self.assertEqual(val_res.get_json()["status"], "cancelled")

    def test_11_ai_cinebot_natural_language_assistant(self):
        """Tests CineBot natural language responses grounded in real catalog movies and showtimes."""
        # Test thriller inquiry
        res_thriller = self.client.post("/api/ai/cinebot", json={"message": "Suggest a thriller movie"})
        self.assertEqual(res_thriller.status_code, 200)
        data = res_thriller.get_json()
        self.assertTrue(data["success"])
        self.assertIn("reply", data)
        self.assertGreater(len(data["suggested_movies"]), 0)

        # Test showtime inquiry
        res_shows = self.client.post("/api/ai/cinebot", json={"message": "Showtimes for Interstellar in Mumbai", "city": "Mumbai"})
        self.assertEqual(res_shows.status_code, 200)
        s_data = res_shows.get_json()
        self.assertTrue(s_data["success"])

    def test_12_admin_portal_authorization_and_management(self):
        """Tests that ordinary users are blocked from admin routes, while admins can manage movies and view stats."""
        # Ordinary user login
        rand_email = f"standard_user_{random.randint(10000, 99999)}@cinepass.com"
        reg_res = self.client.post("/api/auth/register", json={
            "name": "Standard User",
            "email": rand_email,
            "password": "Password123",
        })
        user_token = reg_res.get_json()["token"]

        # Ordinary user attempting to fetch admin stats must get 403 Forbidden
        denied_res = self.client.get("/api/admin/stats", headers={"Authorization": f"Bearer {user_token}"})
        self.assertEqual(denied_res.status_code, 403)

        # Admin login
        admin_login = self.client.post("/api/auth/login", json={
            "email": "admin@cinepass.com",
            "password": Config.ADMIN_PASSWORD,
        })
        admin_token = admin_login.get_json()["token"]

        # Admin gets stats successfully
        admin_stats = self.client.get("/api/admin/stats", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(admin_stats.status_code, 200)
        st = admin_stats.get_json()["stats"]
        self.assertIn("total_revenue", st)
        self.assertIn("total_tickets_sold", st)


if __name__ == "__main__":
    unittest.main()
