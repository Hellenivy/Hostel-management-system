import requests
from django.conf import settings


def _messaging_url():
    # Africa's Talking serves the sandbox from a separate host.
    if settings.AT_USERNAME == "sandbox":
        return "https://api.sandbox.africastalking.com/version1/messaging"
    return "https://api.africastalking.com/version1/messaging"


def send_sms(phone, message):
    """Send one SMS. `phone` must be 2547XXXXXXXX / 2541XXXXXXXX.

    Returns (ok, detail) where detail is the provider's status or error.
    """
    if not settings.AT_API_KEY:
        raise ValueError("AT_API_KEY is not configured.")

    data = {
        "username": settings.AT_USERNAME,
        "to": f"+{phone}",
        "message": message,
    }

    if settings.AT_SENDER_ID:
        data["from"] = settings.AT_SENDER_ID

    response = requests.post(
        _messaging_url(),
        data=data,
        headers={
            "apiKey": settings.AT_API_KEY,
            "Accept": "application/json",
        },
        timeout=30,
    )

    try:
        body = response.json()
    except ValueError:
        return False, f"HTTP {response.status_code}: {response.text[:200]}"

    recipients = body.get("SMSMessageData", {}).get("Recipients", [])

    if not recipients:
        return False, body.get("SMSMessageData", {}).get("Message", "No recipients")

    status = recipients[0].get("status", "")
    # 100 Processed, 101 Sent, 102 Queued are all accepted by the gateway.
    ok = recipients[0].get("statusCode") in (100, 101, 102)
    return ok, status
