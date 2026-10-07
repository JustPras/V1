from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import init_db, get_db
import os
import secrets
import hmac
import hashlib
import asyncio
from datetime import datetime
import csv
import io
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

app = FastAPI(title="SlotArmor", description="Micro-Hold Booking SaaS")

# Mount static files and templates if they exist
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

async def cleanup_expired_bookings():
    """Background task that runs every minute to cancel unpaid holds older than 10 minutes."""
    while True:
        try:
            with get_db() as db:
                # Cancel bookings older than 10 minutes
                cursor = db.execute('''
                    UPDATE bookings 
                    SET status = 'cancelled' 
                    WHERE status = 'pending' 
                    AND created_at < datetime('now', '-10 minutes')
                ''')
                db.commit()
                if cursor.rowcount > 0:
                    print(f"[{datetime.now()}] Auto-cancelled {cursor.rowcount} expired bookings.")
        except Exception as e:
            print(f"Error in cleanup task: {e}")
            
        await asyncio.sleep(60) # Wait 60 seconds before checking again

from app.whatsapp import send_whatsapp_reminder

async def process_whatsapp_reminders():
    """Background task running every hour to send H-1 and Day-of reminders."""
    while True:
        try:
            with get_db() as db:
                # Fetch bookings that are paid (confirmed) and not yet done/cancelled
                bookings = db.execute('''
                    SELECT b.*, s.name as service_name 
                    FROM bookings b
                    JOIN services s ON b.service_id = s.id
                    WHERE b.status = 'paid'
                ''').fetchall()
                
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                
                for b in bookings:
                    try:
                        b_date = datetime.strptime(b['booking_date'], "%Y-%m-%d")
                        days_diff = (b_date.date() - now.date()).days
                        
                        # H-1 Reminder
                        if days_diff == 1 and b['reminder_h1_sent'] == 0:
                            send_whatsapp_reminder(b['customer_phone'], b['customer_name'], b['service_name'], b['booking_date'], b['start_time'], "H-1")
                            db.execute("UPDATE bookings SET reminder_h1_sent = 1 WHERE id = ?", (b['id'],))
                        
                        # Day-of Reminder
                        elif days_diff == 0 and b['reminder_dayof_sent'] == 0:
                            send_whatsapp_reminder(b['customer_phone'], b['customer_name'], b['service_name'], b['booking_date'], b['start_time'], "Hari H (Hari Ini)")
                            db.execute("UPDATE bookings SET reminder_dayof_sent = 1 WHERE id = ?", (b['id'],))
                            
                    except Exception as parse_e:
                        print(f"Date parse error for booking {b['id']}: {parse_e}")
                        
                db.commit()
        except Exception as e:
            print(f"Error in WhatsApp reminder task: {e}")
            
        await asyncio.sleep(60 * 60) # Run every hour

@app.on_event("startup")
async def startup_event():
    init_db()
    # Start the background auto-cleanup task
    asyncio.create_task(cleanup_expired_bookings())
    # Start the background WhatsApp reminder task
    asyncio.create_task(process_whatsapp_reminders())

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html", 
        context={"title": "SlotArmor"}
    )

@app.get("/b/{slug}", response_class=HTMLResponse)
async def booking_page(request: Request, slug: str):
    with get_db() as db:
        merchant = db.execute("SELECT * FROM merchants WHERE slug = ?", (slug,)).fetchone()
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        
        services = db.execute("SELECT * FROM services WHERE merchant_id = ?", (merchant['id'],)).fetchall()
        
    return templates.TemplateResponse(
        request=request,
        name="booking.html", 
        context={
            "merchant": merchant,
            "services": services
        }
    )

# Add other endpoints (booking creation, webhook, admin console) here...

@app.post("/b/{slug}/checkout")
async def process_booking(
    request: Request, 
    slug: str,
    service_id: int = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    date: str = Form(...),
    time: str = Form(...)
):
    with get_db() as db:
        merchant = db.execute("SELECT * FROM merchants WHERE slug = ?", (slug,)).fetchone()
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        
        service = db.execute("SELECT * FROM services WHERE id = ? AND merchant_id = ?", (service_id, merchant['id'])).fetchone()
        if not service:
            raise HTTPException(status_code=400, detail="Invalid service")

        # Generate unique 8-character reference code
        ref_code = secrets.token_hex(4)
        
        db.execute('''
            INSERT INTO bookings (reference_code, service_id, customer_name, customer_phone, booking_date, start_time, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
        ''', (ref_code, service_id, name, phone, date, time))
        db.commit()
        
    return RedirectResponse(url=f"/checkout/{ref_code}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/checkout/{ref_code}", response_class=HTMLResponse)
async def checkout_page(request: Request, ref_code: str):
    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE reference_code = ?", (ref_code,)).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
            
        if booking['status'] != 'pending':
            return RedirectResponse(url=f"/checkout/{ref_code}/success", status_code=status.HTTP_303_SEE_OTHER)

        service = db.execute("SELECT * FROM services WHERE id = ?", (booking['service_id'],)).fetchone()
        
        # Calculate deposit
        if service['deposit_type'] == 'percentage':
            deposit_amount = int(service['price'] * (service['deposit_amount'] / 100.0))
        else:
            deposit_amount = service['deposit_amount']

        # Calculate remaining seconds for 10-minute hold
        created_at_dt = datetime.strptime(booking['created_at'], "%Y-%m-%d %H:%M:%S")
        elapsed_seconds = (datetime.utcnow() - created_at_dt).total_seconds()
        remaining_seconds = max(0, int((10 * 60) - elapsed_seconds))
            
    return templates.TemplateResponse(
        request=request,
        name="checkout.html",
        context={
            "booking": booking,
            "service": service,
            "deposit_amount": deposit_amount,
            "remaining_seconds": remaining_seconds
        }
    )

@app.post("/checkout/{ref_code}/simulate-payment")
async def simulate_payment(request: Request, ref_code: str):
    with get_db() as db:
        db.execute("UPDATE bookings SET status = 'paid' WHERE reference_code = ?", (ref_code,))
        db.commit()
    return RedirectResponse(url=f"/checkout/{ref_code}/success", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/checkout/{ref_code}/success", response_class=HTMLResponse)
async def success_page(request: Request, ref_code: str):
    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE reference_code = ?", (ref_code,)).fetchone()
        if not booking or booking['status'] != 'paid':
            raise HTTPException(status_code=404, detail="Booking not found or not paid")
            
        service = db.execute("SELECT * FROM services WHERE id = ?", (booking['service_id'],)).fetchone()
        merchant = db.execute("SELECT * FROM merchants WHERE id = ?", (service['merchant_id'],)).fetchone()
        
    return templates.TemplateResponse(
        request=request,
        name="success.html",
        context={
            "booking": booking,
            "service": service,
            "merchant": merchant
        }
    )

# --- Admin Console Routes ---

def get_current_merchant(request: Request):
    session_token = request.cookies.get("admin_session")
    if not session_token:
        return None
    # Very simple mock session verification (in production use JWT or DB session table)
    # Here we just look up the merchant by the raw string for MVP simplicity 
    # (assuming session_token is just merchant id for now, though it's not secure)
    merchant_id = session_token
    with get_db() as db:
        merchant = db.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,)).fetchone()
        return merchant

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, error: str = None):
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={"error": error}
    )

@app.post("/admin/login")
async def admin_login(request: Request, response: Response, email: str = Form(...), password: str = Form(...)):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    with get_db() as db:
        merchant = db.execute("SELECT * FROM merchants WHERE email = ? AND password_hash = ?", (email, password_hash)).fetchone()
        
    if not merchant:
        return RedirectResponse(url="/admin/login?error=Invalid+credentials", status_code=status.HTTP_303_SEE_OTHER)
        
    # Set a simple cookie (insecure for real prod, but fine for MVP)
    resp = RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(key="admin_session", value=str(merchant['id']), httponly=True)
    return resp

@app.get("/admin/logout")
async def admin_logout(response: Response):
    resp = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("admin_session")
    return resp

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    merchant = get_current_merchant(request)
    if not merchant:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        
    with get_db() as db:
        bookings_raw = db.execute('''
            SELECT b.*, s.name as service_name, s.price, s.deposit_amount, s.deposit_type 
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            WHERE s.merchant_id = ?
            ORDER BY b.created_at DESC
        ''', (merchant['id'],)).fetchall()
        
        bookings = []
        now = datetime.utcnow()
        for b in bookings_raw:
            b_dict = dict(b)
            if b_dict['status'] == 'pending':
                created_at_dt = datetime.strptime(b_dict['created_at'], "%Y-%m-%d %H:%M:%S")
                elapsed = (now - created_at_dt).total_seconds()
                b_dict['remaining_seconds'] = max(0, int((10 * 60) - elapsed))
            bookings.append(b_dict)
            
        # Calculate KPIs
        kpis = {
            "total_bookings": len(bookings),
            "pending_holds": sum(1 for b in bookings if b['status'] == 'pending'),
            "deposits_collected": 0,
            "total_revenue": 0
        }
        
        for b in bookings:
            if b['status'] in ('paid', 'done'):
                kpis['total_revenue'] += b['price']
                
                # Calculate deposit for this booking
                if b['deposit_type'] == 'percentage':
                    kpis['deposits_collected'] += int(b['price'] * (b['deposit_amount'] / 100.0))
                else:
                    kpis['deposits_collected'] += b['deposit_amount']
                    
        # Fetch merchant services
        merchant_services = db.execute("SELECT * FROM services WHERE merchant_id = ?", (merchant['id'],)).fetchall()
                    
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "merchant": merchant,
            "bookings": bookings,
            "kpis": kpis,
            "merchant_services": merchant_services
        }
    )

@app.post("/admin/booking/{booking_id}/done")
async def mark_booking_done(request: Request, booking_id: int):
    merchant = get_current_merchant(request)
    if not merchant:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        
    with get_db() as db:
        # Verify ownership
        booking = db.execute('''
            SELECT b.id FROM bookings b
            JOIN services s ON b.service_id = s.id
            WHERE b.id = ? AND s.merchant_id = ?
        ''', (booking_id, merchant['id'])).fetchone()
        
        if booking:
            db.execute("UPDATE bookings SET status = 'done' WHERE id = ?", (booking_id,))
            db.commit()
            
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/services/add")
async def add_service(
    request: Request,
    name: str = Form(...),
    duration_mins: int = Form(...),
    price: int = Form(...),
    deposit_type: str = Form(...),
    deposit_amount: int = Form(...)
):
    merchant = get_current_merchant(request)
    if not merchant:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        
    # Convert dollars to cents (price input is in dollars)
    price_cents = price * 100
    
    # If flat deposit, convert to cents too
    if deposit_type == 'flat':
        deposit_amount = deposit_amount * 100
        
    with get_db() as db:
        db.execute('''
            INSERT INTO services (merchant_id, name, duration_mins, price, deposit_type, deposit_amount)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (merchant['id'], name, duration_mins, price_cents, deposit_type, deposit_amount))
        db.commit()
        
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/services/{service_id}/delete")
async def delete_service(request: Request, service_id: int):
    merchant = get_current_merchant(request)
    if not merchant:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        
    with get_db() as db:
        # Only delete if it belongs to this merchant
        db.execute("DELETE FROM services WHERE id = ? AND merchant_id = ?", (service_id, merchant['id']))
        db.commit()
        
    return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin/export/csv")
async def export_bookings_csv(request: Request):
    merchant = get_current_merchant(request)
    if not merchant:
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    with get_db() as db:
        bookings = db.execute('''
            SELECT b.reference_code, b.customer_name, b.customer_phone, 
                   s.name as service_name, b.booking_date, b.start_time, b.status, b.created_at
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            WHERE s.merchant_id = ?
            ORDER BY b.created_at DESC
        ''', (merchant['id'],)).fetchall()

    # Create CSV in memory
    output = io.StringIO()
    # Add UTF-8 BOM so Excel opens it correctly
    output.write('\ufeff')
    
    writer = csv.writer(output)
    writer.writerow(['Reference Code', 'Customer Name', 'Phone', 'Service', 'Date', 'Time', 'Status', 'Booked At'])
    
    for b in bookings:
        writer.writerow([
            b['reference_code'],
            b['customer_name'],
            b['customer_phone'],
            b['service_name'],
            b['booking_date'],
            b['start_time'],
            b['status'],
            b['created_at']
        ])
        
    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="bookings_export.csv"'
    }
    
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)
