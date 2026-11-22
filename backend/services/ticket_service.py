from __future__ import annotations

from typing import Any, Optional
from bson import ObjectId

from database import get_bookings_collection
from services.qr_service import generate_qr_data_url
from utils.serializers import serialize_doc


def get_ticket_by_reference(reference_or_id: str) -> Optional[dict[str, Any]]:
    coll = get_bookings_collection()
    booking = coll.find_one({"booking_reference": reference_or_id})
    if not booking:
        try:
            booking = coll.find_one({"_id": ObjectId(reference_or_id)})
        except Exception:
            pass
    if not booking:
        booking = coll.find_one({"id": reference_or_id})

    if not booking:
        return None

    doc = serialize_doc(booking)
    if not doc.get("qr_code_data"):
        from config import Config
        validation_url = f"{Config.APP_URL}/api/tickets/validate/{doc['booking_reference']}"
        doc["qr_code_data"] = generate_qr_data_url(validation_url)

    return doc


def validate_ticket(reference_or_id: str) -> dict[str, Any]:
    """Validates digital ticket authenticity.
    
    Only valid, paid, and non-cancelled tickets pass validation!
    """
    ticket = get_ticket_by_reference(reference_or_id)
    if not ticket:
        return {
            "valid": False,
            "status": "not_found",
            "message": "Ticket does not exist. Fraudulent or unrecognized ticket reference.",
        }

    payment_status = ticket.get("payment_status")
    ticket_status = ticket.get("ticket_status")

    if ticket_status == "cancelled" or payment_status == "refunded":
        return {
            "valid": False,
            "status": "cancelled",
            "message": "This ticket was cancelled and refunded. Entry denied.",
            "ticket": {
                "booking_reference": ticket.get("booking_reference"),
                "movie_title": ticket.get("movie_title"),
                "cinema_name": ticket.get("cinema_name"),
                "cancelled_at": ticket.get("cancelled_at"),
            },
        }

    if payment_status != "paid":
        return {
            "valid": False,
            "status": "unpaid",
            "message": "Payment for this ticket has not been verified. Entry denied.",
            "ticket": {
                "booking_reference": ticket.get("booking_reference"),
                "payment_status": payment_status,
            },
        }

    # Valid confirmed ticket
    return {
        "valid": True,
        "status": "active",
        "message": "Verified Authentic Cinepass Digital Ticket. Entry Approved.",
        "ticket": {
            "booking_reference": ticket.get("booking_reference"),
            "movie_title": ticket.get("movie_title"),
            "movie_poster": ticket.get("movie_poster"),
            "cinema_name": ticket.get("cinema_name"),
            "cinema_city": ticket.get("cinema_city"),
            "screen_name": ticket.get("screen_name"),
            "screen_type": ticket.get("screen_type"),
            "show_date": ticket.get("show_date"),
            "show_time": ticket.get("show_time"),
            "seats": [s.get("seat_id") if isinstance(s, dict) else s for s in (ticket.get("seats") or [])],
            "num_seats": len(ticket.get("seats") or []),
            "total_amount": ticket.get("total_amount"),
            "user_name": ticket.get("user_name"),
            "confirmed_at": ticket.get("confirmed_at"),
        },
    }
