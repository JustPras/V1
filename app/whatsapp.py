import os
import requests

# Retrieve keys from environment variables
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "mock_token")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "mock_phone_id")

def send_whatsapp_reminder(phone_number: str, customer_name: str, service_name: str, date: str, time: str, reminder_type: str):
    """
    Scaffolding for sending WhatsApp messages via Meta Cloud API.
    reminder_type can be 'H-7', 'H-1', or 'DAY-OF'.
    """
    
    print(f"[WhatsApp API] Preparing {reminder_type} reminder for {customer_name} ({phone_number})...")
    
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # We map reminder_type to specific approved Meta Message Templates
    template_name = "slotarmor_reminder" # Dummy template name
    
    # Ensure phone number formatting (must be E.164 without '+')
    # Example: "+62812..." -> "62812..."
    clean_phone = phone_number.replace("+", "").replace("-", "").replace(" ", "")
    
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": "id" # Indonesian
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": customer_name},
                        {"type": "text", "text": service_name},
                        {"type": "text", "text": f"{date} jam {time}"},
                        {"type": "text", "text": reminder_type}
                    ]
                }
            ]
        }
    }
    
    # --- MOCK MODE ---
    if WHATSAPP_TOKEN == "mock_token":
        print(f"[WhatsApp API - MOCK] Simulated sending to {clean_phone}: Halo {customer_name}, pengingat {reminder_type} untuk {service_name} pada {date} {time}.")
        return {"status": "mock_success"}
        
    # --- PRODUCTION MODE ---
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        print(f"[WhatsApp API - SUCCESS] Sent to {clean_phone}")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[WhatsApp API - ERROR] Failed to send message: {e}")
        return {"error": str(e)}
