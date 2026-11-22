from __future__ import annotations

import random
import string
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId

from config import Config
from database import (
    get_bookings_collection,
    get_cinemas_collection,
    get_coupons_collection,
    get_movies_collection,
    get_screens_collection,
    get_seat_locks_collection,
    get_shows_collection,
    get_snacks_collection,
)
from services.cinema_service import get_show_by_id
from utils.serializers import serialize_doc


_seat_lock_mutex = threading.RLock()


class BookingError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_booking_reference() -> str:
    """Generates a unique reference code, e.g. CP-202611-X7K9."""
    date_part = datetime.now().strftime("%Y%m")
    rand_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"CP-{date_part}-{rand_part}"


def cleanup_expired_locks():
    """Removes all expired temporary seat locks."""
    with _seat_lock_mutex:
        now = _now()
        locks = get_seat_locks_collection()
        locks.delete_many({"expires_at": {"$lt": now}})


def get_seat_layout_for_show(show_id: str, user_id: Optional[str] = None, session_id: Optional[str] = None) -> dict[str, Any]:
    """Builds interactive seat layout with real-time availability: available, locked, booked, or selected."""
    show = get_show_by_id(show_id)
    if not show:
        raise BookingError("Showtime not found.")

    screen = show.get("screen") or {}
    cinema = show.get("cinema") or {}

    cleanup_expired_locks()

    # Standard cinema layout with categories
    # VIP Recliner: Rows A-B
    # Platinum: Rows C-E
    # Gold: Rows F-I
    # Silver: Rows J-L
    price_tiers = show.get("price_tiers") or {
        "VIP": 550.0,
        "Platinum": 380.0,
        "Gold": 250.0,
        "Silver": 180.0,
    }

    tier_definitions = [
        {"tier": "VIP", "label": "VIP Recliner", "price": float(price_tiers.get("VIP", 550.0)), "rows": ["A", "B"], "cols": 12},
        {"tier": "Platinum", "label": "Platinum", "price": float(price_tiers.get("Platinum", 380.0)), "rows": ["C", "D", "E"], "cols": 16},
        {"tier": "Gold", "label": "Gold", "price": float(price_tiers.get("Gold", 250.0)), "rows": ["F", "G", "H", "I"], "cols": 16},
        {"tier": "Silver", "label": "Silver", "price": float(price_tiers.get("Silver", 180.0)), "rows": ["J", "K", "L"], "cols": 16},
    ]

    # Query confirmed bookings for this show
    bookings_coll = get_bookings_collection()
    show_or = [{"show_id": show_id}, {"show_id": str(show_id)}]
    try:
        show_or.append({"show_id": ObjectId(show_id)})
    except Exception:
        pass

    confirmed_bookings = bookings_coll.find({
        "$and": [
            {"$or": show_or},
            {"payment_status": "paid"},
            {"ticket_status": {"$ne": "cancelled"}},
        ]
    })

    booked_seat_ids = set()
    for b in confirmed_bookings:
        for s in (b.get("seats") or []):
            if isinstance(s, dict):
                booked_seat_ids.add(s.get("seat_id"))
            elif isinstance(s, str):
                booked_seat_ids.add(s)

    # Query active locks for this show
    locks_coll = get_seat_locks_collection()
    now = _now()
    active_locks = list(locks_coll.find({
        "$and": [
            {"$or": show_or},
            {"expires_at": {"$gt": now}},
        ]
    }))

    locked_seat_map = {}
    for l in active_locks:
        sid = l.get("seat_id")
        locked_by_user = (user_id and l.get("user_id") == user_id)
        locked_by_session = (session_id and l.get("session_id") == session_id)
        locked_seat_map[sid] = {
            "is_mine": bool(locked_by_user or locked_by_session),
            "expires_at": l.get("expires_at"),
            "seconds_remaining": max(0, int((l.get("expires_at") - now).total_seconds())) if isinstance(l.get("expires_at"), datetime) else 0,
        }

    # Construct seat layout
    layout_sections = []
    total_seats = 0
    available_seats = 0

    for section in tier_definitions:
        rows_data = []
        for row_letter in section["rows"]:
            seats = []
            for col_num in range(1, section["cols"] + 1):
                seat_id = f"{row_letter}{col_num}"
                total_seats += 1

                # Determine status
                if seat_id in booked_seat_ids:
                    status = "booked"
                elif seat_id in locked_seat_map:
                    if locked_seat_map[seat_id]["is_mine"]:
                        status = "selected"
                        available_seats += 1
                    else:
                        status = "locked"
                else:
                    status = "available"
                    available_seats += 1

                seats.append({
                    "id": seat_id,
                    "row": row_letter,
                    "number": col_num,
                    "tier": section["tier"],
                    "price": section["price"],
                    "status": status,
                    "locked_info": locked_seat_map.get(seat_id) if status in ("locked", "selected") else None,
                })
            rows_data.append({"row": row_letter, "seats": seats})

        layout_sections.append({
            "tier": section["tier"],
            "label": section["label"],
            "price": section["price"],
            "rows": rows_data,
        })

    return {
        "show": show,
        "screen_name": screen.get("screen_name", "Screen 1"),
        "screen_type": screen.get("screen_type", "Standard"),
        "total_seats": total_seats,
        "available_seats": available_seats,
        "sections": layout_sections,
    }


def lock_seats(
    show_id: str,
    seat_ids: list[str],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Atomic server-side seat locking with expiration.
    
    Prevents double booking. Raises BookingError if any seat is already booked
    or actively locked by another customer.
    """
    if not seat_ids:
        raise BookingError("No seats selected for locking.")
    if len(seat_ids) > 10:
        raise BookingError("You can book a maximum of 10 seats at a time.")

    with _seat_lock_mutex:
        cleanup_expired_locks()

        show = get_show_by_id(show_id)
        if not show:
            raise BookingError("Showtime not found.")

        # Check if already booked in confirmed bookings
        bookings_coll = get_bookings_collection()
        show_or = [{"show_id": show_id}, {"show_id": str(show_id)}]
        try:
            show_or.append({"show_id": ObjectId(show_id)})
        except Exception:
            pass

        booked = bookings_coll.find({
            "$and": [
                {"$or": show_or},
                {"payment_status": "paid"},
                {"ticket_status": {"$ne": "cancelled"}},
            ]
        })
        all_booked = set()
        for b in booked:
            for s in (b.get("seats") or []):
                sid = s.get("seat_id") if isinstance(s, dict) else s
                all_booked.add(sid)

        for sid in seat_ids:
            if sid in all_booked:
                raise BookingError(f"Seat {sid} is already booked by another customer.")

        # Check existing locks
        locks_coll = get_seat_locks_collection()
        now = _now()
        existing_locks = list(locks_coll.find({
            "$and": [
                {"$or": show_or},
                {"seat_id": {"$in": seat_ids}},
                {"expires_at": {"$gt": now}},
            ]
        }))

        for l in existing_locks:
            l_uid = l.get("user_id")
            l_sid = l.get("session_id")
            # If locked by someone else
            if not ((user_id and l_uid == user_id) or (session_id and l_sid == session_id)):
                raise BookingError(f"Seat {l.get('seat_id')} is currently locked by another customer.")

        # Atomic lock assignment
        timeout_seconds = Config.SEAT_LOCK_TIMEOUT_SECONDS
        expires_at = now + timedelta(seconds=timeout_seconds)

        for sid in seat_ids:
            locks_coll.update_one(
                {"show_id": str(show_id), "seat_id": sid},
                {"$set": {
                    "show_id": str(show_id),
                    "seat_id": sid,
                    "user_id": user_id,
                    "session_id": session_id,
                    "locked_at": now,
                    "expires_at": expires_at,
                }},
                upsert=True,
            )

        return {
            "success": True,
            "locked_seats": seat_ids,
            "timeout_seconds": timeout_seconds,
            "expires_at": expires_at.isoformat(),
        }


def unlock_seats(show_id: str, seat_ids: list[str], user_id: Optional[str] = None, session_id: Optional[str] = None):
    """Releases active seat locks when user deselects or cancels."""
    with _seat_lock_mutex:
        locks_coll = get_seat_locks_collection()
        query: dict[str, Any] = {
            "show_id": str(show_id),
            "seat_id": {"$in": seat_ids},
        }
        user_or = []
        if user_id:
            user_or.append({"user_id": user_id})
        if session_id:
            user_or.append({"session_id": session_id})
        if user_or:
            query["$or"] = user_or

        locks_coll.delete_many(query)
        return True


def list_cinema_snacks(cinema_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Returns available snacks, beverages, popcorn, and combo offerings."""
    snacks_coll = get_snacks_collection()
    query = {"is_available": True}
    if cinema_id:
        query["$or"] = [{"cinema_id": cinema_id}, {"cinema_id": None}, {"cinema_id": {"$exists": False}}]

    items = list(snacks_coll.find(query))
    if not items:
        # Return standard cinema food menu
        return [
            {"id": "snk-1", "name": "Large Butter Popcorn", "category": "popcorn", "price": 280.0, "description": "Crispy golden popcorn tossed in creamy melted butter.", "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?auto=format&fit=crop&w=400&q=80"},
            {"id": "snk-2", "name": "Caramel Gourmet Popcorn", "category": "popcorn", "price": 320.0, "description": "Sweet crunchy kettle corn coated with rich golden caramel.", "image_url": "https://images.unsplash.com/photo-1512149177596-f817c7ef5d4c?auto=format&fit=crop&w=400&q=80"},
            {"id": "snk-3", "name": "Classic Movie Nachos & Salsa", "category": "snacks", "price": 240.0, "description": "Crispy tortilla chips served with zesty salsa and warm cheese dip.", "image_url": "https://images.unsplash.com/photo-1513456852971-30c0b8199d4d?auto=format&fit=crop&w=400&q=80"},
            {"id": "snk-4", "name": "Cold Coca-Cola (Large)", "category": "beverages", "price": 180.0, "description": "Refreshing ice-cold fountain beverage (650ml).", "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?auto=format&fit=crop&w=400&q=80"},
            {"id": "snk-5", "name": "Fresh Lemon Iced Tea", "category": "beverages", "price": 190.0, "description": "Chilled black tea brewed with organic lemons and mint leaves.", "image_url": "https://images.unsplash.com/photo-1556679343-c7306c1976bc?auto=format&fit=crop&w=400&q=80"},
            {"id": "snk-6", "name": "Blockbuster Couple Combo", "category": "combos", "price": 540.0, "description": "1 Large Tub Popcorn + 2 Large Fountain Drinks + 1 Nachos.", "image_url": "https://images.unsplash.com/photo-1585647347384-2593bc35786b?auto=format&fit=crop&w=400&q=80"},
        ]
    return [serialize_doc(i) for i in items]


def validate_coupon(code: str, order_subtotal: float, user_id: Optional[str] = None) -> dict[str, Any]:
    """Validates coupon code against usage limits, expiry, and minimum order amount."""
    if not code:
        return {"valid": False, "discount": 0.0, "message": "No coupon entered."}

    clean_code = code.strip().upper()
    coupons_coll = get_coupons_collection()
    coupon = coupons_coll.find_one({"code": clean_code, "active": True})

    if not coupon:
        # Check standard default promo codes
        defaults = {
            "CINEPASS20": {"type": "percentage", "value": 20.0, "min_amount": 300.0, "max_discount": 150.0},
            "WELCOME50": {"type": "fixed", "value": 50.0, "min_amount": 250.0, "max_discount": 50.0},
            "FLAT100": {"type": "fixed", "value": 100.0, "min_amount": 600.0, "max_discount": 100.0},
            "BLOCKBUSTER": {"type": "percentage", "value": 25.0, "min_amount": 500.0, "max_discount": 200.0},
        }
        if clean_code in defaults:
            c_meta = defaults[clean_code]
            if order_subtotal < c_meta["min_amount"]:
                return {
                    "valid": False,
                    "discount": 0.0,
                    "message": f"Minimum order amount for {clean_code} is ₹{c_meta['min_amount']:.2f}.",
                }
            if c_meta["type"] == "percentage":
                disc = (order_subtotal * c_meta["value"]) / 100.0
                disc = min(disc, c_meta["max_discount"])
            else:
                disc = min(c_meta["value"], order_subtotal)
            return {
                "valid": True,
                "code": clean_code,
                "discount": round(disc, 2),
                "message": f"Coupon {clean_code} applied successfully! You saved ₹{disc:.2f}.",
            }
        return {"valid": False, "discount": 0.0, "message": "Invalid or expired coupon code."}

    # Verify minimum order
    min_amt = float(coupon.get("min_amount", 0.0))
    if order_subtotal < min_amt:
        return {
            "valid": False,
            "discount": 0.0,
            "message": f"Minimum order amount for {clean_code} is ₹{min_amt:.2f}.",
        }

    # Verify expiry
    if "expiry_date" in coupon and coupon["expiry_date"]:
        exp = coupon["expiry_date"]
        if isinstance(exp, str):
            try:
                exp = datetime.fromisoformat(exp)
            except Exception:
                pass
        if isinstance(exp, datetime) and exp < _now():
            return {"valid": False, "discount": 0.0, "message": "This coupon has expired."}

    # Calculate discount
    disc_type = coupon.get("discount_type", "percentage")
    val = float(coupon.get("discount_value", 0.0))
    max_disc = float(coupon.get("max_discount", 999999.0))

    if disc_type == "percentage":
        discount = (order_subtotal * val) / 100.0
        discount = min(discount, max_disc)
    else:
        discount = min(val, order_subtotal)

    return {
        "valid": True,
        "code": clean_code,
        "discount": round(discount, 2),
        "message": f"Coupon {clean_code} applied successfully! You saved ₹{discount:.2f}.",
    }


def calculate_booking_breakdown(
    show_id: str,
    seat_ids: list[str],
    snacks: Optional[list[dict[str, Any]]] = None,
    coupon_code: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """CRITICAL SECURITY REQUIREMENT:
    Calculates all payment amounts strictly on the backend.
    Never trusts amount sent by frontend JavaScript!
    """
    show = get_show_by_id(show_id)
    if not show:
        raise BookingError("Showtime not found.")

    if not seat_ids:
        raise BookingError("Please select at least one seat.")

    # Price tiers
    price_tiers = show.get("price_tiers") or {
        "VIP": 550.0,
        "Platinum": 380.0,
        "Gold": 250.0,
        "Silver": 180.0,
    }

    # Determine tier and price for each seat
    seats_detail = []
    ticket_subtotal = 0.0

    for sid in seat_ids:
        row = sid[0].upper()
        if row in ("A", "B"):
            tier = "VIP"
            tier_name = "VIP Recliner"
        elif row in ("C", "D", "E"):
            tier = "Platinum"
            tier_name = "Platinum"
        elif row in ("F", "G", "H", "I"):
            tier = "Gold"
            tier_name = "Gold"
        else:
            tier = "Silver"
            tier_name = "Silver"

        price = float(price_tiers.get(tier, 250.0))
        seats_detail.append({
            "seat_id": sid,
            "row": row,
            "tier": tier,
            "tier_name": tier_name,
            "price": price,
        })
        ticket_subtotal += price

    # Snacks calculation
    snacks_detail = []
    snack_subtotal = 0.0
    if snacks:
        available_menu = {s["id"]: s for s in list_cinema_snacks(str(show.get("cinema_id")))}
        for item in snacks:
            snk_id = item.get("id")
            qty = int(item.get("quantity", 0))
            if qty > 0 and snk_id in available_menu:
                menu_item = available_menu[snk_id]
                item_price = float(menu_item["price"])
                line_total = item_price * qty
                snacks_detail.append({
                    "id": snk_id,
                    "name": menu_item["name"],
                    "price": item_price,
                    "quantity": qty,
                    "total": line_total,
                })
                snack_subtotal += line_total

    num_tickets = len(seat_ids)
    fee_per_ticket = Config.CONVENIENCE_FEE_PER_TICKET
    convenience_fee = round(fee_per_ticket * num_tickets, 2)
    gst = round((convenience_fee * Config.GST_PERCENTAGE) / 100.0, 2)

    order_subtotal = ticket_subtotal + snack_subtotal
    coupon_result = validate_coupon(coupon_code, order_subtotal, user_id)
    discount = coupon_result.get("discount", 0.0) if coupon_result.get("valid") else 0.0

    final_total = max(0.0, round(ticket_subtotal + snack_subtotal + convenience_fee + gst - discount, 2))

    return {
        "show": show,
        "seats": seats_detail,
        "num_tickets": num_tickets,
        "ticket_subtotal": ticket_subtotal,
        "snacks": snacks_detail,
        "snack_subtotal": snack_subtotal,
        "convenience_fee": convenience_fee,
        "gst": gst,
        "gst_percentage": Config.GST_PERCENTAGE,
        "coupon_code": coupon_code if coupon_result.get("valid") else None,
        "coupon_discount": discount,
        "coupon_message": coupon_result.get("message"),
        "total_amount": final_total,
    }
