"""Token-request transports with browser-grade TLS stacks.

Since 2026-07 Tesla's auth edge fingerprints the TLS handshake of requests to
the token endpoint; tokens minted over Python's OpenSSL handshake are later
rejected by owner-api with 403. Instead of a third-party impersonation wheel,
we prefer system-provided stacks:

  swift  — Apple URLSession (same TLS family as Safari and the official Tesla
           iOS app), run from auditable source via `swift <script>`
  curl   — /usr/bin/curl (Apple-shipped, LibreSSL)
  urllib — Python stdlib; last resort, known to be fingerprinted

Only token requests go through this module; orders/tasks calls stay in app.api.
"""

import json
import shutil
import subprocess
import urllib.parse
from pathlib import Path

SWIFT_HELPER = Path(__file__).resolve().parent / "token_post.swift"
CURL_BIN = "/usr/bin/curl"
TIMEOUT = 60


class TokenTransportError(Exception):
    """status is the HTTP status code when the endpoint answered >= 400,
    None when no transport got an answer at all (network failure)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _clt_installed():
    try:
        return subprocess.run(
            ["/usr/bin/xcode-select", "-p"], capture_output=True
        ).returncode == 0
    except OSError:
        return False


def swift_available(which=shutil.which, clt_installed=_clt_installed):
    # /usr/bin/swift exists as a stub even without Xcode CLT; running the stub
    # pops an install dialog, so require an actual CLT path before using swift.
    return which("swift") is not None and clt_installed()


def transport_order(swift_available):
    order = ["curl", "urllib"]
    if swift_available:
        order.insert(0, "swift")
    return order


def build_curl_argv(url, body, headers):
    argv = [CURL_BIN, "--silent", "--show-error", "--max-time", str(TIMEOUT),
            "--write-out", "\n%{http_code}", "--data-binary", "@-"]
    for name, value in (headers or {}).items():
        argv += ["--header", f"{name}: {value}"]
    argv.append(url)
    return argv


def _post_via_curl(url, body, headers):
    result = subprocess.run(
        build_curl_argv(url, body, headers),
        input=body, capture_output=True, timeout=TIMEOUT + 10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.decode(errors='replace').strip()}")
    out = result.stdout.decode("utf-8", errors="replace")
    payload, _, status_line = out.rpartition("\n")
    return int(status_line.strip() or 0), payload


def _post_via_swift(url, body, headers):
    argv = ["swift", str(SWIFT_HELPER), url]
    for name, value in (headers or {}).items():
        argv.append(f"{name}: {value}")
    result = subprocess.run(argv, input=body, capture_output=True, timeout=TIMEOUT + 60)
    if result.returncode != 0:
        raise RuntimeError(f"swift helper failed: {result.stderr.decode(errors='replace').strip()[:300]}")
    out = result.stdout.decode("utf-8", errors="replace")
    status_line, _, payload = out.partition("\n")
    return int(status_line.strip() or 0), payload


def _post_via_urllib(url, body, headers):
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


_IMPLS = {"swift": _post_via_swift, "curl": _post_via_curl, "urllib": _post_via_urllib}


def token_post(url, fields, headers=None, impls=None, order=None):
    """POST form fields via the first working transport.

    Returns (parsed_json, transport_name). Raises TokenTransportError when the
    endpoint returns an HTTP error or every transport fails.
    """
    impls = impls or _IMPLS
    if order is None:
        order = [t for t in transport_order(swift_available()) if t in impls]
    body = urllib.parse.urlencode(fields).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}

    attempts = []
    for name in order:
        try:
            status, payload = impls[name](url, body, headers)
        except Exception as e:
            attempts.append(f"{name}: {e}")
            continue
        if status >= 400:
            raise TokenTransportError(
                f"token endpoint returned {status} via {name}: {payload[:300]}",
                status=status,
            )
        try:
            return json.loads(payload), name
        except json.JSONDecodeError as e:
            attempts.append(f"{name}: invalid JSON ({e})")
    raise TokenTransportError(
        "all token transports failed — " + "; ".join(attempts)
    )
