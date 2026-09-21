"""kit.http.fetch, exercised for real.

Every other test monkeypatches `fetch` away, so its retry policy, its status
handling and the identity it sends were never run by the suite -- which is
exactly where a live bug hid: ESPN answered a spoofed Chrome User-Agent with
HTTP 202 and an empty body, three feeds died silently, and nothing caught it.
The local-server class below replays that response.
"""

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fandom.sources import rss
from kit import http

EMPTY_FEED = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Quiet</title></channel></rss>'
BOT_WALL = (b'<!DOCTYPE html><html><head><title>Just a moment...</title></head>'
            b'<body><p>Checking your browser</p></body></html>')
ONE_ITEM = (b'<?xml version="1.0"?><rss version="2.0"><channel>'
            b'<item><title>Chiefs win in overtime</title>'
            b'<link>https://example.test/a</link></item></channel></rss>')


class _Response:
    """What urlopen hands back: a context manager with .status and .read()."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _http_error(code: int, body: bytes = b"nope", headers: dict | None = None):
    return urllib.error.HTTPError("https://example.test", code, "err", headers or {}, None)


class TestRetryPolicy:
    """The retry decisions, with urlopen replaced -- no sockets."""

    def _spy(self, monkeypatch, outcomes):
        """urlopen that yields `outcomes` in order; records the Requests seen."""
        seen = []

        def fake(request, timeout=None):
            seen.append(request)
            outcome = outcomes[len(seen) - 1]
            if isinstance(outcome, Exception):
                if isinstance(outcome, urllib.error.HTTPError):
                    outcome.read = lambda: b"error body"
                raise outcome
            return outcome

        monkeypatch.setattr(urllib.request, "urlopen", fake)
        return seen

    def test_403_is_an_answer_not_a_failure(self, monkeypatch):
        seen = self._spy(monkeypatch, [_http_error(403)])
        status, body = http.fetch("https://example.test/feed")
        assert status == 403
        assert body == b"error body"
        assert len(seen) == 1, "403 must not be retried -- it is a decision, not a hiccup"

    def test_503_twice_gives_up_with_the_status(self, monkeypatch):
        seen = self._spy(monkeypatch, [_http_error(503), _http_error(503)])
        status, _ = http.fetch("https://example.test/feed")
        assert status == 503
        assert len(seen) == 2

    def test_503_then_200_succeeds(self, monkeypatch):
        seen = self._spy(monkeypatch, [_http_error(503), _Response(200, ONE_ITEM)])
        status, body = http.fetch("https://example.test/feed")
        assert (status, body) == (200, ONE_ITEM)
        assert len(seen) == 2

    def test_network_failure_twice_raises(self, monkeypatch):
        seen = self._spy(monkeypatch, [OSError("dns"), OSError("dns")])
        with pytest.raises(http.HttpError):
            http.fetch("https://example.test/feed")
        assert len(seen) == 2

    def test_identity_is_our_own_never_a_browser(self, monkeypatch):
        """Regression on the ESPN incident, at the level where it happened."""
        seen = self._spy(monkeypatch, [_Response(200, ONE_ITEM)])
        http.fetch("https://example.test/feed")
        agent = seen[0].get_header("User-agent")
        assert "fandom-hermes-agent" in agent
        assert "Mozilla" not in agent, "a borrowed identity is what ESPN answered 202 to"


class TestBackoff:
    """The wait between knocks, with a recording sleeper -- the suite stays instant."""

    @pytest.fixture()
    def slept(self, monkeypatch):
        waits: list[float] = []
        monkeypatch.setattr(http, "_sleep", waits.append)
        return waits

    def _spy(self, monkeypatch, outcomes):
        seen = []

        def fake(request, timeout=None):
            seen.append(request)
            outcome = outcomes[len(seen) - 1]
            if isinstance(outcome, Exception):
                if isinstance(outcome, urllib.error.HTTPError):
                    outcome.read = lambda: b"error body"
                raise outcome
            return outcome

        monkeypatch.setattr(urllib.request, "urlopen", fake)
        return seen

    def test_one_wait_between_two_knocks(self, monkeypatch, slept):
        self._spy(monkeypatch, [_http_error(503), _Response(200, ONE_ITEM)])
        http.fetch("https://example.test/feed")
        assert slept == [0.25]

    def test_the_last_attempt_never_waits(self, monkeypatch, slept):
        """Nothing follows it, so a wait would only delay the answer."""
        self._spy(monkeypatch, [_http_error(503)])
        http.fetch("https://example.test/feed", attempts=1)
        assert slept == []

    def test_a_named_wait_is_honoured(self, monkeypatch, slept):
        error = _http_error(429, headers={"Retry-After": "1"})
        self._spy(monkeypatch, [error, _Response(200, ONE_ITEM)])
        http.fetch("https://example.test/feed")
        assert slept == [1.0]

    def test_an_absurd_wait_is_capped(self, monkeypatch, slept):
        """A server saying 99 seconds does not get to own the digest cron."""
        error = _http_error(503, headers={"Retry-After": "99"})
        self._spy(monkeypatch, [error, _Response(200, ONE_ITEM)])
        http.fetch("https://example.test/feed")
        assert slept == [2.0]

    def test_an_http_date_falls_back_to_the_default(self, monkeypatch, slept):
        error = _http_error(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        self._spy(monkeypatch, [error, _Response(200, ONE_ITEM)])
        http.fetch("https://example.test/feed")
        assert slept == [0.25]

    def test_403_never_waits(self, monkeypatch, slept):
        self._spy(monkeypatch, [_http_error(403)])
        http.fetch("https://example.test/feed")
        assert slept == []


class _Handler(BaseHTTPRequestHandler):
    ROUTES = {
        "/feed.xml": (200, ONE_ITEM),
        "/silent": (202, b""),          # the ESPN incident, exactly
        "/botwall": (200, BOT_WALL),
        "/empty-feed": (200, EMPTY_FEED),
    }

    def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's name
        if self.path == "/slow":
            import time
            time.sleep(1.0)
            status, body = 200, ONE_ITEM
        else:
            status, body = self.ROUTES.get(self.path, (404, b"missing"))
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *_):  # keep pytest output clean
        return


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


class TestAgainstALocalServer:
    """Loopback, not egress: the only place urlopen itself is exercised."""

    def test_a_real_feed_parses(self, server):
        assert len(rss.fetch_feed(f"{server}/feed.xml")) == 1

    def test_success_with_an_empty_body_is_a_failure(self, server):
        """HTTP 202 and nothing in it: a success code carrying no feed."""
        with pytest.raises(rss.FeedError):
            rss.fetch_feed(f"{server}/silent")

    def test_bot_wall_is_not_a_feed(self, server):
        with pytest.raises(rss.FeedError) as caught:
            rss.fetch_feed(f"{server}/botwall")
        assert "not a feed" in str(caught.value)

    def test_a_genuinely_empty_feed_is_not_an_error(self, server):
        """The false-positive guard: quiet day, valid feed, no news."""
        assert rss.fetch_feed(f"{server}/empty-feed") == []

    def test_timeout_raises_http_error(self, server):
        with pytest.raises(http.HttpError):
            http.fetch(f"{server}/slow", timeout_s=0.2, attempts=1)
