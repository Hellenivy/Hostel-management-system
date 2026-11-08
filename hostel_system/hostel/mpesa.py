import requests
import base64
from datetime import datetime
from django.conf import settings


def get_access_token():
    credentials = (
        f"{settings.MPESA_CONSUMER_KEY}:"
        f"{settings.MPESA_CONSUMER_SECRET}"
    )

    encoded_credentials = base64.b64encode(
        credentials.encode()
    ).decode()

    response = requests.get(
        f"{settings.MPESA_BASE_URL}/oauth/v1/generate",
        params={"grant_type": "client_credentials"},
        headers={
            "Authorization": f"Basic {encoded_credentials}"
        },
        timeout=30,
    )

    response.raise_for_status()
    return response.json()["access_token"]


def generate_password(timestamp):
    password_string = (
        f"{settings.MPESA_SHORTCODE}"
        f"{settings.MPESA_PASSKEY}"
        f"{timestamp}"
    )

    return base64.b64encode(
        password_string.encode()
    ).decode()


def format_phone_number(phone):
    # Daraja only accepts 2547XXXXXXXX / 2541XXXXXXXX.
    digits = "".join(ch for ch in str(phone) if ch.isdigit())

    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits

    if len(digits) != 12 or not digits.startswith(("2547", "2541")):
        return None

    return digits


def build_callback_url():
    # Daraja does not sign callbacks, so a secret path segment is what
    # proves a callback came from Safaricom and not from an attacker.
    token = settings.MPESA_CALLBACK_TOKEN

    if not token:
        raise ValueError("MPESA_CALLBACK_TOKEN is not configured.")

    return f"{settings.MPESA_CALLBACK_URL.rstrip('/')}/{token}/"


def initiate_stk_push(phone, amount, tenant_id):
    # Clean the phone number into the 2547XXXXXXXX format Daraja needs.
    phone = format_phone_number(phone)
    if phone is None:
        raise ValueError("Invalid phone number")

    callback_url = build_callback_url()
    access_token = get_access_token()

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = generate_password(timestamp)

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": settings.MPESA_SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        "AccountReference": f"TENANT-{tenant_id}",
        "TransactionDesc": "Hostel Rent Payment",
    }

    response = requests.post(
        f"{settings.MPESA_BASE_URL}/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        timeout=30,
    )

    # Daraja returns its error details as JSON on 4xx/5xx, so read them
    # instead of raising and losing the errorMessage.
    try:
        return response.json()
    except ValueError:
        response.raise_for_status()
        raise


def query_stk_push(checkout_request_id):
    access_token = get_access_token()

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = generate_password(timestamp)

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }

    response = requests.post(
        f"{settings.MPESA_BASE_URL}/mpesa/stkpushquery/v1/query",
        json=payload,
        headers={
            "Authorization": f"Bearer {access_token}"
        },
        timeout=30,
    )

    response.raise_for_status()
    return response.json()
