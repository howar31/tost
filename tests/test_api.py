import json
import unittest
from urllib.parse import parse_qs, urlparse

from app.api import (
    ApiError,
    Unauthorized,
    build_details_url,
    build_headers,
    fetch_snapshot,
    post_form,
    request_json,
)


class TestBuildHeaders(unittest.TestCase):
    def test_includes_bearer_and_app_identity(self):
        headers = build_headers("tok123")
        self.assertEqual(headers["Authorization"], "Bearer tok123")
        self.assertIn("Tesla", headers["User-Agent"])
        self.assertIn("TeslaApp", headers["X-Tesla-User-Agent"])
        self.assertTrue(headers["X-Request-Id"])


class TestBuildDetailsUrl(unittest.TestCase):
    def test_locale_split_into_language_and_country(self):
        url = build_details_url("RN000111", "zh-TW")
        qs = parse_qs(urlparse(url).query)
        self.assertEqual(qs["deviceLanguage"], ["zh"])
        self.assertEqual(qs["deviceCountry"], ["TW"])
        self.assertEqual(qs["referenceNumber"], ["RN000111"])
        self.assertIn("appVersion", qs)

    def test_missing_locale_falls_back_to_en_us(self):
        qs = parse_qs(urlparse(build_details_url("RN1", None)).query)
        self.assertEqual(qs["deviceLanguage"], ["en"])
        self.assertEqual(qs["deviceCountry"], ["US"])


class FakeFetch:
    """Scripted (status, body) responses; records calls."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, headers, data):
        self.calls.append({"url": url, "headers": headers, "data": data})
        result = self.script.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestRequestJson(unittest.TestCase):
    def test_retries_5xx_then_succeeds(self):
        fetch = FakeFetch([(500, ""), (200, '{"ok": true}')])
        result = request_json("http://x", fetch=fetch, sleep=lambda s: None)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(fetch.calls), 2)

    def test_401_raises_unauthorized_without_retry(self):
        fetch = FakeFetch([(401, "")])
        with self.assertRaises(Unauthorized):
            request_json("http://x", fetch=fetch, sleep=lambda s: None)
        self.assertEqual(len(fetch.calls), 1)

    def test_persistent_5xx_raises_after_3_attempts(self):
        fetch = FakeFetch([(503, "")] * 3)
        with self.assertRaises(ApiError):
            request_json("http://x", fetch=fetch, sleep=lambda s: None)
        self.assertEqual(len(fetch.calls), 3)

    def test_network_error_retried(self):
        fetch = FakeFetch([OSError("conn reset"), (200, "{}")])
        self.assertEqual(
            request_json("http://x", fetch=fetch, sleep=lambda s: None), {}
        )


class TestPostForm(unittest.TestCase):
    def test_fields_urlencoded_in_body(self):
        fetch = FakeFetch([(200, '{"access_token": "a"}')])
        result = post_form("http://x", {"grant_type": "refresh_token", "a": "b c"}, fetch=fetch)
        self.assertEqual(result, {"access_token": "a"})
        body = fetch.calls[0]["data"].decode()
        self.assertIn("grant_type=refresh_token", body)
        self.assertIn("a=b+c", body)


class TestFetchSnapshot(unittest.TestCase):
    def test_assembles_orders_with_details_keyed_by_ref(self):
        orders_body = json.dumps(
            {"response": [
                {"referenceNumber": "RN1", "locale": "zh-TW", "modelCode": "my"},
                {"referenceNumber": "RN2", "locale": "zh-TW", "modelCode": "m3"},
            ]}
        )
        fetch = FakeFetch([
            (200, orders_body),
            (200, '{"tasks": {"n": 1}}'),
            (200, '{"tasks": {"n": 2}}'),
        ])
        snapshot = fetch_snapshot("tok", fetch=fetch)
        self.assertEqual(set(snapshot.keys()), {"RN1", "RN2"})
        self.assertEqual(snapshot["RN1"]["order"]["modelCode"], "my")
        self.assertEqual(snapshot["RN1"]["details"], {"tasks": {"n": 1}})
        detail_urls = [c["url"] for c in fetch.calls[1:]]
        self.assertTrue(all("referenceNumber=RN" in u for u in detail_urls))


if __name__ == "__main__":
    unittest.main()
