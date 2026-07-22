"""
mpesa.py, Safaricom Daraja API wrapper (STK Push / Lipa na M-Pesa Online)

Environment variables required:
    MPESA_CONSUMER_KEY     , from developer.safaricom.co.ke app
    MPESA_CONSUMER_SECRET  , from developer.safaricom.co.ke app
    MPESA_SHORTCODE        , your Paybill or Till number
    MPESA_PASSKEY          , from Safaricom portal (sandbox or live)
    MPESA_CALLBACK_URL     , public HTTPS URL, e.g. https://kali.tail3ceaef.ts.net/mpesa/callback
    MPESA_ENV              , "sandbox" (default) or "production"
"""

import os
import base64
import hashlib
import requests
from datetime import datetime

_ENV        = os.environ.get("MPESA_ENV", "sandbox")
_BASE       = ("https://sandbox.safaricom.co.ke" if _ENV == "sandbox"
               else "https://api.safaricom.co.ke")

CONSUMER_KEY    = os.environ.get("MPESA_CONSUMER_KEY", "")
CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
SHORTCODE       = os.environ.get("MPESA_SHORTCODE", "174379")   # Safaricom sandbox default
PASSKEY         = os.environ.get("MPESA_PASSKEY", "")
CALLBACK_URL    = os.environ.get("MPESA_CALLBACK_URL", "")

MPESA_OK = bool(CONSUMER_KEY and CONSUMER_SECRET and PASSKEY and CALLBACK_URL)

# Monthly Pro price in KES (≈ $29 at 130 KES/USD)
PRO_MONTHLY_KES  = int(os.environ.get("PRO_MONTHLY_KES", "3500"))
PRO_ANNUAL_KES   = int(os.environ.get("PRO_ANNUAL_KES",  "23000"))
# Plus tier, same ~121 KES/USD rate as Pro above (≈ $12 / $9-equivalent annual)
PLUS_MONTHLY_KES = int(os.environ.get("PLUS_MONTHLY_KES", "1450"))
PLUS_ANNUAL_KES  = int(os.environ.get("PLUS_ANNUAL_KES",  "13000"))


def _get_token() -> str:
    """Fetch OAuth access token from Safaricom."""
    creds = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode()
    r = requests.get(
        f"{_BASE}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {creds}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _password_and_timestamp():
    """Generate STK Push password and timestamp."""
    ts  = datetime.now().strftime("%Y%m%d%H%M%S")
    raw = f"{SHORTCODE}{PASSKEY}{ts}".encode()
    pwd = base64.b64encode(raw).decode()
    return pwd, ts


def stk_push(phone: str, amount: int, account_ref: str, description: str) -> dict:
    """
    Initiate Lipa na M-Pesa Online (STK Push).

    phone      , customer phone, format 254XXXXXXXXX
    amount     , integer KES amount
    account_ref, shown on customer's phone (e.g. "BullLogic Pro")
    description, shown on customer's phone (e.g. "30-day Pro access")

    Returns Safaricom's response dict. Key fields:
        CheckoutRequestID, store this to match the callback
        ResponseCode == "0" means request accepted (not yet paid)
    """
    if not MPESA_OK:
        raise RuntimeError("M-Pesa not configured, set MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_PASSKEY, MPESA_CALLBACK_URL")

    token       = _get_token()
    password, ts = _password_and_timestamp()

    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password":          password,
        "Timestamp":         ts,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            phone,
        "PartyB":            SHORTCODE,
        "PhoneNumber":       phone,
        "CallBackURL":       CALLBACK_URL,
        "AccountReference":  account_ref[:12],
        "TransactionDesc":   description[:13],
    }
    r = requests.post(
        f"{_BASE}/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def query_status(checkout_request_id: str) -> dict:
    """
    Query the status of a pending STK Push.
    ResultCode == "0" means payment succeeded.
    """
    if not MPESA_OK:
        raise RuntimeError("M-Pesa not configured")

    token        = _get_token()
    password, ts = _password_and_timestamp()

    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password":          password,
        "Timestamp":         ts,
        "CheckoutRequestID": checkout_request_id,
    }
    r = requests.post(
        f"{_BASE}/mpesa/stkpushquery/v1/query",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()
