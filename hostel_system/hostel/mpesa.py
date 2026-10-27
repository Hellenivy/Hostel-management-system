
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


def initiate_stk_push(phone, amount, tenant_id):
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
        "CallBackURL": settings.MPESA_CALLBACK_URL,
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

    response.raise_for_status()
    return response.json()


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
