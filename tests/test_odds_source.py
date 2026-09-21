"""The odds provider: what it sends, what it refuses to say, what it parses.

The shapes below are written from the provider's documented v4 answer, not
saved from a real call, and that is a gap with a name: `tests/test_odds_live.py`
is what proves the parser against what the board actually sends, and it needs
a key. Until it has run, treat the parsing tests here as a contract with the
documentation rather than with the provider.
"""

import json

import pytest

from fandom.sources import odds
from fandom.sources.base import SourceError

KEY = "sup3r-s3cr3t-ab12"

ODDS_BODY = [{
    "id": "e1",
    "sport_key": "soccer_brazil_campeonato",
    "sport_title": "Brazil Série A",
    "commence_time": "2026-09-21T22:00:00Z",
    "home_team": "Flamengo",
    "away_team": "Palmeiras",
    "bookmakers": [
        {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-09-21T19:00:00Z",
         "markets": [{"key": "h2h", "last_update": "2026-09-21T19:00:00Z", "outcomes": [
             {"name": "Flamengo", "price": 1.95},
             {"name": "Palmeiras", "price": 4.30},
             {"name": "Draw", "price": 3.85}]}]},
        {"key": "betfair_ex_eu", "title": "Betfair", "last_update": "2026-09-21T18:58:00Z",
         "markets": [
             {"key": "h2h", "last_update": "2026-09-21T18:58:00Z", "outcomes": [
                 {"name": "Flamengo", "price": 1.98},
                 {"name": "Palmeiras", "price": 4.20},
                 {"name": "Draw", "price": 3.80}]},
             {"key": "totals", "last_update": "2026-09-21T18:58:00Z", "outcomes": [
                 {"name": "Over", "price": 1.90, "point": 2.5},
                 {"name": "Under", "price": 1.90, "point": 2.5}]}]},
    ],
}]

SPORTS_BODY = [
    {"key": "soccer_brazil_campeonato", "group": "Soccer", "title": "Brazil Série A",
     "active": True},
    {"key": "esports_csgo", "group": "Esports", "title": "CS2", "active": False},
]


@pytest.fixture(autouse=True)
def edge(monkeypatch):
    """Default every test to the production shape: an edge, no key anywhere."""
    monkeypatch.delenv(odds._KEY_ENV, raising=False)
    monkeypatch.setenv(odds._EDGE_ENV, "https://odds.example.test")


def answer(monkeypatch, status=200, body=None, headers=None):
    """Replace the transport and record the URL it was actually given."""
    seen = {}

    def fake(url, **_kwargs):
        seen["url"] = url
        payload = json.dumps(body if body is not None else ODDS_BODY).encode()
        return status, headers or {}, payload

    monkeypatch.setattr(odds.http, "fetch_headers", fake)
    return seen


class TestConfiguration:
    def test_the_edge_is_called_with_no_credential_at_all(self, monkeypatch):
        seen = answer(monkeypatch)
        odds.fetch_odds("soccer_brazil_campeonato")
        assert seen["url"].startswith("https://odds.example.test/v4/")
        assert "apikey" not in seen["url"].lower()

    def test_a_key_in_the_environment_switches_to_the_origin(self, monkeypatch):
        """The development path, and the only one that ever reads the key."""
        monkeypatch.setenv(odds._KEY_ENV, KEY)
        seen = answer(monkeypatch)
        odds.fetch_odds("soccer_brazil_campeonato")
        assert seen["url"].startswith(odds._ORIGIN)
        assert f"apiKey={KEY}" in seen["url"]

    def test_neither_one_is_an_absence_not_an_outage(self, monkeypatch):
        monkeypatch.delenv(odds._EDGE_ENV, raising=False)
        with pytest.raises(odds.OddsUnconfigured):
            odds.list_sports()


class TestRedaction:
    def test_the_answer_carries_a_url_with_no_key_in_it(self, monkeypatch):
        """source_health writes this URL to disk, under a tree AGENTS.md says
        holds no credential."""
        monkeypatch.setenv(odds._KEY_ENV, KEY)
        answer(monkeypatch)
        _events, result = odds.fetch_odds("soccer_brazil_campeonato")
        assert KEY not in result.url
        assert "regions=eu" in result.url      # the identity survives the stripping

    def test_the_key_never_reaches_an_error_message(self, monkeypatch):
        """An auth error is the classic place a credential turns up in a log."""
        monkeypatch.setenv(odds._KEY_ENV, KEY)
        answer(monkeypatch, status=401)
        with pytest.raises(SourceError) as raised:
            odds.list_sports()
        assert KEY not in str(raised.value)

    def test_a_server_error_names_the_redacted_url(self, monkeypatch):
        monkeypatch.setenv(odds._KEY_ENV, KEY)
        answer(monkeypatch, status=503)
        with pytest.raises(SourceError) as raised:
            odds.fetch_odds("soccer_epl")
        assert KEY not in str(raised.value) and "soccer_epl" in str(raised.value)

    def test_the_planned_url_is_redacted_too(self, monkeypatch):
        monkeypatch.setenv(odds._KEY_ENV, KEY)
        assert KEY not in odds.safe_url("/v4/sports/")

    def test_a_non_json_answer_does_not_echo_the_key(self, monkeypatch):
        monkeypatch.setenv(odds._KEY_ENV, KEY)
        monkeypatch.setattr(odds.http, "fetch_headers",
                            lambda url, **kw: (200, {}, b"<html>nope</html>"))
        with pytest.raises(SourceError) as raised:
            odds.list_sports()
        assert KEY not in str(raised.value)


class TestQuota:
    def test_a_429_is_its_own_error(self, monkeypatch):
        """The board is fine; we ran out of turns. A cached line still answers."""
        answer(monkeypatch, status=429, headers={"x-requests-remaining": "0"})
        with pytest.raises(odds.OddsQuota):
            odds.fetch_odds("soccer_epl")

    def test_the_headers_come_back_as_numbers(self, monkeypatch):
        answer(monkeypatch, headers={"x-requests-remaining": "451",
                                     "x-requests-used": "49", "x-requests-last": "1"})
        _events, result = odds.fetch_odds("soccer_brazil_campeonato")
        assert (result.remaining, result.used, result.cost) == (451, 49, 1)

    def test_missing_headers_are_none_not_zero(self, monkeypatch):
        """Zero credits left and no answer about credits are different facts."""
        answer(monkeypatch)
        _events, result = odds.fetch_odds("soccer_brazil_campeonato")
        assert result.remaining is None and result.cost is None

    def test_the_estimate_is_markets_times_regions(self):
        assert odds.plan_cost() == 1
        assert odds.plan_cost("h2h,totals", "eu,us") == 4


class TestParsing:
    def test_every_book_becomes_quotes_for_the_wanted_market(self, monkeypatch):
        answer(monkeypatch)
        events, _result = odds.fetch_odds("soccer_brazil_campeonato")
        assert len(events) == 1
        event = events[0]
        assert event.event_id == "e1" and event.home_team == "Flamengo"
        assert {quote.book for quote in event.quotes} == {"pinnacle", "betfair_ex_eu"}
        assert len(event.quotes) == 6            # two books, three outcomes

    def test_another_market_is_left_alone(self, monkeypatch):
        """A totals line is a different question and must not join this one."""
        answer(monkeypatch)
        events, _result = odds.fetch_odds("soccer_brazil_campeonato")
        assert all(quote.outcome in ("Flamengo", "Palmeiras", "Draw")
                   for quote in events[0].quotes)

    def test_a_quote_keeps_the_boards_own_timestamp(self, monkeypatch):
        answer(monkeypatch)
        events, _result = odds.fetch_odds("soccer_brazil_campeonato")
        betfair = next(q for q in events[0].quotes if q.book == "betfair_ex_eu")
        assert betfair.last_update == "2026-09-21T18:58:00Z"

    def test_a_price_that_is_not_a_number_is_skipped_not_guessed(self, monkeypatch):
        broken = json.loads(json.dumps(ODDS_BODY))
        broken[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = None
        answer(monkeypatch, body=broken)
        events, _result = odds.fetch_odds("soccer_brazil_campeonato")
        assert len(events[0].quotes) == 5

    def test_the_board_spelling_is_never_normalized(self, monkeypatch):
        """It is the join key a person confirmed; touching it breaks the link."""
        answer(monkeypatch)
        events, _result = odds.fetch_odds("soccer_brazil_campeonato")
        assert events[0].sport_title == "Brazil Série A"

    def test_an_event_list_carries_no_quotes(self, monkeypatch):
        """The free endpoint the linking flow reads: fixtures, no prices."""
        answer(monkeypatch, body=[{k: v for k, v in ODDS_BODY[0].items()
                                   if k != "bookmakers"}])
        events, _result = odds.list_events("soccer_brazil_campeonato")
        assert events[0].quotes == [] and events[0].home_team == "Flamengo"

    def test_sports_come_back_shaped_with_their_season_flag(self, monkeypatch):
        answer(monkeypatch, body=SPORTS_BODY)
        sports, _result = odds.list_sports()
        assert sports[0]["sport_key"] == "soccer_brazil_campeonato"
        assert sports[0]["active"] is True and sports[1]["active"] is False

    def test_an_empty_board_is_an_empty_list_not_a_crash(self, monkeypatch):
        answer(monkeypatch, body=[])
        events, _result = odds.fetch_odds("soccer_epl")
        assert events == []
