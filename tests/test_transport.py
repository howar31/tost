import unittest

from app import transport


class TestCurlArgs(unittest.TestCase):
    def test_curl_argv_posts_form_with_headers(self):
        argv = transport.build_curl_argv(
            "https://auth.tesla.com/oauth2/v3/token",
            b"grant_type=refresh_token",
            {"User-Agent": "Tesla/4.55.5"},
        )
        self.assertEqual(argv[0], "/usr/bin/curl")
        self.assertIn("https://auth.tesla.com/oauth2/v3/token", argv)
        self.assertIn("--data-binary", argv)
        joined = " ".join(argv)
        self.assertIn("User-Agent: Tesla/4.55.5", joined)
        # must emit status line separate from body
        self.assertIn("%{http_code}", joined)


class TestSwiftAvailable(unittest.TestCase):
    # /usr/bin/swift exists as a stub even without Xcode CLT; running it pops
    # an install dialog, so swift must only be preferred when CLT is present.
    def test_swift_binary_without_clt_not_available(self):
        self.assertFalse(transport.swift_available(
            which=lambda name: "/usr/bin/swift", clt_installed=lambda: False))

    def test_swift_binary_with_clt_available(self):
        self.assertTrue(transport.swift_available(
            which=lambda name: "/usr/bin/swift", clt_installed=lambda: True))

    def test_missing_swift_binary_not_available(self):
        self.assertFalse(transport.swift_available(
            which=lambda name: None, clt_installed=lambda: True))


class TestTokenTransportErrorStatus(unittest.TestCase):
    def test_http_error_carries_status_code(self):
        def fake(url, body, headers):
            return 401, '{"error": "invalid_grant"}'

        with self.assertRaises(transport.TokenTransportError) as ctx:
            transport.token_post("https://x", {}, impls={"curl": fake}, order=["curl"])
        self.assertEqual(ctx.exception.status, 401)

    def test_transport_failure_has_no_status(self):
        def boom(url, body, headers):
            raise RuntimeError("offline")

        with self.assertRaises(transport.TokenTransportError) as ctx:
            transport.token_post("https://x", {}, impls={"curl": boom}, order=["curl"])
        self.assertIsNone(ctx.exception.status)


class TestTransportChain(unittest.TestCase):
    def test_prefers_swift_when_available(self):
        order = transport.transport_order(swift_available=True)
        self.assertEqual(order[0], "swift")
        self.assertEqual(order[-1], "urllib")

    def test_skips_swift_when_unavailable(self):
        order = transport.transport_order(swift_available=False)
        self.assertNotIn("swift", order)
        self.assertEqual(order[0], "curl")

    def test_token_post_uses_first_working_transport(self):
        calls = []

        def fake_swift(url, body, headers):
            calls.append("swift")
            raise RuntimeError("swift not installed")

        def fake_curl(url, body, headers):
            calls.append("curl")
            return 200, '{"access_token": "tok"}'

        result, used = transport.token_post(
            "https://auth.tesla.com/oauth2/v3/token",
            {"grant_type": "x"},
            impls={"swift": fake_swift, "curl": fake_curl},
            order=["swift", "curl"],
        )
        self.assertEqual(result["access_token"], "tok")
        self.assertEqual(used, "curl")
        self.assertEqual(calls, ["swift", "curl"])

    def test_http_error_status_raises_with_body(self):
        def fake(url, body, headers):
            return 400, '{"error": "invalid_grant"}'

        with self.assertRaises(transport.TokenTransportError) as ctx:
            transport.token_post(
                "https://x", {}, impls={"curl": fake}, order=["curl"]
            )
        self.assertIn("invalid_grant", str(ctx.exception))

    def test_all_transports_failing_reports_each_attempt(self):
        def boom(url, body, headers):
            raise RuntimeError("nope")

        with self.assertRaises(transport.TokenTransportError) as ctx:
            transport.token_post(
                "https://x", {}, impls={"curl": boom, "urllib": boom},
                order=["curl", "urllib"],
            )
        message = str(ctx.exception)
        self.assertIn("curl", message)
        self.assertIn("urllib", message)


if __name__ == "__main__":
    unittest.main()
