# Cinepass — Premier Cinema Discovery & Ticket Booking Platform

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Framework-Flask%203.1.3-black.svg)](https://flask.palletsprojects.com/)
[![Database](https://img.shields.io/badge/Database-MongoDB%20%2B%20PyMongo%20(Fail--safe%20Embedded%20Engine)-green.svg)](https://www.mongodb.com/)
[![Payments](https://img.shields.io/badge/Payments-Razorpay%20Test%20Gateway-blue.svg)](https://razorpay.com/)
[![AI Concierge](https://img.shields.io/badge/AI%20Assistant-CineBot%20(Multi--Provider)-purple.svg)](https://github.com/Strata56/Cinepass)

**Live Demo Website:** [https://cinepass-1.onrender.com/](https://cinepass-1.onrender.com/)  
**GitHub Repository:** [https://github.com/Strata56/Cinepass](https://github.com/Strata56/Cinepass)

Cinepass is a complete, production-grade online cinema ticket booking and movie discovery web application inspired by BookMyShow, PVR Cinemas, Netflix, and IMDb. It combines cinematic UI/UX, multi-tier interactive seat selection, server-side atomic seat locking, Razorpay test payment verification, digital ticket issuance with verifiable QR codes, and an AI-powered cinema concierge (CineBot).

---

## Key Features

### 1. Premium Cinema UI & Discovery
- **Aesthetic Identity**: Deep obsidian & charcoal palette (`#07080b`, `#0f1118`), electric violet (`#7c3aed`), cinema rose (`#e11d48`), gold ratings (`#f59e0b`), and smooth micro-animations.
- **Hero Carousel**: Cinematic hero banners displaying trending blockbusters with direct booking, trailer playback, and metadata tags.
- **Categorized Sections**: Now Showing, Trending This Week, Top Rated, Coming Soon, and Curated Recommendations.
- **Advanced Discovery**: Multi-field search by title, actor, director, genre, and release year with real-time autocomplete suggestions (debounced) and keyboard shortcut (`Ctrl+K`).
- **City & Cinema Discovery**: Filter theatres by city (Mumbai, Delhi-NCR, Bengaluru, Hyderabad, Chennai, Pune) and format amenities (IMAX with Laser, 4DX, Dolby Atmos, Director's Cut Recliner).

### 2. Complete 4-Step Movie Ticket Booking Workflow
- **STEP 1: Showtime Picker**: Select movie, city, date (5-day rolling schedule), and cinema screen format.
- **STEP 2: Interactive Seat Map**: Curved cinema screen visualization with multi-tier seating:
  - **VIP Recliner** (Rows A-B, ₹550)
  - **Platinum** (Rows C-E, ₹380)
  - **Gold** (Rows F-I, ₹250)
  - **Silver** (Rows J-L, ₹180)
- **Server-Side Atomic Seat Locking**:
  - Automatically locks selected seats for an **8-minute reservation window** with live countdown timer (`08:00`).
  - Cryptographically and atomically prevents double bookings.
  - Automatically frees expired seat locks on abandoned sessions.
- **STEP 3: Gourmet Cinema Concessions**: Optional food & beverage add-ons (Butter Popcorn, Gourmet Caramel Corn, Coke, Nachos with Salsa, Couple Combos) with quantity adjusters.
- **STEP 4: Order Summary & Promo Coupons**:
  - Itemized server-side pricing: Ticket subtotal, Snacks subtotal, Convenience fee (₹30/seat), GST (18%), and verified coupon discounts (`CINEPASS20`, `WELCOME50`, `FLAT100`).
  - **Security Assurance**: Never trusts frontend payment amounts; all subtotals and discounts are verified strictly on the backend.

### 3. Razorpay Payment Gateway & Digital Tickets
- **Test Mode Gateway**: Order creation and cryptographic HMAC-SHA256 signature verification (`order_id|payment_id`).
- **Idempotency Protection**: Duplicate payment callbacks are handled safely without duplicate ticket creation.
- **Digital Cinema Pass**: Generates a digital ticket featuring:
  - Unique booking reference code (e.g. `CP-202611-X7K9`)
  - Movie, cinema, screen format, date, showtime, and assigned seat identifiers
  - Built-in SVG QR code linking to the public validation endpoint
  - Single-click print / save layout (`window.print()`).
- **Public QR Validation Endpoint**: `/api/tickets/validate/<reference>` allows theatre staff to verify ticket authenticity, payment status, and admission validity.

### 4. AI Cinema Concierge — CineBot & Personalization
- **CineBot AI Assistant**: Floating concierge capable of natural language queries:
  - *"What should I watch tonight?"*
  - *"Suggest a thriller movie"*
  - *"Best movie for a family night"*
  - *"Showtimes for Interstellar in Mumbai"*
  - **Catalogue Grounding**: Recommends real catalog movies and retrieves live cinema showtimes.
  - **Graceful Fallback**: Functions seamlessly with rule-based natural language intelligence when external AI API keys are not configured.
- **Personalized Recommendations**: Learns user genre affinities from watchlists, previous ticket bookings, and ratings.

### 5. User Account & Administrator Portal
- **User Authentication**: Secure password hashing (`pbkdf2:sha256`), token/session management, registration, login, logout, profile updates, and password changes.
- **User Dashboard**: Overview of active, past, and cancelled bookings with a one-click cancellation policy (80% verified refund simulator).
- **Admin Management Portal (`/admin` via `admin@cinepass.com`)**:
  - Real-time statistics: Total revenue, tickets sold, active shows, registered users.
  - CRUD management for movies, cinemas, screens, showtimes, and promo coupons.

---

## Architecture & Technology Stack

```text
Cinepass/
├── backend/
│   ├── app.py                      # Flask application factory & 51 RESTful API endpoints
│   ├── config.py                   # Environment configuration & feature flags
│   ├── database.py                 # Resilient dual-mode database engine (MongoDB + Fallback)
│   ├── seed_database.py            # Comprehensive cinema, movie, and showtime dataset
│   ├── requirements.txt            # Production dependencies
│   ├── services/
│   │   ├── auth_service.py         # PBKDF2 password hashing & RBAC
│   │   ├── booking_service.py      # Atomic seat locking & server-side pricing
│   │   ├── cinema_service.py       # City, cinema, screen, and showtime queries
│   │   ├── cinebot_service.py      # AI CineBot assistant & catalogue grounding
│   │   ├── movie_service.py        # Movie discovery, filters, search & summaries
│   │   ├── payment_service.py      # Razorpay test mode & HMAC-SHA256 verification
│   │   ├── personalization_service.py # Watchlist & booking-based recommendations
│   │   ├── qr_service.py           # Pure-Python SVG QR code matrix generator
│   │   ├── review_service.py       # Verified viewer reviews & ratings
│   │   └── ticket_service.py       # Digital ticket rendering & public verification
│   ├── static/
│   │   ├── css/style.css           # Premium dark cinema stylesheet
│   │   └── js/app.js               # Reactive ES6+ application client
│   ├── templates/
│   │   └── index.html              # Single-page cinema application template
│   └── utils/
│       ├── serializers.py          # BSON / ObjectId / datetime serializers
│       └── validators.py           # Query and payload validation
├── tests/
│   └── test_cinepass_production.py # 12 automated end-to-end test suites
├── .env.example                    # Environment variable template
├── Procfile                        # Render start command
├── render.yaml                     # Render infrastructure blueprint
└── README.md                       # Comprehensive documentation
```

### Technology Breakdown

| Component | Technology | Version | Purpose |
|---|---|---|---|
| **Backend Framework** | Flask | 3.1.3 | RESTful API, session handling, template serving |
| **WSGI Server** | Gunicorn | 21.2.0 | Production application server |
| **Database** | MongoDB / PyMongo | 4.18.1 | Primary persistent document store with indexing |
| **Resilient Storage** | Fallback JSON Engine | Built-in | Zero-downtime offline storage ensuring 100% testability |
| **Security & Auth** | Werkzeug / itsdangerous | 3.1.8 / 2.2.0 | PBKDF2:SHA256 hashing, signed timed tokens |
| **Payment Gateway** | Razorpay Test Suite | Built-in / 1.4.1 | Order creation & HMAC-SHA256 signature verification |
| **QR Code Engine** | Pure-Python SVG Generator | Built-in | Digital ticket QR rendering without external binary dependencies |
| **Frontend Languages**| HTML5, CSS3, Vanilla JS (ES6+) | Modern | Reactive DOM manipulation, seat map SVGs, modals |
| **AI Integrations** | Gemini / OpenAI / OpenRouter | Optional | CineBot dialogue and spoiler-free summaries |
| **Testing** | unittest | Standard Lib | 12 automated test suites verifying all critical paths |

---

## Installation & Local Development

### Prerequisites
- Python 3.10, 3.11, or 3.13
- Git

### 1. Clone the repository
```bash
git clone https://github.com/Strata56/Cinepass.git
cd Cinepass
```

### 2. Create and activate a virtual environment
```bash
python -m venv venv

# On Windows (PowerShell):
venv\Scripts\activate

# On macOS/Linux:
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r backend/requirements.txt
```

### 4. Configure environment variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
*(On Windows Command Prompt: `copy .env.example .env`)*

### 5. Seed the database
Populates 16 featured movies, 10 premier cinemas, 840 scheduled showtimes across 6 cities, gourmet snacks, discount coupons, and administrator credentials:
```bash
python backend/seed_database.py
```

### 6. Run the application
```bash
python backend/app.py
```
Open **`http://127.0.0.1:5000`** in your browser.

---

## Automated Test Suite

Run the full end-to-end test suite (all 12 production test cases):
```bash
python -m unittest tests/test_cinepass_production.py
```

### Test Coverage Highlights:
- **`test_01`**: Homepage and `/api/movies` response (200 OK).
- **`test_02`**: Homepage curated carousel, trending, and genre groupings.
- **`test_03`**: Real-time autocomplete suggestions and multi-attribute filters.
- **`test_04`**: Movie details and similar movies discovery.
- **`test_05`**: Cinema directory, amenities, and scheduled showtimes by city.
- **`test_06`**: User registration, password hashing, login, profile updates, and watchlist.
- **`test_07`**: Multi-tier seat map layout, atomic seat locking, conflict rejection (409), and unlock.
- **`test_08`**: Strictly server-calculated pricing, convenience fees, 18% GST, and coupons.
- **`test_09`**: Razorpay test order creation, authentic HMAC-SHA256 signature verification, confirmed booking, digital ticket generation, and idempotency.
- **`test_10`**: Booking cancellation policy with 80% refund processing and ticket invalidation.
- **`test_11`**: AI CineBot natural language concierge grounded in real catalog showtimes.
- **`test_12`**: Role-based access control (RBAC), blocking ordinary users (403), and admin platform metrics.

---

## Default Administrative Credentials

- **Email**: `admin@cinepass.com`
- **Password**: `CinePass@Admin2026`

*You can change these in `.env` via `ADMIN_EMAIL` and `ADMIN_PASSWORD`.*

---

## Render Deployment Guide

1. Create a **Web Service** on [Render.com](https://render.com).
2. Connect your GitHub repository (`Strata56/Cinepass`).
3. Set the following settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r backend/requirements.txt && python backend/seed_database.py`
   - **Start Command**: `gunicorn --chdir backend app:app`
4. Add the following Environment Variables in the Render dashboard:
   - `FLASK_ENV` = `production`
   - `ALLOW_FALLBACK_DB` = `true`
   - `SECRET_KEY` = `generate-a-strong-secret-key`
   - `MONGODB_URI` = *(Optional: MongoDB Atlas connection string)*
   - `RAZORPAY_KEY_ID` = `rzp_test_cinepass2026key`
   - `RAZORPAY_KEY_SECRET` = `cinepass_test_secret_99887766`
   - `ADMIN_EMAIL` = `admin@cinepass.com`
   - `ADMIN_PASSWORD` = `YourSecureAdminPassword`
5. Click **Deploy**. Cinepass will automatically seed showtimes and launch.

---

## License

This project is open-source and developed for educational and portfolio demonstration purposes. All movie trademarks, posters, and imagery belong to their respective copyright holders.
