import base64
from collections import deque
from html.parser import HTMLParser
import json
import logging
import math
import re
import threading
import time
from urllib.parse import urljoin, urlsplit

import requests


APPLE_MUSIC_URL = "https://music.apple.com"
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
JS_REFERENCE_PATTERN = re.compile(r"""["']([^"'\s]+\.m?js(?:\?[^"'\s]*)?)["']""")


class TokenFetchError(RuntimeError):
    pass


class _ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.sources.append(attrs["src"])
        elif (
            tag == "link" and attrs.get("rel") == "modulepreload" and attrs.get("href")
        ):
            self.sources.append(attrs["href"])


def _expiry(token):
    try:
        header, payload, _ = token.split(".")
        decode = lambda value: json.loads(
            base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        )
        if decode(header).get("alg") != "ES256":
            return 0
        expires = decode(payload).get("exp")
        if isinstance(expires, bool) or not isinstance(expires, (int, float)):
            return 0
        return expires if math.isfinite(expires) else 0
    except (ValueError, TypeError, AttributeError):
        return 0


class DeveloperTokenProvider:
    EXPIRY_MARGIN = 60
    MAX_SCRIPTS = 32
    MAX_ATTEMPTS = 3

    def __init__(self, session):
        self.session = session
        self._token = None
        self._lock = threading.Lock()

    def get(self, storefront="us", rejected_token=None):
        with self._lock:
            if (
                self._token
                and self._token != rejected_token
                and _expiry(self._token) > time.time() + self.EXPIRY_MARGIN
            ):
                return self._token
            self._token = None
            for attempt in range(self.MAX_ATTEMPTS):
                try:
                    self._token = self._discover(storefront, rejected_token)
                    logging.info("Fetched and cached Apple Music developer token.")
                    return self._token
                except (requests.RequestException, TokenFetchError) as exc:
                    logging.warning(
                        "Developer token discovery failed (attempt %d/%d): %s",
                        attempt + 1,
                        self.MAX_ATTEMPTS,
                        type(exc).__name__,
                    )
                    if attempt + 1 == self.MAX_ATTEMPTS:
                        raise TokenFetchError(
                            "Could not fetch an Apple Music developer token. "
                            "Check your connection and try again. The web player may have changed."
                        ) from exc
                    time.sleep(1)

    def get_response(self, url, storefront="us", **kwargs):
        headers = {"Origin": APPLE_MUSIC_URL, "Referer": APPLE_MUSIC_URL + "/"}
        headers.update(kwargs.pop("headers", {}) or {})
        token = self.get(storefront)
        kwargs.setdefault("timeout", 20)
        for attempt in range(2):
            headers["Authorization"] = f"Bearer {token}"
            response = self.session.get(url, headers=headers, **kwargs)
            if response.status_code not in (401, 403) or attempt == 1:
                return response
            response.close()
            token = self.get(storefront, rejected_token=token)

    def _find_token(self, content, rejected_token):
        for match in JWT_PATTERN.finditer(content):
            token = match.group(0)
            if (
                token != rejected_token
                and _expiry(token) > time.time() + self.EXPIRY_MARGIN
            ):
                return token
        return None

    def _discover(self, storefront, rejected_token):
        with self.session.get(
            f"{APPLE_MUSIC_URL}/{storefront}/browse", timeout=20
        ) as response:
            response.raise_for_status()
            page_url, content = response.url, response.text
        token = self._find_token(content, rejected_token)
        if token:
            return token

        parser = _ScriptParser()
        parser.feed(content)
        pending = deque()
        seen = set()

        def enqueue(sources, base_url):
            sources = sorted(
                sources,
                key=lambda src: (
                    not any(
                        name in src.lower()
                        for name in ("index", "token", "auth", "music")
                    )
                ),
            )
            for source in sources:
                url = urljoin(base_url, source)
                parts = urlsplit(url)
                if (
                    parts.scheme == "https"
                    and parts.netloc == "music.apple.com"
                    and parts.path.endswith((".js", ".mjs"))
                    and url not in seen
                ):
                    seen.add(url)
                    pending.append(url)

        enqueue(parser.sources, page_url)
        fetched = 0
        while pending and fetched < self.MAX_SCRIPTS:
            url = pending.popleft()
            fetched += 1
            try:
                with self.session.get(url, timeout=20) as response:
                    response.raise_for_status()
                    script, script_url = response.text, response.url
            except requests.RequestException:
                continue
            token = self._find_token(script, rejected_token)
            if token:
                return token
            enqueue(JS_REFERENCE_PATTERN.findall(script), script_url)
        raise TokenFetchError(
            "No usable developer token found in the Apple Music web player."
        )
