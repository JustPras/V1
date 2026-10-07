# SlotArmor V1

SlotArmor is a deposit-secured booking system for independent professionals. It eliminates no-shows by requiring an upfront deposit and automates client communication.

## Features (V1)
- **Apple Ecosystem UI:** Premium, interactive user interface using glassmorphism, fluid animations (GSAP), and system fonts.
- **Smart Booking Wizard:** 3-step intuitive booking process for clients.
- **Deposit Security:** Calculate percentage or fixed deposits to protect your time.
- **Admin Dashboard:** Monitor confirmed bookings, pending deposits, and KPIs in real-time.
- **Simulated Checkout:** Ready for payment gateway integration (QRIS / Crypto).

## Tech Stack
- **Backend:** FastAPI (Python)
- **Frontend:** Jinja2 Templates, Tailwind CSS, Vanilla JS, GSAP (Animations)
- **Database:** SQLite

## How to Run Locally

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # On Windows
   pip install -r requirements.txt
   ```

2. Seed the database with sample data:
   ```bash
   python seed.py
   ```

3. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

4. Open your browser:
   - **Client view:** `http://127.0.0.1:8000`
   - **Admin login:** `http://127.0.0.1:8000/admin/login` (Default username: `admin`, password: `password`)
