import unittest

from app.api import TESLA_APP_VERSION, build_details_url
from app.auth import REDIRECT_URI, extract_auth_code


class TestNewAuthConstants(unittest.TestCase):
    def test_redirect_uri_is_app_scheme(self):
        # Tesla delisted https://auth.tesla.com/void/callback for ownerapi (2026-07)
        self.assertEqual(REDIRECT_URI, "tesla://auth/callback")

    def test_app_version_no_longer_pinned_to_retired_build(self):
        self.assertEqual(TESLA_APP_VERSION, "9.99.9-9999")
        self.assertIn("appVersion=9.99.9-9999", build_details_url("RN1", "zh-TW"))


class TestExtractAuthCodeTeslaScheme(unittest.TestCase):
    def test_tesla_scheme_callback_accepted(self):
        url = "tesla://auth/callback?code=NA_abc&state=xyz&issuer=https%3A%2F%2Fauth.tesla.com%2Foauth2%2Fv3"
        self.assertEqual(extract_auth_code(url), "NA_abc")

    def test_legacy_https_callback_still_accepted(self):
        url = "https://auth.tesla.com/void/callback?code=C9&state=s"
        self.assertEqual(extract_auth_code(url), "C9")


if __name__ == "__main__":
    unittest.main()
