"""`fandom.py odds`, end to end with the transport replaced.

The CLI is loaded by path: the script is `fandom.py` and the package next to
it is `fandom/`, so an import statement would reach the wrong one.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from fandom.models import Sport, Team
from fandom.sources import odds as odds_source
from fandom.store import FandomStore

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "fandom-watch" / "scripts"
KEY = "sup3r-s3cr3t-ab12"

BOARD = [{
    "id": "e1", "sport_key": "soccer_brazil_campeonato", "sport_title": "Brazil Série A",
    "commence_time": None,          # filled per test, relative to now
    "home_team": "Flamengo", "away_team": "Palmeiras",
    "bookmakers": [
        {"key": "pinnacle", "last_update": None, "markets": [{"key": "h2h", "last_update": None,
         "outcomes": [{"name": "Flamengo", "price": 1.95}, {"name": "Palmeiras", "price": 4.30},
                      {"name": "Draw", "price": 3.85}]}]},
        {"key": "betfair_ex_eu", "last_update": None, "markets": [{"key": "h2h", "last_update": None,
         "outcomes": [{"name": "Flamengo", "price": 1.98}, {"name": "Palmeiras", "price": 4.20},
                      {"name": "Draw", "price": 3.80}]}]},
        {"key": "williamhill", "last_update": None, "markets": [{"key": "h2h", "last_update": None,
         "outcomes": [{"name": "Flamengo", "price": 1.92}, {"name": "Palmeiras", "price": 4.40},
                      {"name": "Draw", "price": 3.90}]}]},
    ],
}]

EVENTS = [{"id": "e1", "sport_key": "soccer_brazil_campeonato", "sport_title": "Brazil Série A",
           "commence_time": "2026-09-30T22:00:00Z",
           "home_team": "Flamengo", "away_team": "Palmeiras"}]

SPORTS = [
    {"key": "soccer_brazil_campeonato", "group": "Soccer", "title": "Brazil Série A", "active": True},
    {"key": "basketball_nba", "group": "Basketball", "title": "NBA", "active": True},
    {"key": "soccer_epl", "group": "Soccer", "title": "EPL", "active": False},
]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A fresh FANDOM_HOME, with one subject already linked to the board."""
    path = tmp_path / "fandom"
    monkeypatch.setenv("FANDOM_HOME", str(path))
    monkeypatch.setenv(odds_source._EDGE_ENV, "https://odds.example.test")
    monkeypatch.delenv(odds_source._KEY_ENV, raising=False)
    store = FandomStore(str(path))
    store.seed_defaults()
    store.add(Team(key="flamengo", name="Flamengo", sport=Sport.FUTEBOL,
                   aliases=["mengão"], odds_sport="soccer_brazil_campeonato",
                   odds_key="Flamengo"))
    store.save()
    return path


@pytest.fixture()
def cli(home):
    """The CLI module, loaded fresh so it reads this test's FANDOM_HOME."""
    sys.modules.pop("fandom_cli", None)
    spec = importlib.util.spec_from_file_location("fandom_cli", SCRIPTS / "fandom.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["fandom_cli"] = module
    spec.loader.exec_module(module)
    return module


def board(cli, *, minutes_to_kickoff=180, quote_age_min=2):
    """The board's answer, stamped relative to the CLI's own clock."""
    from datetime import timedelta
    now = cli.clock.now()
    body = json.loads(json.dumps(BOARD))
    body[0]["commence_time"] = cli.clock.iso(now + timedelta(minutes=minutes_to_kickoff))
    stamp = cli.clock.iso(now - timedelta(minutes=quote_age_min))
    for shop in body[0]["bookmakers"]:
        shop["last_update"] = stamp
        for market in shop["markets"]:
            market["last_update"] = stamp
    return body


def transport(monkeypatch, body, *, status=200, headers=None):
    calls = []

    def fake(url, **_kwargs):
        calls.append(url)
        return status, headers or {}, json.dumps(body).encode()

    monkeypatch.setattr(odds_source.http, "fetch_headers", fake)
    return calls


def run(cli, capsys, *argv):
    sys.argv = ["fandom.py", *argv]
    code = cli.main()
    return code, json.loads(capsys.readouterr().out)


class TestShow:
    def test_a_linked_subject_gets_a_priced_fixture_with_its_age(self, cli, capsys, monkeypatch):
        transport(monkeypatch, board(cli), headers={"x-requests-remaining": "451",
                                                    "x-requests-last": "1"})
        code, payload = run(cli, capsys, "odds", "show", "flamengo")
        assert code == 0
        event = payload["events"][0]
        assert event["home_team"] == "Flamengo" and event["books"] == 3
        assert event["age_minutes"] == 0 and event["stale"] is False
        assert sum(row["p"] for row in event["outcomes"]) == pytest.approx(1.0, abs=1e-3)
        assert payload["budget"]["remaining"] == 451

    def test_an_unlinked_subject_is_named_as_a_token_not_a_sentence(self, cli, capsys, monkeypatch):
        transport(monkeypatch, board(cli))
        _code, payload = run(cli, capsys, "odds", "show")
        reasons = {entry["reason"] for entry in payload["unlinked"]}
        assert reasons == {"unlinked"}
        assert {entry["key"] for entry in payload["unlinked"]} >= {"cs2", "cblol"}

    def test_no_spend_reads_the_cache_and_touches_no_transport(self, cli, capsys, monkeypatch):
        calls = transport(monkeypatch, board(cli), headers={"x-requests-last": "1"})
        run(cli, capsys, "odds", "show", "flamengo")
        before = len(calls)
        _code, payload = run(cli, capsys, "odds", "show", "flamengo", "--no-spend")
        assert len(calls) == before
        assert payload["events"], "the cached reading should still answer"

    def test_the_method_travels_with_the_answer(self, cli, capsys, monkeypatch):
        transport(monkeypatch, board(cli))
        _code, payload = run(cli, capsys, "odds", "show", "flamengo",
                             "--method", "proportional")
        assert payload["method"] == "proportional"
        assert payload["events"][0]["method"] == "proportional"


class TestSecret:
    def test_the_key_never_reaches_the_disk(self, cli, capsys, monkeypatch, home):
        """The test that does not trust the design and reads the bytes.

        AGENTS.md says nothing under FANDOM_HOME carries a credential. This
        walks the whole tree after a full run and checks.
        """
        monkeypatch.setenv(odds_source._KEY_ENV, KEY)
        transport(monkeypatch, board(cli), headers={"x-requests-last": "1"})
        run(cli, capsys, "odds", "show", "flamengo")
        written = [path for path in home.rglob("*") if path.is_file()]
        assert written, "the run wrote nothing at all"
        for path in written:
            assert KEY.encode() not in path.read_bytes(), f"{path.name} carries the key"
            assert b"apikey" not in path.read_bytes().lower(), f"{path.name} carries the parameter"

    def test_the_health_record_is_keyed_by_a_redacted_url(self, cli, capsys, monkeypatch, home):
        monkeypatch.setenv(odds_source._KEY_ENV, KEY)
        transport(monkeypatch, board(cli), headers={"x-requests-last": "1"})
        _code, payload = run(cli, capsys, "odds", "show", "flamengo")
        health = json.loads((home / "sources.json").read_text())
        keyed = [url for url in health["sources"] if "odds" in url]
        assert keyed and all(KEY not in url for url in keyed)
        assert payload["sources"]["answered"] == 1


class TestQuota:
    def test_a_429_is_an_outage_not_a_crash(self, cli, capsys, monkeypatch):
        transport(monkeypatch, board(cli))
        run(cli, capsys, "odds", "show", "flamengo")          # one good reading first
        transport(monkeypatch, [], status=429, headers={"x-requests-remaining": "0"})
        code, payload = run(cli, capsys, "odds", "show", "flamengo")
        assert code == 0
        assert payload["sources"]["degraded"] or payload["sources"]["down"]
        assert [entry["reason"] for entry in payload["spend"]] == ["error"]

    def test_the_cached_line_still_answers_with_its_age(self, cli, capsys, monkeypatch):
        transport(monkeypatch, board(cli), headers={"x-requests-last": "1"})
        run(cli, capsys, "odds", "show", "flamengo")
        transport(monkeypatch, [], status=429)
        _code, payload = run(cli, capsys, "odds", "show", "flamengo")
        assert payload["events"], "a spent quota must not erase what was already read"
        assert payload["events"][0]["age_minutes"] is not None

    def test_the_budget_counts_the_header_not_the_estimate(self, cli, capsys, monkeypatch):
        """markets x regions says 1; the board charged 4. The ledger believes
        the board."""
        transport(monkeypatch, board(cli), headers={"x-requests-last": "4"})
        _code, payload = run(cli, capsys, "odds", "show", "flamengo")
        assert payload["budget"]["spent_30d"] == 4
        assert payload["spend"][0]["cost"] == 4

    def test_the_daily_budget_stops_the_call_before_it_is_made(self, cli, capsys, monkeypatch):
        calls = transport(monkeypatch, board(cli), headers={"x-requests-last": "9"})
        run(cli, capsys, "odds", "show", "flamengo")
        before = len(calls)
        _code, payload = run(cli, capsys, "odds", "show", "flamengo")
        assert len(calls) == before, "the gate is after the spending, not before it"
        assert payload["spend"] == [{"sport_key": "soccer_brazil_campeonato",
                                     "reason": "daily_budget", "cost": 0}]

    def test_an_unconfigured_board_is_an_absence_not_an_error(self, cli, capsys, monkeypatch):
        monkeypatch.delenv(odds_source._EDGE_ENV, raising=False)
        code, payload = run(cli, capsys, "odds", "show", "flamengo")
        assert code == 0
        assert payload["spend"] == [{"sport_key": "soccer_brazil_campeonato",
                                     "reason": "unconfigured", "cost": 0}]


class TestLink:
    def test_without_a_sport_key_it_offers_the_competitions_of_that_sport(self, cli, capsys, monkeypatch):
        transport(monkeypatch, SPORTS)
        _code, payload = run(cli, capsys, "odds", "link", "flamengo")
        assert [sport["sport_key"] for sport in payload["sports"]] == ["soccer_brazil_campeonato"]
        assert payload["cost"] == 0

    def test_an_esports_subject_is_told_the_board_has_none(self, cli, capsys, monkeypatch):
        calls = transport(monkeypatch, SPORTS)
        _code, payload = run(cli, capsys, "odds", "link", "cs2")
        assert payload["reason"] == "sport_not_covered" and payload["sports"] == []
        assert calls == [], "an answer we already know must not cost a call"

    def test_with_a_sport_key_it_ranks_the_boards_spellings(self, cli, capsys, monkeypatch):
        transport(monkeypatch, EVENTS)
        _code, payload = run(cli, capsys, "odds", "link", "flamengo",
                             "--sport-key", "soccer_brazil_campeonato")
        assert payload["candidates"][0]["name"] == "Flamengo"
        assert payload["cost"] == 0

    def test_a_name_the_board_does_not_spell_is_refused(self, cli, capsys, monkeypatch):
        """A near match here is the wrong club, so nothing is accepted on faith."""
        transport(monkeypatch, EVENTS)
        code, payload = run(cli, capsys, "odds", "link", "flamengo",
                            "--sport-key", "soccer_brazil_campeonato", "--name", "Flamengo RJ")
        assert code == 2 and "error" in payload

    def test_committing_a_name_stores_it_exactly(self, cli, capsys, monkeypatch, home):
        transport(monkeypatch, EVENTS)
        _code, payload = run(cli, capsys, "odds", "link", "brasileirao",
                             "--sport-key", "soccer_brazil_campeonato", "--name", "Palmeiras")
        assert payload["linked"]["odds_linked"] is True
        stored = FandomStore(str(home)).get("brasileirao")
        assert (stored.odds_sport, stored.odds_key) == ("soccer_brazil_campeonato", "Palmeiras")

    def test_a_league_link_takes_the_whole_board(self, cli, capsys, monkeypatch, home):
        transport(monkeypatch, EVENTS)
        _code, payload = run(cli, capsys, "odds", "link", "brasileirao",
                             "--sport-key", "soccer_brazil_campeonato", "--league")
        assert payload["scope"] == "league"
        stored = FandomStore(str(home)).get("brasileirao")
        assert stored.odds_sport == "soccer_brazil_campeonato" and stored.odds_key is None


class TestDigest:
    def test_the_digest_spends_nothing(self, cli, capsys, monkeypatch):
        """Three leagues every morning is ninety credits a month for a block
        most mornings have no game to fill."""
        transport(monkeypatch, board(cli), headers={"x-requests-last": "1"})
        run(cli, capsys, "odds", "show", "flamengo")

        def explode(url, **_kwargs):
            raise AssertionError(f"the digest reached for the board: {url}")

        monkeypatch.setattr(odds_source.http, "fetch_headers", explode)
        monkeypatch.setattr(cli.sources_module, "sweep", lambda plan: ([], []))
        code, payload = run(cli, capsys, "digest")
        assert code == 0
        assert payload["odds"]["events"][0]["home_team"] == "Flamengo"

    def test_the_digest_omits_a_line_older_than_its_horizon(self, cli, capsys, monkeypatch):
        """Better silent than opening the morning with the day before yesterday."""
        transport(monkeypatch, board(cli, minutes_to_kickoff=60 * 60), headers={"x-requests-last": "1"})
        run(cli, capsys, "odds", "show", "flamengo")
        monkeypatch.setattr(cli.sources_module, "sweep", lambda plan: ([], []))
        _code, payload = run(cli, capsys, "digest")
        assert payload["odds"]["events"] == []
