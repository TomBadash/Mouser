import json
import io
import unittest
import urllib.error
from unittest.mock import patch

from core.updater import (
    LatestRelease,
    UpdateCheckState,
    check_latest_release,
    fetch_latest_release,
    is_newer,
)
from core.version import APP_VERSION


class _FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


class UpdaterTests(unittest.TestCase):
    def test_is_newer_compares_stable_versions(self):
        self.assertTrue(is_newer("3.7.0", "3.7.1"))
        self.assertFalse(is_newer("3.7.0", "3.7.0"))
        self.assertFalse(is_newer("3.7.0", "3.6.9"))
        self.assertTrue(is_newer("3.7.0", "4.0.0"))
        self.assertTrue(is_newer("3.7.3", "3.7.3.2"))
        self.assertFalse(is_newer("3.7.3.2", "3.7.3"))

    def test_is_newer_ignores_prerelease_tags(self):
        self.assertFalse(is_newer("3.7.0", "3.7.0-rc1"))
        self.assertFalse(is_newer("3.7.0", "v3.8.0-beta.1"))

    def test_fetch_latest_release_parses_github_response(self):
        payload = {
            "tag_name": "v3.7.1",
            "html_url": "https://github.com/TomBadash/Mouser/releases/tag/v3.7.1",
            "name": "Mouser v3.7.1",
            "published_at": "2026-05-13T00:00:00Z",
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)) as mocked:
            release = fetch_latest_release(timeout=1)

        self.assertEqual(
            release,
            LatestRelease(
                tag_name="v3.7.1",
                html_url="https://github.com/TomBadash/Mouser/releases/tag/v3.7.1",
                name="Mouser v3.7.1",
                published_at="2026-05-13T00:00:00Z",
            ),
        )
        request = mocked.call_args.args[0]
        self.assertIn("TomBadash/Mouser", request.full_url)
        self.assertEqual(request.get_header("User-agent"), f"Mouser/{APP_VERSION}")

    def test_check_latest_release_accepts_utf8_bom_response(self):
        payload = (
            b'\xef\xbb\xbf{"tag_name":"v3.7.1",'
            b'"html_url":"https://github.com/TomBadash/Mouser/releases/tag/v3.7.1"}'
        )

        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
            result = check_latest_release(now=10.0, manual=True)

        self.assertEqual(result.release.tag_name, "v3.7.1")
        self.assertTrue(result.reachable)

    def test_fetch_latest_release_can_use_test_endpoint_override(self):
        payload = {
            "tag_name": "v3.7.1",
            "html_url": "https://example.test/releases/v3.7.1",
        }
        with (
            patch.dict(
                "os.environ",
                {"MOUSER_UPDATE_LATEST_RELEASE_URL": "http://127.0.0.1:8765/release.json"},
            ),
            patch("urllib.request.urlopen", return_value=_FakeResponse(payload)) as mocked,
        ):
            release = fetch_latest_release(timeout=1)

        self.assertEqual(release.tag_name, "v3.7.1")
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8765/release.json")

    def test_fetch_latest_release_returns_none_on_malformed_response(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse({"tag_name": "v3.7.1"}),
        ):
            self.assertIsNone(fetch_latest_release())

    def test_fetch_latest_release_ignores_drafts_and_prereleases(self):
        payload = {
            "tag_name": "v3.8.0-beta.1",
            "html_url": "https://github.com/TomBadash/Mouser/releases/tag/v3.8.0-beta.1",
            "prerelease": True,
        }
        with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
            self.assertIsNone(fetch_latest_release())

    def test_fetch_latest_release_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            self.assertIsNone(fetch_latest_release())

    def test_fetch_latest_release_returns_none_on_invalid_json(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(b"{")):
            self.assertIsNone(fetch_latest_release())

    def test_check_latest_release_records_attempt_on_malformed_response(self):
        response = _FakeResponse(
            {"tag_name": "v3.7.1"},
            headers={"ETag": '"malformed"'},
        )

        with patch("urllib.request.urlopen", return_value=response):
            result = check_latest_release(now=50.0)

        self.assertIsNone(result.release)
        self.assertFalse(result.reachable)
        self.assertEqual(result.state.last_check, 50.0)
        self.assertEqual(result.state.etag, '"malformed"')

    def test_check_latest_release_logs_unreadable_json_response(self):
        stderr = io.StringIO()

        with (
            patch("urllib.request.urlopen", return_value=_FakeResponse(b"{")),
            patch("sys.stderr", new=stderr),
        ):
            result = check_latest_release(now=60.0, manual=True)

        self.assertIsNone(result.release)
        self.assertFalse(result.reachable)
        self.assertEqual(result.state.last_check, 60.0)
        self.assertIn("[update] release metadata could not be read:", stderr.getvalue())

    def test_check_latest_release_records_attempt_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = check_latest_release(now=75.0)

        self.assertIsNone(result.release)
        self.assertFalse(result.reachable)
        self.assertEqual(result.state.last_check, 75.0)

    def test_check_latest_release_sends_conditional_headers_and_persists_cache(self):
        payload = {
            "tag_name": "v3.7.1",
            "html_url": "https://github.com/TomBadash/Mouser/releases/tag/v3.7.1",
        }
        state = UpdateCheckState(
            etag='"old"',
            last_modified="Tue, 12 May 2026 00:00:00 GMT",
        )
        response = _FakeResponse(
            payload,
            headers={
                "ETag": '"new"',
                "Last-Modified": "Wed, 13 May 2026 00:00:00 GMT",
            },
        )

        with patch("urllib.request.urlopen", return_value=response) as mocked:
            result = check_latest_release(state=state, now=10.0)

        request = mocked.call_args.args[0]
        self.assertEqual(request.get_header("If-none-match"), '"old"')
        self.assertEqual(
            request.get_header("If-modified-since"),
            "Tue, 12 May 2026 00:00:00 GMT",
        )
        self.assertEqual(result.release.tag_name, "v3.7.1")
        self.assertTrue(result.reachable)
        self.assertEqual(result.state.etag, '"new"')
        self.assertEqual(
            result.state.last_modified, "Wed, 13 May 2026 00:00:00 GMT"
        )
        self.assertEqual(result.state.last_check, 10.0)
        self.assertEqual(result.state.last_seen_latest_version, "v3.7.1")

    def test_check_latest_release_handles_not_modified(self):
        state = UpdateCheckState(etag='"new"', last_check=1.0)
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/TomBadash/Mouser/releases/latest",
            304,
            "Not Modified",
            {},
            None,
        )

        with patch("urllib.request.urlopen", side_effect=error):
            result = check_latest_release(state=state, now=20.0, manual=True)

        self.assertIsNone(result.release)
        self.assertTrue(result.reachable)
        self.assertTrue(result.not_modified)
        self.assertEqual(result.state.etag, '"new"')
        self.assertEqual(result.state.last_check, 20.0)

    def test_check_latest_release_respects_automatic_interval(self):
        state = UpdateCheckState(last_check=100.0)

        with patch("urllib.request.urlopen") as mocked:
            result = check_latest_release(
                state=state,
                now=120.0,
                manual=False,
                min_interval_seconds=60,
            )

        mocked.assert_not_called()
        self.assertIsNone(result.release)
        self.assertTrue(result.throttled)
        self.assertTrue(result.reachable)

    def test_check_latest_release_manual_bypasses_automatic_interval(self):
        payload = {
            "tag_name": "v3.7.1",
            "html_url": "https://github.com/TomBadash/Mouser/releases/tag/v3.7.1",
        }
        state = UpdateCheckState(last_check=100.0)

        with patch(
            "urllib.request.urlopen", return_value=_FakeResponse(payload)
        ) as mocked:
            result = check_latest_release(
                state=state,
                now=120.0,
                manual=True,
                min_interval_seconds=60,
            )

        mocked.assert_called_once()
        self.assertEqual(result.release.tag_name, "v3.7.1")

    def test_check_latest_release_obeys_retry_after_backoff(self):
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/TomBadash/Mouser/releases/latest",
            403,
            "rate limited",
            {"Retry-After": "30"},
            None,
        )

        with patch("urllib.request.urlopen", side_effect=error):
            result = check_latest_release(now=100.0, manual=True)

        self.assertFalse(result.reachable)
        self.assertTrue(result.rate_limited)
        self.assertEqual(result.state.backoff_until, 130.0)

        with patch("urllib.request.urlopen") as mocked:
            retry = check_latest_release(state=result.state, now=120.0, manual=True)

        mocked.assert_not_called()
        self.assertTrue(retry.throttled)
        self.assertTrue(retry.rate_limited)


if __name__ == "__main__":
    unittest.main()
