from twilio.rest import Client
import os

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"  # Twilio sandbox
client = Client(TWILIO_SID, TWILIO_AUTH)

def send_whatsapp(to, message):
    print(f"[WA] Attempt → to={to} | msg={message}")

    if not to:
        print("[WA] ❌ Skipped: No mobile number")
        return

    try:
        msg = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{to}"
        )

        print(f"[WA] ✅ SUCCESS → to={to} | SID={msg.sid}")

    except Exception as e:
        print(f"[WA] ❌ ERROR → to={to} | error={str(e)}")