import collections
import time

import requests

from scrapers import constants

RATE_LIMIT_WAIT_SECONDS = 180.0
RATE_LIMIT_COOLDOWN_SECONDS = 300.0


class FetchError(Exception):
    pass


class RateLimitedError(FetchError):
    pass


class FetchClient:
    def __init__(
        self,
        use_cache: bool = True,
        delay: float = constants.REQUEST_DELAY_SECONDS,
        cache_dir=None,
        max_requests_per_window: int | None = None,
        window_seconds: float = 120.0,
    ):
        self.session = requests.Session()
        self.session.headers.update(constants.HEADERS)
        self.use_cache = use_cache
        self.delay = delay
        self.cache_dir = cache_dir if cache_dir is not None else constants.CACHE_DIR
        self.max_requests_per_window = max_requests_per_window
        self.window_seconds = window_seconds
        self._last_request_at = 0.0
        self._request_times = collections.deque()
        self._cool_until = 0.0

    def _pace(self) -> None:
        now = time.monotonic()
        if now < self._cool_until:
            remaining = self._cool_until - now
            print(f"  [rate-limit cooldown] pausing {remaining:.0f}s", flush=True)
            time.sleep(remaining)
            now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        if self.max_requests_per_window:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] > self.window_seconds:
                self._request_times.popleft()
            while len(self._request_times) >= self.max_requests_per_window:
                wait = self.window_seconds - (now - self._request_times[0]) + self.delay
                time.sleep(max(wait, 0.0))
                now = time.monotonic()
                while self._request_times and now - self._request_times[0] > self.window_seconds:
                    self._request_times.popleft()
        self._last_request_at = time.monotonic()

    def _cache_path(self, cache_key: str) -> object:
        return self.cache_dir / f"{cache_key}.html"

    def fetch(self, url: str, cache_key: str | None = None) -> str:
        if cache_key is not None and self.use_cache:
            cached = self._cache_path(cache_key)
            if cached.exists():
                return cached.read_text(encoding="utf-8")

        last_error = None
        for attempt in range(constants.MAX_RETRIES):
            try:
                self._pace()
                self._request_times.append(time.monotonic())
                resp = self.session.get(url, timeout=30)
                if resp.status_code in (403, 429):
                    raise RateLimitedError(f"HTTP {resp.status_code} for {url}")
                if resp.status_code >= 500:
                    raise FetchError(f"HTTP {resp.status_code} for {url}")
                resp.raise_for_status()
                if "charset" in resp.headers.get("Content-Type", ""):
                    html = resp.text
                else:
                    html = resp.content.decode("utf-8", errors="replace")

                if cache_key is not None and self.use_cache:
                    self._cache_path(cache_key).parent.mkdir(parents=True, exist_ok=True)
                    self._cache_path(cache_key).write_text(html, encoding="utf-8")
                return html
            except RateLimitedError as exc:
                last_error = exc
                self._cool_until = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
                if attempt < constants.MAX_RETRIES - 1:
                    time.sleep(RATE_LIMIT_WAIT_SECONDS)
            except (requests.RequestException, FetchError) as exc:
                last_error = exc
                if attempt < constants.MAX_RETRIES - 1:
                    time.sleep(constants.RETRY_BACKOFF_SECONDS * (2**attempt))

        raise FetchError(f"Failed to fetch {url}: {last_error}")
