"""Minimal HTTP that says who it is: enough to read feeds and pages."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

# An honest identity, not a borrowed one. ESPN answers a spoofed Chrome with
# HTTP 202 and an empty body -- a success code carrying nothing, so the sweep
# recorded three dead feeds (nba, nfl, soccer) and said nothing. The same
# request under this agent's own name answers 200 with the feed. Checked
# against every source this agent reads: espn, bbc, ge.globo, google news and
# thesportsdb all answer 200, so there is no site left that wants the pretence.
USER_AGENT = (
    "fandom-hermes-agent/1.0 "
    "(+https://github.com/emanuellcoelho/fandom-hermes-agent)"
)


class HttpError(RuntimeError):
    """A fetch that could not deliver bytes worth parsing."""


# Retrying instantly is retrying rudely: a 429 means "slow down", and the old
# `continue` answered it by knocking again in the same millisecond. A server
# that is merely busy gets the second knock a quarter second later, and one
# that names its own terms via Retry-After gets what it asked for -- capped,
# because an irritated server sends 99 and the digest cron cannot wait that
# long. `_sleep` is module-level so tests can swap it and stay instant.
_sleep = time.sleep
_BACKOFF_BASE_S = 0.25
_RETRY_AFTER_CAP_S = 2.0


def _retry_after_s(error: urllib.error.HTTPError) -> float | None:
    """The server's own wait, in seconds, when it named one in whole seconds."""
    raw = ""
    if getattr(error, "headers", None) is not None:
        raw = (error.headers.get("Retry-After") or "").strip()
    if not raw.isdigit():        # the HTTP-date form is rare; the default covers it
        return None
    return float(raw)


def fetch(url: str, *, timeout_s: float = 8.0, attempts: int = 2) -> tuple[int, bytes]:
    """GET the URL, return (status, body). Retries transient failures once.

    Any single request's failure is the caller's to survive -- a sweep checks
    many items and one bad store must never end the sweep.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7"})
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                last_error = error
                wait = _retry_after_s(error)
                if wait is None:
                    wait = _BACKOFF_BASE_S * (2 ** attempt)
                _sleep(min(wait, _RETRY_AFTER_CAP_S))
                continue
            return error.code, error.read()
        except OSError as error:
            last_error = error
    raise HttpError(f"GET {url} failed: {last_error}")
