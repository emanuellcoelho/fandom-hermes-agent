"""Digest build, store seeding, config contract, TheSportsDB shaping."""

import pytest

from kit import clock

from fandom.config import DEFAULTS, missing_keys
from fandom.engine import matchday
from fandom.engine.digest import build as build_digest
from fandom.models import NewsItem, Sport, Team
from fandom.sources import thesportsdb
from fandom.sources.base import SourceError
from fandom.store import team_key_for


def news(title, link="https://x/1") -> NewsItem:
    return NewsItem(title=title, link=link, published_at=clock.iso(), source="ge")


class TestDigest:
    def test_groups_and_flags_transfers(self, store):
        followed = store.add(Team(key="fla", name="Flamengo", sport=Sport.FUTEBOL,
                                  aliases=["flamengo"]))
        payload = build_digest([followed], [news("Flamengo vence"),
                                            news("Flamengo anuncia reforço", "https://x/2")], [])
        entry = payload["teams"][0]
        assert entry["count"] == 2
        assert entry["transfers"] and "reforço" in entry["transfers"][0]["title"]

    def test_quiet_when_nothing_matched(self, store):
        followed = store.add(Team(key="nba", name="NBA", sport=Sport.BASQUETE, aliases=["nba"]))
        payload = build_digest([followed], [news("Palmeiras vence clássico")], [])
        assert payload["quiet"] is True

    def test_failed_sources_are_named_and_deduped(self, store):
        followed = store.add(Team(key="nba", name="NBA", sport=Sport.BASQUETE, aliases=["nba"]))
        payload = build_digest([followed], [],
                               ["ge.globo.com: blocked", "ge.globo.com: blocked"])
        assert payload["failed_sources"] == ["ge.globo.com: blocked"]
        assert payload["quiet"] is True


class TestStore:
    def test_seed_installs_once_into_empty_store(self, store):
        assert store.seed_defaults() is True
        assert {t.key for t in store.all()} >= {"brasileirao", "cblol", "nba"}
        assert store.seed_defaults() is False  # never over a populated store

    def test_add_remove_roundtrip(self, store):
        added = store.add(Team(key="gremio", name="Grêmio", sport=Sport.FUTEBOL, aliases=["gremio"]))
        store.save()
        reloaded = type(store)(store.home)
        assert reloaded.get("gremio").name == "Grêmio"
        reloaded.remove("gremio")
        with pytest.raises(KeyError):
            reloaded.get("gremio")

    def test_slug_dedups_accents(self):
        assert team_key_for("São Paulo FC") == team_key_for("sao paulo fc")

    def test_a_teams_file_written_before_odds_existed_still_loads(self):
        """Every home already on disk predates odds_sport. None may need a migration."""
        team = Team.from_dict({"key": "gremio", "name": "Grêmio", "sport": "futebol",
                               "aliases": ["gremio"], "source_id": "133739"})
        assert team.odds_sport is None and team.odds_key is None

    def test_the_odds_link_survives_a_save_and_a_reload(self, store):
        store.add(Team(key="flamengo", name="Flamengo", sport=Sport.FUTEBOL,
                       odds_sport="soccer_brazil_campeonato", odds_key="Flamengo"))
        store.save()
        reloaded = type(store)(store.home).get("flamengo")
        assert reloaded.odds_sport == "soccer_brazil_campeonato"
        assert reloaded.odds_key == "Flamengo"
        assert store.compact_view(reloaded)["odds_linked"] is True


class TestConfig:
    def test_missing_keys_on_raw_file(self, tmp_path):
        assert set(missing_keys(str(tmp_path))) == {"timezone", "digest_times", "language"}
        assert DEFAULTS["digest_times"] == ["08:00", "12:00", "18:00"]


class TestTheSportsDB:
    def test_team_search_shapes_candidates(self, sdb_team, monkeypatch):
        monkeypatch.setattr(thesportsdb.http, "fetch",
                            lambda url, **kw: (200, __import__("json").dumps(sdb_team).encode()))
        results = thesportsdb.search_team("Corinthians")
        assert results[0]["id"] == "134284" and results[0]["league"] == "Brazilian Serie A"

    def test_next_matches_shape_a_match(self, monkeypatch):
        payload = ('{"events":[{"dateEvent":"2026-09-14","strLeague":"Brasileirão",'
                   '"strHomeTeam":"Corinthians","strAwayTeam":"Palmeiras",'
                   '"strStatus":"Not Started","intHomeScore":null,"intAwayScore":null}]}').encode()
        monkeypatch.setattr(thesportsdb.http, "fetch", lambda url, **kw: (200, payload))
        matches = thesportsdb.next_matches("134284")
        assert matches[0].home == "Corinthians" and matches[0].status == "scheduled"

    def test_live_score_is_live_not_finished(self, monkeypatch):
        payload = ('{"events":[{"dateEvent":"2026-09-13","strStatus":"1H",'
                   '"strHomeTeam":"Flamengo","strAwayTeam":"Corinthians",'
                   '"intHomeScore":"0","intAwayScore":"0"}]}').encode()
        monkeypatch.setattr(thesportsdb.http, "fetch", lambda url, **kw: (200, payload))
        matches = thesportsdb.next_matches("134284")
        assert matches[0].status == "live" and matches[0].score == "0 x 0"

    def test_free_tier_empty_answers_yield_no_match(self, monkeypatch):
        monkeypatch.setattr(thesportsdb.http, "fetch", lambda url, **kw: (200, b'{"events":null}'))
        assert thesportsdb.next_matches("1") == []


class TestMatchday:
    def test_team_without_source_id_says_so(self, store):
        followed = store.add(Team(key="fla", name="Flamengo", sport=Sport.FUTEBOL, aliases=["fla"]))
        view = matchday.build(followed)
        assert view["fixture"] is None and "provedor" in view["note"]

    def test_dead_provider_degrades_with_note(self, store, monkeypatch):
        followed = store.add(Team(key="fla", name="Flamengo", sport=Sport.FUTEBOL,
                                  aliases=["fla"], source_id="134284"))
        monkeypatch.setattr(thesportsdb.http, "fetch", lambda url, **kw: (403, b"denied"))
        view = matchday.build(followed)
        assert view["fixture"] is None and view["note"]