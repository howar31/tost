import unittest

from app.auth import BadRedirectUrl, extract_auth_code


class TestExtractAuthCode(unittest.TestCase):
    def test_valid_callback_url_returns_code(self):
        url = "https://auth.tesla.com/void/callback?code=NA_abc123&state=xyz"
        self.assertEqual(extract_auth_code(url), "NA_abc123")

    def test_authorize_url_pasted_gives_targeted_message(self):
        url = "https://auth.tesla.com/oauth2/v3/authorize?client_id=ownerapi&state=x"
        with self.assertRaises(BadRedirectUrl) as ctx:
            extract_auth_code(url)
        self.assertIn("login page", str(ctx.exception))

    def test_callback_url_without_code_reports_missing_code(self):
        url = "https://auth.tesla.com/void/callback?state=xyz"
        with self.assertRaises(BadRedirectUrl) as ctx:
            extract_auth_code(url)
        self.assertIn("no code", str(ctx.exception))

    def test_garbage_input_reports_not_a_url(self):
        with self.assertRaises(BadRedirectUrl):
            extract_auth_code("hello world")

    def test_surrounding_whitespace_tolerated(self):
        url = "  https://auth.tesla.com/void/callback?code=C1&state=s \n"
        self.assertEqual(extract_auth_code(url), "C1")


if __name__ == "__main__":
    unittest.main()
