"""OAuth2 PKCE auth against auth.tesla.com + macOS Keychain token storage.

The only credentials this module ever sees are the OAuth authorization code
(pasted by the user from the redirect URL) and the resulting tokens. The Tesla
password is typed exclusively on tesla.com in the user's browser. Tokens live
in the login Keychain, never in plaintext files.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse

from app.api import USER_AGENT, X_TESLA_USER_AGENT
from app.transport import TokenTransportError, token_post


def _token_request(fields):
    """Token-endpoint POST via a browser-grade TLS transport (see app.transport)."""
    headers = {"User-Agent": USER_AGENT, "X-Tesla-User-Agent": X_TESLA_USER_AGENT}
    result, used = token_post(TOKEN_URL, fields, headers=headers)
    if used == "urllib":
        print(
            "[!] token obtained via plain Python TLS — Tesla may reject it "
            "with 403; install Xcode CLT (`xcode-select --install`) so the "
            "swift transport can be used",
            file=sys.stderr,
        )
    return result

AUTH_URL = "https://auth.tesla.com/oauth2/v3/authorize"
TOKEN_URL = "https://auth.tesla.com/oauth2/v3/token"
CLIENT_ID = "ownerapi"
# Tesla delisted https://auth.tesla.com/void/callback for ownerapi (2026-07);
# only the app scheme is accepted now. Browsers won't follow tesla:// — the
# user copies the callback URL out of DevTools instead.
REDIRECT_URI = "tesla://auth/callback"
SCOPE = "openid email offline_access"

EXP_LEEWAY_SECONDS = 30


class AuthRequired(Exception):
    """Raised when no usable token exists and interactive login is needed."""


class BadRedirectUrl(Exception):
    """Pasted URL is not a usable post-login callback URL; message says why."""


def extract_auth_code(redirected_url):
    """Pull the authorization code out of the pasted callback URL.

    Raises BadRedirectUrl with a targeted explanation for the common mistakes.
    """
    url = redirected_url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https", "tesla"):
        raise BadRedirectUrl("that is not a URL — paste the full callback address (it starts with tesla:// or https://)")
    if "/authorize" in parsed.path:
        raise BadRedirectUrl(
            "that is the login page URL itself — first complete the Tesla login "
            "in the browser, then copy the URL of the \"Page Not Found\" page "
            "you land on afterwards (it contains code=...)"
        )
    code_values = urllib.parse.parse_qs(parsed.query).get("code")
    if not code_values:
        raise BadRedirectUrl(
            "no code= parameter in that URL — copy the address of the page you "
            "reach right after login completes"
        )
    return code_values[0]


def generate_pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def token_expired(access_token, now=None):
    """True when the JWT exp is past (or within leeway). Garbage = expired.

    No signature check: the token is consumed locally only, to decide whether
    to refresh before calling Tesla.
    """
    now = time.time() if now is None else now
    try:
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload["exp"] <= now + EXP_LEEWAY_SECONDS
    except Exception:
        return True


def _run_security(args, stdin=None):
    result = subprocess.run(
        ["security"] + args, input=stdin, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


class KeychainTokenStore:
    SERVICE = "local.tost.tesla-tokens"
    ACCOUNT = "tost"

    def __init__(self, runner=None):
        self._run = runner or _run_security

    def load(self):
        try:
            out = self._run(
                ["find-generic-password", "-a", self.ACCOUNT, "-s", self.SERVICE, "-w"]
            )
        except Exception:
            return None
        out = out.strip()
        if not out:
            return None
        if not out.startswith("{"):  # current base64 format ("{" = legacy raw JSON)
            out = base64.b64decode(out).decode()
        return json.loads(out)

    def save(self, tokens):
        # The secret rides stdin (`security -i` batch mode) because argv is
        # visible in the process list. base64 keeps the payload a single token
        # for security's command parser.
        payload = base64.b64encode(
            json.dumps(tokens, separators=(",", ":")).encode()
        ).decode()
        self._run(
            ["-i"],
            stdin=(
                f"add-generic-password -a {self.ACCOUNT} -s {self.SERVICE} "
                f"-w {payload} -U\n"  # -U: update in place if the item exists
            ),
        )

    def delete(self):
        try:
            self._run(
                ["delete-generic-password", "-a", self.ACCOUNT, "-s", self.SERVICE]
            )
        except Exception:
            pass


def interactive_login(token_store=None):
    """Full browser-based PKCE login. Returns the token dict."""
    token_store = token_store or KeychainTokenStore()
    verifier, challenge = generate_pkce_pair()
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": os.urandom(16).hex(),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    # Deliberately NOT auto-opening the browser: with an active Tesla session
    # the tesla:// redirect fires the instant the page loads, so DevTools must
    # be recording BEFORE navigation or the callback URL is lost.
    print("Steps (order matters):", file=sys.stderr)
    print("  1. Open a NEW browser tab, then DevTools (Cmd+Option+I) -> Network", file=sys.stderr)
    print("     tab, tick \"Preserve log\", filter for: callback", file=sys.stderr)
    print("  2. Now paste this URL into that tab's address bar:", file=sys.stderr)
    print(f"\n{url}\n", file=sys.stderr)
    print("  3. Already logged in? It redirects instantly — no login needed.", file=sys.stderr)
    print("     Otherwise complete the Tesla login (password + MFA).", file=sys.stderr)
    print("  4. The redirect to tesla://auth/callback?code=... cannot be opened", file=sys.stderr)
    print("     by the browser but shows up in the Network list (red/cancelled,", file=sys.stderr)
    print("     or in the Location header of the last /authorize request).", file=sys.stderr)
    print("  5. Copy that full tesla://auth/callback?code=... URL, paste it here.", file=sys.stderr)
    code = None
    for _ in range(3):
        redirected = input("Redirected URL: ").strip()
        try:
            code = extract_auth_code(redirected)
            break
        except BadRedirectUrl as e:
            print(f"[!] {e}", file=sys.stderr)
    if code is None:
        raise AuthRequired("could not get an authorization code after 3 attempts")
    tokens = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    )
    token_store.save(tokens)
    print("Tokens saved to macOS Keychain.", file=sys.stderr)
    return tokens


def get_access_token(token_store=None, token_request=None):
    """Return a valid access token, refreshing via Keychain-stored refresh token.

    Raises AuthRequired when interactive login is needed. A refresh attempt
    that fails without the endpoint rejecting the token (network down, auth
    server 5xx) propagates as TokenTransportError instead: the refresh token
    is still good, so callers must treat it as transient, not re-prompt login.
    """
    token_store = token_store or KeychainTokenStore()
    token_request = token_request or _token_request
    tokens = token_store.load()
    if not tokens or "refresh_token" not in tokens:
        raise AuthRequired("no tokens in Keychain — run: tost auth")
    access = tokens.get("access_token", "")
    if not token_expired(access):
        return access
    try:
        refreshed = token_request(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": tokens["refresh_token"],
            }
        )
    except TokenTransportError as e:
        if e.status is not None and 400 <= e.status < 500:
            raise AuthRequired(f"refresh token rejected — run: tost auth ({e})")
        raise
    tokens.update(refreshed)
    token_store.save(tokens)
    return tokens["access_token"]
