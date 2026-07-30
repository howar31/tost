import base64
import hashlib
import json
import time
import unittest

from app.auth import (
    AuthRequired,
    KeychainTokenStore,
    generate_pkce_pair,
    get_access_token,
    token_expired,
)
from app.transport import TokenTransportError


def make_jwt(exp):
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": exp}).encode()
    ).rstrip(b"=")
    return b".".join([header, payload, b"sig"]).decode()


class TestPkce(unittest.TestCase):
    def test_challenge_is_s256_of_verifier(self):
        verifier, challenge = generate_pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.assertEqual(challenge, expected)

    def test_verifier_unique_per_call(self):
        v1, _ = generate_pkce_pair()
        v2, _ = generate_pkce_pair()
        self.assertNotEqual(v1, v2)


class TestTokenExpired(unittest.TestCase):
    def test_future_exp_not_expired(self):
        self.assertFalse(token_expired(make_jwt(time.time() + 3600)))

    def test_past_exp_expired(self):
        self.assertTrue(token_expired(make_jwt(time.time() - 10)))

    def test_exp_within_leeway_treated_as_expired(self):
        # 30s leeway: a token about to lapse mid-request counts as expired
        self.assertTrue(token_expired(make_jwt(time.time() + 5)))

    def test_garbage_token_treated_as_expired(self):
        self.assertTrue(token_expired("not-a-jwt"))


class FakeRunner:
    """Records security-CLI invocations; returns canned stdout per subcommand."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, args, stdin=None):
        self.calls.append((args, stdin))
        sub = args[0]
        if sub in self.responses:
            return self.responses[sub]
        return ""


class TestKeychainTokenStore(unittest.TestCase):
    def test_save_sends_secret_via_stdin_not_argv(self):
        # argv is visible in the process list; the token JSON must ride stdin
        # (base64-wrapped so `security -i` tokenization cannot mangle it)
        runner = FakeRunner()
        store = KeychainTokenStore(runner=runner)
        store.save({"access_token": "a", "refresh_token": "r"})
        args, stdin = runner.calls[0]
        self.assertEqual(args, ["-i"])
        self.assertIn("add-generic-password", stdin)
        self.assertIn(KeychainTokenStore.SERVICE, stdin)
        self.assertIn("-U", stdin)
        self.assertNotIn("refresh_token", " ".join(args))
        payload = stdin.split("-w ", 1)[1].split()[0]
        self.assertEqual(json.loads(base64.b64decode(payload))["refresh_token"], "r")

    def test_load_parses_legacy_plain_json_payload(self):
        runner = FakeRunner(
            responses={"find-generic-password": '{"access_token": "a"}\n'}
        )
        store = KeychainTokenStore(runner=runner)
        self.assertEqual(store.load(), {"access_token": "a"})

    def test_load_parses_base64_payload(self):
        payload = base64.b64encode(b'{"access_token": "a"}').decode()
        runner = FakeRunner(responses={"find-generic-password": payload + "\n"})
        store = KeychainTokenStore(runner=runner)
        self.assertEqual(store.load(), {"access_token": "a"})

    def test_load_returns_none_when_item_missing(self):
        def failing_runner(args, stdin=None):
            raise RuntimeError("The specified item could not be found")

        store = KeychainTokenStore(runner=failing_runner)
        self.assertIsNone(store.load())


class FakeTokenStore:
    def __init__(self, tokens):
        self.tokens = tokens
        self.saved = None

    def load(self):
        return self.tokens

    def save(self, tokens):
        self.saved = tokens


class TestGetAccessTokenRefresh(unittest.TestCase):
    def _store_with_expired_access(self):
        return FakeTokenStore(
            {"access_token": make_jwt(time.time() - 10), "refresh_token": "r1"}
        )

    def test_4xx_refresh_rejection_raises_auth_required(self):
        def reject(fields):
            raise TokenTransportError("token endpoint returned 400", status=400)

        with self.assertRaises(AuthRequired):
            get_access_token(self._store_with_expired_access(), token_request=reject)

    def test_network_failure_during_refresh_is_not_auth_required(self):
        # offline box: refresh token is still valid, must NOT prompt re-login
        def offline(fields):
            raise TokenTransportError("all token transports failed")

        with self.assertRaises(TokenTransportError):
            get_access_token(self._store_with_expired_access(), token_request=offline)

    def test_5xx_during_refresh_is_not_auth_required(self):
        def outage(fields):
            raise TokenTransportError("token endpoint returned 502", status=502)

        with self.assertRaises(TokenTransportError):
            get_access_token(self._store_with_expired_access(), token_request=outage)

    def test_successful_refresh_saves_and_returns_new_token(self):
        fresh = make_jwt(time.time() + 3600)

        def ok(fields):
            self.assertEqual(fields["grant_type"], "refresh_token")
            self.assertEqual(fields["refresh_token"], "r1")
            return {"access_token": fresh, "refresh_token": "r2"}

        store = self._store_with_expired_access()
        self.assertEqual(get_access_token(store, token_request=ok), fresh)
        self.assertEqual(store.saved["refresh_token"], "r2")


if __name__ == "__main__":
    unittest.main()
