import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'slotarmor.db')

if os.environ.get('VERCEL') == '1':
    DB_PATH = '/tmp/slotarmor.db'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        # Enable WAL mode
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        
        # Create tables
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS merchants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                duration_mins INTEGER NOT NULL,
                price INTEGER NOT NULL, -- Stored in cents
                deposit_type TEXT NOT NULL, -- 'percentage' or 'flat'
                deposit_amount INTEGER NOT NULL,
                FOREIGN KEY (merchant_id) REFERENCES merchants (id)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_code TEXT UNIQUE NOT NULL,
                service_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_email TEXT,
                booking_date TEXT NOT NULL, -- ISO Date
                start_time TEXT NOT NULL, -- HH:MM
                status TEXT NOT NULL DEFAULT 'pending', -- pending, confirmed, paid, cancelled, done
                stripe_session_id TEXT,
                reminder_h1_sent INTEGER DEFAULT 0,
                reminder_dayof_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (service_id) REFERENCES services (id)
            );
        ''')
        
        # Simple migration for existing DB
        try:
            conn.execute('ALTER TABLE bookings ADD COLUMN reminder_h1_sent INTEGER DEFAULT 0;')
            conn.execute('ALTER TABLE bookings ADD COLUMN reminder_dayof_sent INTEGER DEFAULT 0;')
        except sqlite3.OperationalError:
            pass # Columns already exist
            
        conn.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
