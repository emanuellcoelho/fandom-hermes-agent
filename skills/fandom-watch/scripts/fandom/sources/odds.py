"""The odds board: fixtures with the prices bookmakers are posting.

The agent carries no credential. Its image is public and its home is a tree
AGENTS.md says holds no secret, so the key lives at an edge that speaks this
API verbatim -- same paths, same JSON, same x-requests-* headers, minus the
?apiKey= -- and the agent calls a public URL exactly as it calls thesportsdb.

The development path talks to the origin directly and reads the key from the
environment. `_base_and_auth` is the only function in this tree allowed to do
that, and it writes nothing. Everything that leaves this module -- a planned
source, an error message, a health record -- leaves redacted, because
`source_health` keys its record by URL and writes that record to disk.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any

from kit import http

from fandom.models import OddsEvent, Quote
from fandom.sources.base import SourceError

# The origin, spoken only in development.
_ORIGIN = "https://api.the-odds-api.com"
_KEY_ENV = "ODDS_API_KEY"

# The public edge that holds the key. Empty until one answers a live test:
# the rule this repo already learned the hard way is that a URL nobody
# fetched through kit.http is a guess, and three feeds sat dead for days
# behind a comment claiming otherwise. `ODDS_EDGE_BASE` sets it per
# deployment; an empty value means this source is simply not configured, and
# the caller degrades the way it degrades for a dead feed.
_EDGE_DEFAULT = ""
_EDGE_ENV = "ODDS_EDGE_BASE"

SPORTS_PATH = "/v4/sports"
DEFAULT_MARKETS = "h2h"
DEFAULT_REGIONS = "eu"


class OddsQuota(SourceError):
    """The board is fine; we ran out of turns.

    Distinct from a dead source on purpose: everything downstream reads the
    two differently, and a cached line still answers this one.
    """


class OddsUnconfigured(SourceError):
    """No edge and no key: nothing to call. Not an outage, an absence."""


@dataclass(frozen=True)
class Answer:
    """One call's outcome, including what it cost.

    The headers are the only authority on the price; `plan_cost` is a
    pre-flight guess that stops being true the day the provider reprices.
    """

    status: int
    payload: Any
    url: str                  # redacted, always
    remaining: int | None = None   # x-requests-remaining
    used: int | None = None        # x-requests-used
    cost: int | None = None        # x-requests-last: what THIS call cost


def _base_and_auth() -> tuple[str, dict[str, str]]:
    """Where to call and what to send. The one place a key may be read.

    A key in the environment means a developer's machine, so the call goes
    straight to the origin. Otherwise the edge answers, and the agent has
    nothing to leak.
    """
    key = os.environ.get(_KEY_ENV, "").strip()
    if key:
        return _ORIGIN, {"apiKey": key}
    edge = (os.environ.get(_EDGE_ENV) or _EDGE_DEFAULT).strip().rstrip("/")
    if not edge:
        raise OddsUnconfigured("odds", "no odds edge configured")
    return edge, {}


def _redact(url: str) -> str:
    """The identity of a request, with nothing secret in it.

    Not cosmetic. `source_health` keys its record by URL and writes it to
    sources.json, under a tree that carries no credential -- so the live URL
    is built inside `_get` and dies there, and this is what the rest of the
    program ever sees.
    """
    parts = urllib.parse.urlsplit(url)
    kept = [(name, value) for name, value in urllib.parse.parse_qsl(parts.query)
            if name.lower() != "apikey"]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(kept), ""))


def _number(headers: dict[str, str], name: str) -> int | None:
    raw = (headers or {}).get(name, "").strip()
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def safe_url(path: str, params: dict[str, str] | None = None) -> str:
    """The redacted URL a call would use, for planning and health records."""
    base, _auth = _base_and_auth()
    query = urllib.parse.urlencode(params or {})
    return f"{base}{path}?{query}" if query else f"{base}{path}"


def _get(path: str, params: dict[str, str] | None = None) -> Answer:
    base, auth = _base_and_auth()
    query = urllib.parse.urlencode({**(params or {}), **auth})
    url = f"{base}{path}?{query}"
    safe = _redact(url)
    status, headers, body = http.fetch_headers(url)
    if status == 429:
        raise OddsQuota("odds", "quota exhausted")
    if status == 401:
        # No interpolation here at all: an auth error message is the classic
        # place a credential turns up in a log.
        raise SourceError("odds", "credentials refused")
    if status != 200:
        raise SourceError("odds", f"HTTP {status} for {safe}")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise SourceError("odds", f"non-JSON answer for {safe}: {str(error)[:80]}") from error
    return Answer(
        status=status, payload=payload, url=safe,
        remaining=_number(headers, "x-requests-remaining"),
        used=_number(headers, "x-requests-used"),
        cost=_number(headers, "x-requests-last"),
    )


def plan_cost(markets: str = DEFAULT_MARKETS, regions: str = DEFAULT_REGIONS) -> int:
    """The pre-flight estimate: markets times regions. The header is the receipt."""
    return max(1, len([m for m in markets.split(",") if m]) *
               len([r for r in regions.split(",") if r]))


def _event_from(raw: dict[str, Any], market: str = DEFAULT_MARKETS) -> OddsEvent:
    """One fixture, with every price the board carries for the wanted market.

    Team names are kept exactly as the board spells them: they are the join
    key a person confirmed, and normalizing them here would break the link.
    """
    quotes: list[Quote] = []
    for book in raw.get("bookmakers") or []:
        for offered in book.get("markets") or []:
            if offered.get("key") != market:
                continue
            stamp = offered.get("last_update") or book.get("last_update") or ""
            for outcome in offered.get("outcomes") or []:
                try:
                    price = float(outcome["price"])
                except (KeyError, TypeError, ValueError):
                    continue
                quotes.append(Quote(book=str(book.get("key") or book.get("title") or ""),
                                    outcome=str(outcome.get("name") or ""),
                                    price=price, last_update=str(stamp)))
    return OddsEvent(
        event_id=str(raw.get("id") or ""), sport_key=str(raw.get("sport_key") or ""),
        sport_title=str(raw.get("sport_title") or ""),
        commence_time=str(raw.get("commence_time") or ""),
        home_team=str(raw.get("home_team") or ""), away_team=str(raw.get("away_team") or ""),
        market=market, quotes=quotes,
    )


def list_sports() -> tuple[list[dict[str, Any]], Answer]:
    """Which competitions the board carries, and which are in season. Free."""
    answer = _get(f"{SPORTS_PATH}/")
    sports = [
        {"sport_key": entry.get("key"), "title": entry.get("title"),
         "group": entry.get("group"), "active": bool(entry.get("active"))}
        for entry in (answer.payload or []) if isinstance(entry, dict)
    ]
    return sports, answer


def list_events(sport_key: str) -> tuple[list[OddsEvent], Answer]:
    """This competition's fixtures, without any price. Free, and no credit.

    The linking conversation reads this: asking which club the board means
    must never cost a credit, or onboarding becomes the expensive part.
    """
    answer = _get(f"{SPORTS_PATH}/{sport_key}/events")
    events = [_event_from(raw) for raw in (answer.payload or []) if isinstance(raw, dict)]
    return events, answer


def fetch_odds(sport_key: str, *, markets: str = DEFAULT_MARKETS,
               regions: str = DEFAULT_REGIONS,
               event_id: str | None = None) -> tuple[list[OddsEvent], Answer]:
    """The prices, for a whole competition at once. This is what costs.

    One call returns every fixture of the league, so reading three leagues is
    three credits, not three credits per game.
    """
    path = f"{SPORTS_PATH}/{sport_key}/odds"
    if event_id:
        path = f"{SPORTS_PATH}/{sport_key}/events/{event_id}/odds"
    answer = _get(path, {"regions": regions, "markets": markets, "oddsFormat": "decimal"})
    payload = answer.payload
    raws = payload if isinstance(payload, list) else [payload]
    events = [_event_from(raw, market=markets.split(",")[0])
              for raw in raws if isinstance(raw, dict)]
    return events, answer
