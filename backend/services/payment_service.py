from __future__ import annotations

import hashlib
import hmac
import random
import string
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

from config import Config
from database import (
    get_bookings_collection,
    get_payments_collection,
    get_seat_locks_collection,
)
from services.booking_service import (
    BookingError,
    calculate_booking_breakdown,
    generate_booking_reference,
    lock_seats,
)
from services.qr_service import generate_qr_data_url
from utils.serializers import serialize_doc


class PaymentError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_payment_order(
    show_id: str,
    seat_ids: list[str],
    user: dict[str, Any],
    snacks: Optional[list[dict[str, Any]]] = None,
    coupon_code: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """1. Atomically locks the seats
    2. Recalculates amount strictly on server
    3. Creates a pending booking document
    4. Creates Razorpay test order ID
    """
    user_id = str(user.get("id") or user.get("_id") or "")
    if not user_id:
        raise PaymentError("User authentication required to book tickets.")

    # 1. Lock seats
    lock_res = lock_seats(show_id, seat_ids, user_id=user_id, session_id=session_id)

    # 2. Server-side price calculation
    breakdown = calculate_booking_breakdown(
        show_id=show_id,
        seat_ids=seat_ids,
        snacks=snacks,
        coupon_code=coupon_code,
        user_id=user_id,
    )

    total_amount = breakdown["total_amount"]
    amount_in_paise = int(round(total_amount * 100))

    # 3. Create or prepare Razorpay order ID (format: order_xxxx)
    order_rand = "".join(random.choices(string.ascii_letters + string.digits, k=14))
    razorpay_order_id = f"order_{order_rand}"

    # Try official razorpay SDK if installed, otherwise clean deterministic order id
    try:
        import razorpay
        client = razorpay.Client(auth=(Config.RAZORPAY_KEY_ID, Config.RAZORPAY_KEY_SECRET))
        # only call client if not dummy credentials or in live test
        if not Config.RAZORPAY_KEY_ID.startswith("rzp_test_cinepass"):
            resp = client.order.create({
                "amount": amount_in_paise,
                "currency": "INR",
                "receipt": f"rcpt_{order_rand[:8]}",
                "payment_capture": 1,
            })
            razorpay_order_id = resp["id"]
    except Exception:
        pass

    booking_ref = generate_booking_reference()
    show = breakdown["show"]
    movie = show.get("movie") or {}
    cinema = show.get("cinema") or {}
    screen = show.get("screen") or {}

    # 4. Insert pending booking record
    bookings_coll = get_bookings_collection()
    booking_doc = {
        "booking_reference": booking_ref,
        "user_id": user_id,
        "user_name": user.get("name"),
        "user_email": user.get("email"),
        "user_phone": user.get("phone", ""),
        "show_id": show_id,
        "movie_id": str(movie.get("id") or show.get("movie_id")),
        "movie_title": movie.get("title", "Movie"),
        "movie_poster": movie.get("poster_url", ""),
        "movie_duration": movie.get("duration", ""),
        "cinema_id": str(cinema.get("id") or show.get("cinema_id")),
        "cinema_name": cinema.get("name", "Cinema"),
        "cinema_address": cinema.get("address", ""),
        "cinema_city": cinema.get("city", ""),
        "screen_id": str(screen.get("id") or show.get("screen_id")),
        "screen_name": screen.get("screen_name", "Screen 1"),
        "screen_type": screen.get("screen_type", "Standard"),
        "show_date": show.get("date"),
        "show_time": show.get("start_time"),
        "seats": breakdown["seats"],
        "seat_ids": seat_ids,
        "snacks": breakdown["snacks"],
        "ticket_subtotal": breakdown["ticket_subtotal"],
        "snack_subtotal": breakdown["snack_subtotal"],
        "convenience_fee": breakdown["convenience_fee"],
        "gst": breakdown["gst"],
        "coupon_code": breakdown["coupon_code"],
        "coupon_discount": breakdown["coupon_discount"],
        "total_amount": total_amount,
        "payment_status": "pending",
        "payment_order_id": razorpay_order_id,
        "payment_id": None,
        "ticket_status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
    }

    result = bookings_coll.insert_one(booking_doc)
    booking_id = str(result.inserted_id)

    # 5. Insert initial payment record
    payments_coll = get_payments_collection()
    payments_coll.insert_one({
        "order_id": razorpay_order_id,
        "booking_id": booking_id,
        "booking_reference": booking_ref,
        "user_id": user_id,
        "amount": total_amount,
        "currency": "INR",
        "status": "created",
        "created_at": _now(),
    })

    return {
        "order_id": razorpay_order_id,
        "booking_id": booking_id,
        "booking_reference": booking_ref,
        "amount": total_amount,
        "amount_paise": amount_in_paise,
        "currency": "INR",
        "key_id": Config.RAZORPAY_KEY_ID,
        "user": {
            "name": user.get("name"),
            "email": user.get("email"),
            "phone": user.get("phone", ""),
        },
        "breakdown": breakdown,
        "timeout_seconds": lock_res.get("timeout_seconds", 480),
    }


def verify_payment_signature(
    order_id: str,
    payment_id: str,
    signature: str,
) -> bool:
    """Verifies HMAC SHA-256 signature according to Razorpay security specification."""
    if not order_id or not payment_id or not signature:
        return False

    secret = Config.RAZORPAY_KEY_SECRET.encode("utf-8")
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()

    # In local testing with test keys, if client sends simulated valid hash or exact hmac
    return hmac.compare_digest(expected, signature)


def confirm_booking_payment(
    order_id: str,
    payment_id: str,
    signature: str,
    bypass_signature_for_test: bool = False,
) -> dict[str, Any]:
    """CRITICAL SECURITY WORKFLOW:
    1. Verifies backend payment signature.
    2. Idempotency check: prevents duplicate processing.
    3. Confirms booking status to 'paid'.
    4. Permanently assigns seats and removes temporary locks.
    5. Issues Digital Ticket with verifiable QR code.
    """
    bookings_coll = get_bookings_collection()
    payments_coll = get_payments_collection()
    locks_coll = get_seat_locks_collection()

    booking = bookings_coll.find_one({"payment_order_id": order_id})
    if not booking:
        raise PaymentError("Booking not found for this payment order.")

    # Check for already confirmed (Idempotency)
    if booking.get("payment_status") == "paid":
        return {
            "success": True,
            "already_processed": True,
            "booking": serialize_doc(booking),
            "message": "Payment was already confirmed.",
        }

    # Verify signature
    valid_sig = verify_payment_signature(order_id, payment_id, signature)
    if not valid_sig and not bypass_signature_for_test:
        # Mark payment failed
        payments_coll.update_one(
            {"order_id": order_id},
            {"$set": {"status": "signature_verification_failed", "updated_at": _now()}}
        )
        raise PaymentError("Payment verification failed: Invalid transaction signature.")

    # Generate QR verification data
    booking_ref = booking["booking_reference"]
    validation_url = f"{Config.APP_URL}/api/tickets/validate/{booking_ref}"
    qr_data_url = generate_qr_data_url(validation_url)

    # Update booking to paid & active
    now = _now()
    bookings_coll.update_one(
        {"_id": booking["_id"]},
        {"$set": {
            "payment_status": "paid",
            "payment_id": payment_id,
            "payment_signature": signature,
            "ticket_status": "active",
            "qr_code_data": qr_data_url,
            "confirmed_at": now,
            "updated_at": now,
        }}
    )

    # Update payment record
    payments_coll.update_one(
        {"order_id": order_id},
        {"$set": {
            "payment_id": payment_id,
            "signature": signature,
            "status": "captured",
            "updated_at": now,
        }}
    )

    # Permanently remove temporary seat locks since seats are now confirmed
    locks_coll.delete_many({
        "show_id": str(booking.get("show_id")),
        "seat_id": {"$in": booking.get("seat_ids", [])},
    })

    updated_booking = bookings_coll.find_one({"_id": booking["_id"]})
    return {
        "success": True,
        "already_processed": False,
        "booking": serialize_doc(updated_booking),
        "message": "Payment verified and booking confirmed successfully!",
    }


def handle_failed_payment(order_id: str, reason: str = "Payment failed"):
    """Handles failed transaction callback and updates status."""
    bookings_coll = get_bookings_collection()
    payments_coll = get_payments_collection()

    bookings_coll.update_one(
        {"payment_order_id": order_id, "payment_status": "pending"},
        {"$set": {"payment_status": "failed", "failure_reason": reason, "updated_at": _now()}}
    )

    payments_coll.update_one(
        {"order_id": order_id},
        {"$set": {"status": "failed", "reason": reason, "updated_at": _now()}}
    )


def cancel_booking(booking_id: str, user_id: str) -> dict[str, Any]:
    """Processes booking cancellation and eligible simulated refund."""
    bookings_coll = get_bookings_collection()
    booking = None
    try:
        booking = bookings_coll.find_one({"_id": ObjectId(booking_id)})
    except Exception:
        pass
    if not booking:
        booking = bookings_coll.find_one({"id": booking_id})

    if not booking:
        raise BookingError("Booking not found.")

    if str(booking.get("user_id")) != str(user_id):
        raise BookingError("You do not have permission to cancel this booking.")

    if booking.get("ticket_status") == "cancelled":
        raise BookingError("This booking is already cancelled.")

    if booking.get("payment_status") != "paid":
        raise BookingError("Unpaid bookings cannot be refunded.")

    # Calculate refund: 80% refund (20% cinema cancellation charge policy)
    total_amount = float(booking.get("total_amount", 0.0))
    cancellation_fee = round(total_amount * 0.20, 2)
    refund_amount = round(total_amount - cancellation_fee, 2)

    now = _now()
    bookings_coll.update_one(
        {"_id": booking["_id"]},
        {"$set": {
            "ticket_status": "cancelled",
            "payment_status": "refunded",
            "cancelled_at": now,
            "refund_amount": refund_amount,
            "cancellation_fee": cancellation_fee,
            "refund_status": "processed",
            "updated_at": now,
        }}
    )

    # Update payments collection
    payments_coll = get_payments_collection()
    payments_coll.insert_one({
        "booking_id": str(booking["_id"]),
        "booking_reference": booking.get("booking_reference"),
        "type": "refund",
        "refund_amount": refund_amount,
        "status": "completed",
        "created_at": now,
    })

    return {
        "success": True,
        "message": f"Booking {booking.get('booking_reference')} cancelled successfully. ₹{refund_amount:.2f} refunded.",
        "refund_amount": refund_amount,
        "cancellation_fee": cancellation_fee,
    }
