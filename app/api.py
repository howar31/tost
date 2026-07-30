"""Tesla API client. The only module that talks to the network.

Outbound hosts are limited to auth.tesla.com (token exchange, called via
post_form from app.auth), owner-api.teslamotors.com and
akamai-apigateway-vfx.tesla.com. Headers mimic the official mobile app.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# /tasks rejects retired build numbers with 403 "Update App"; a far-future
# version stops the chase.
TESLA_APP_VERSION = "9.99.9-9999"
USER_AGENT = "Tesla/4.55.5 (com.teslamotors.tesla; build:4193; Android 14)"
X_TESLA_USER_AGENT = "TeslaApp/4.55.5-4193/4193/android/14"

ORDERS_URL = "https://owner-api.teslamotors.com/api/1/users/orders"
DETAILS_URL = "https://akamai-apigateway-vfx.tesla.com/tasks"

REQUEST_TIMEOUT = 30


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Unauthorized(ApiError):
    pass


def _urllib_fetch(url, headers, data):
    """Real network call. Returns (status, body_text); raises OSError on network failure."""
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def build_headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": USER_AGENT,
        "X-Tesla-User-Agent": X_TESLA_USER_AGENT,
        "X-Request-Id": str(uuid.uuid4()),
    }


def build_details_url(reference_number, locale):
    language, country = "en", "US"
    if locale:
        parts = locale.replace("_", "-").split("-")
        if parts[0]:
            language = parts[0].lower()
        if len(parts) > 1 and parts[1]:
            country = parts[1].upper()
    query = urllib.parse.urlencode(
        {
            "deviceLanguage": language,
            "deviceCountry": country,
            "referenceNumber": reference_number,
            "appVersion": TESLA_APP_VERSION,
        }
    )
    return f"{DETAILS_URL}?{query}"


def request_json(url, headers=None, data=None, retries=3, sleep=time.sleep, fetch=None):
    """GET/POST returning parsed JSON. Retries 5xx and network errors with
    backoff; 401 raises Unauthorized immediately; other 4xx raise ApiError."""
    fetch = fetch or _urllib_fetch
    last_error = None
    for attempt in range(retries):
        if attempt:
            sleep(2 ** attempt)
        try:
            status, body = fetch(url, headers, data)
        except OSError as e:
            last_error = ApiError(f"network error: {e}")
            continue
        if status == 401:
            raise Unauthorized("401 unauthorized", status=401)
        if status >= 500:
            last_error = ApiError(f"server error {status}", status=status)
            continue
        if status >= 400:
            raise ApiError(f"request failed {status}: {body[:200]}", status=status)
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise ApiError(f"invalid JSON in response: {e}")
    raise last_error


def post_form(url, fields, fetch=None):
    """POST application/x-www-form-urlencoded (OAuth token endpoint)."""
    data = urllib.parse.urlencode(fields).encode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }
    return request_json(url, headers=headers, data=data, fetch=fetch)


def fetch_snapshot(access_token, fetch=None):
    """Orders list + per-order details, keyed by referenceNumber."""
    headers = build_headers(access_token)
    orders = request_json(ORDERS_URL, headers=headers, fetch=fetch).get("response", [])
    snapshot = {}
    for order in orders:
        ref = order.get("referenceNumber")
        if not ref:
            continue
        url = build_details_url(ref, order.get("locale"))
        details = request_json(url, headers=build_headers(access_token), fetch=fetch)
        snapshot[ref] = {"order": order, "details": details}
    return snapshot
