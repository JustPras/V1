import sqlite3
import os
import hashlib
from app.database import init_db, get_db

def seed():
    print("Initializing DB...")
    init_db()
    print("Seeding DB...")
    with get_db() as db:
        password_hash = hashlib.sha256("password123".encode()).hexdigest()
        try:
            db.execute(
                "INSERT INTO merchants (slug, name, email, password_hash) VALUES (?, ?, ?, ?)",
                ("budi-ac", "Budi AC Services", "budi@example.com", password_hash)
            )
            merchant_id = db.execute("SELECT id FROM merchants WHERE slug = 'budi-ac'").fetchone()['id']
            
            db.execute(
                "INSERT INTO services (merchant_id, name, duration_mins, price, deposit_type, deposit_amount) VALUES (?, ?, ?, ?, ?, ?)",
                (merchant_id, "AC Cleaning", 60, 5000, "percentage", 50)
            )
            db.execute(
                "INSERT INTO services (merchant_id, name, duration_mins, price, deposit_type, deposit_amount) VALUES (?, ?, ?, ?, ?, ?)",
                (merchant_id, "Freon Refill", 30, 7500, "flat", 2000)
            )
            
            db.commit()
            print("Seed completed successfully! You can access the booking page at: /b/budi-ac")
        except sqlite3.IntegrityError:
            print("Database already seeded.")

if __name__ == "__main__":
    seed()
