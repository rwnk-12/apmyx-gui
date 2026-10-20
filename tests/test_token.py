import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, mock_open, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.token import DeveloperTokenProvider, TokenFetchError


def jwt(expires=None, key="key", alg="ES256"):
    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return ".".join((encode({"alg": alg, "kid": key}),
                     encode({"exp": time.time() + 3600 if expires is None else expires}), "signature"))


def response(text="", url="https://music.apple.com/us/new", status=200, data=None):
    result = Mock(text=text, url=url, status_code=status)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.json.return_value = data
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class DeveloperTokenTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.provider = DeveloperTokenProvider(self.session)

    def test_current_module_script_and_cache(self):
        token = jwt()
        self.session.get.side_effect = [
            response('<script type="module" src="/assets/index~new.js"></script>'),
            response(token),
        ]
        self.assertEqual(self.provider.get(), token)
        self.assertEqual(self.provider.get("in"), token)
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(self.session.get.call_args.args[0], "https://music.apple.com/assets/index~new.js")

    def test_legacy_preload_absolute_and_query_script_references(self):
        for markup in (
            '<script src="/assets/index-legacy-old.js"></script>',
            '<link rel="modulepreload" href="/assets/auth.mjs?v=1">',
            '<script src="https://music.apple.com/assets/index-new.js"></script>',
        ):
            with self.subTest(markup=markup):
                token = jwt()
                self.session.get.side_effect = [response(markup), response(token)]
                self.assertEqual(DeveloperTokenProvider(self.session).get(), token)

    def test_split_bundle_and_failed_optional_asset(self):
        token = jwt()
        self.session.get.side_effect = [
            response('<script src="/assets/index.js"></script>'),
            response('import "./missing.js"; import "./config.js"',
                     url="https://music.apple.com/assets/index.js"),
            response(status=404), response(token),
        ]
        self.assertEqual(self.provider.get(), token)
        self.assertEqual(self.session.get.call_args.args[0], "https://music.apple.com/assets/config.js")

    def test_rejects_invalid_expired_and_wrong_algorithm_candidates(self):
        good = jwt()
        self.session.get.return_value = response(" ".join((
            "eyJbad.eyJbad.bad", jwt(expires=time.time() - 1),
            jwt(expires=time.time() + 10), jwt(alg="HS256"), good,
        )))
        self.assertEqual(self.provider.get(), good)

    def test_refreshes_cache_before_expiry(self):
        self.provider._token = jwt(expires=time.time() + 10)
        fresh = jwt()
        self.session.get.return_value = response(fresh)
        self.assertEqual(self.provider.get(), fresh)
        self.session.get.assert_called_once()

    def test_concurrent_workers_share_discovery(self):
        token = jwt()
        self.session.get.return_value = response(token)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(lambda _: self.provider.get(), range(16))), [token] * 16)
        self.session.get.assert_called_once()

    def test_auth_refresh_preserves_lyrics_headers_cookies_and_timeout(self):
        for status in (401, 403):
            with self.subTest(status=status):
                provider = DeveloperTokenProvider(self.session)
                old, fresh = jwt(key="old"), jwt(key="fresh")
                provider._token = old
                denied, success = response(status=status), response(data={"data": []})
                self.session.get.side_effect = [denied, response(fresh), success]
                headers = {"Accept": "application/json"}
                result = provider.get_response("https://amp-api.music.apple.com/lyrics",
                    headers=headers, cookies={"media-user-token": "user"}, timeout=30)
                self.assertIs(result, success)
                denied.close.assert_called_once()
                sent = self.session.get.call_args.kwargs
                self.assertEqual(sent["headers"]["Authorization"], f"Bearer {fresh}")
                self.assertEqual(sent["headers"]["Accept"], "application/json")
                self.assertEqual(sent["cookies"], {"media-user-token": "user"})
                self.assertEqual(sent["timeout"], 30)
                self.assertNotIn("Authorization", headers)

    def test_late_rejection_reuses_other_workers_refresh(self):
        fresh = jwt(key="fresh")
        self.provider._token = fresh
        self.assertEqual(self.provider.get(rejected_token=jwt(key="old")), fresh)
        self.session.get.assert_not_called()

    def test_auth_retry_is_bounded(self):
        self.provider._token = jwt(key="old")
        last = response(status=403)
        self.session.get.side_effect = [response(status=401), response(jwt(key="new")), last]
        self.assertIs(self.provider.get_response("https://amp-api.music.apple.com/test"), last)
        self.assertEqual(self.session.get.call_count, 3)

    def test_discovery_failure_is_bounded_and_does_not_cache(self):
        self.session.get.return_value = response("no scripts or tokens")
        with patch("core.token.time.sleep"), self.assertRaises(TokenFetchError):
            self.provider.get()
        self.assertEqual(self.session.get.call_count, 3)
        self.assertIsNone(self.provider._token)

    def test_does_not_reuse_rejected_token_from_page(self):
        old, fresh = jwt(key="old"), jwt(key="fresh")
        self.provider._token = old
        self.session.get.return_value = response(old + " " + fresh)
        self.assertEqual(self.provider.get(rejected_token=old), fresh)

    def test_ignores_external_scripts_and_cycles(self):
        self.session.get.side_effect = [
            response('<script src="https://example.com/evil.js"></script>'
                     '<script src="/assets/index.js"></script>'),
            response('import "./index.js"', url="https://music.apple.com/assets/index.js"),
        ]
        self.provider.MAX_ATTEMPTS = 1
        with self.assertRaises(TokenFetchError):
            self.provider.get()
        self.assertEqual(self.session.get.call_count, 2)


class ControllerTokenTests(unittest.TestCase):
    def setUp(self):
        from core.app import AppController
        self.controller = AppController()
        self.addCleanup(self.controller.session.close)
        self.controller.token_provider = Mock()

    def test_search_lookup_and_lyrics_use_provider(self):
        provider = self.controller.token_provider
        provider.get_response.return_value = response(data={"results": {}})
        self.assertEqual(self.controller._search_api("test", "songs", 1), {"results": {}})
        self.assertIn("/us/search", provider.get_response.call_args.args[0])
        provider.get_response.return_value = response(data={"data": [{"id": "123"}]})
        self.assertEqual(self.controller._lookup_api_item("songs", "123")["data"][0]["id"], "123")
        self.assertIn("/us/songs/123", provider.get_response.call_args.args[0])
        provider.get_response.return_value = response(data={"data": [{"attributes": {"ttml": "<tt/>"}}]})
        with patch("builtins.open", mock_open(read_data="media-user-token: user")):
            self.assertEqual(self.controller._fetch_lyrics_for_song("123"), "<tt/>")
        self.assertEqual(provider.get_response.call_args.kwargs["cookies"], {"media-user-token": "user"})
        self.controller.apply_runtime_settings({"storefront": "in"})
        self.controller._lookup_api_item("songs", "123")
        self.assertEqual(provider.get_response.call_args.args[1], "in")

    def test_failure_emits_existing_ui_signal(self):
        errors = []
        self.controller.token_fetch_failed.connect(errors.append)
        self.controller.token_provider.get_response.side_effect = TokenFetchError("Cannot fetch token")
        with self.assertRaisesRegex(ValueError, "Cannot fetch token"):
            self.controller._search_api("test", "songs", 1)
        self.assertEqual(errors, ["Cannot fetch token"])

    def test_runtime_search_storefront_follows_amd_and_restores_original(self):
        from core.config import sync_storefront
        self.controller.token_provider.get_response.return_value = response(data={"data": [{"id": "123"}]})
        config = sync_storefront({"wrapper": "applemusicdecrypt", "storefront": "gb", "applemusicdecrypt-storefront": "jp"})
        self.controller.apply_runtime_settings(config)
        self.controller._lookup_api_item("songs", "123")
        self.assertIn("/jp/songs/123", self.controller.token_provider.get_response.call_args.args[0])
        self.controller.apply_runtime_settings({**config, "wrapper": "legacy"})
        self.controller._lookup_api_item("songs", "123")
        self.assertIn("/gb/songs/123", self.controller.token_provider.get_response.call_args.args[0])
        config = sync_storefront({"storefront": "", "applemusicdecrypt-storefront": "jp"})
        self.controller.apply_runtime_settings(config)
        self.controller.apply_runtime_settings({**config, "wrapper": "legacy"})
        self.assertEqual(self.controller.storefront, "")


if __name__ == "__main__":
    unittest.main()
