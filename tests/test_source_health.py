"""Source health across runs: a hiccup and a week of silence must read differently."""

from datetime import datetime, timedelta, timezone

import pytest

from fandom.engine import source_health as sh
from fandom.sources.base import SourceOutcome

T0 = datetime(2026, 9, 21, 8, 30, tzinfo=timezone.utc)


def ok(url="https://espn.test/nba", label="espn.test"):
    return SourceOutcome(url=url, label=label, ok=True, items=())


def bad(url="https://espn.test/nba", label="espn.test", error="answered HTTP 503"):
    return SourceOutcome(url=url, label=label, ok=False, error=error)


def run(health, outcomes, at):
    return sh.record(health, outcomes, now=at)


class TestClassify:
    def test_a_source_that_answered_is_ok(self):
        health = run({}, [ok()], T0)
        assert sh.classify(health["sources"][ok().url], now=T0) == "ok"

    def test_one_failure_after_a_success_is_only_flaky(self):
        health = run({}, [ok()], T0)
        health = run(health, [bad()], T0 + timedelta(minutes=5))
        entry = health["sources"][ok().url]
        assert sh.classify(entry, now=T0 + timedelta(minutes=5)) == "flaky"

    def test_three_failures_within_the_hour_are_still_flaky(self):
        """Asking for news six times on a bad morning is not a dead feed."""
        health = run({}, [ok()], T0)
        for minutes in (5, 10, 15):
            health = run(health, [bad()], T0 + timedelta(minutes=minutes))
        entry = health["sources"][ok().url]
        assert entry["consecutive_failures"] == 3
        assert sh.classify(entry, now=T0 + timedelta(minutes=15)) == "flaky"

    def test_three_failures_and_a_day_of_silence_is_down(self):
        health = run({}, [ok()], T0)
        later = T0 + timedelta(hours=26)
        for offset in (0, 1, 2):
            health = run(health, [bad()], later + timedelta(minutes=offset))
        entry = health["sources"][ok().url]
        assert sh.classify(entry, now=later) == "down"

    def test_a_success_clears_the_streak(self):
        health = run({}, [bad(), ], T0)
        health = run(health, [bad()], T0 + timedelta(hours=30))
        health = run(health, [ok()], T0 + timedelta(hours=31))
        entry = health["sources"][ok().url]
        assert entry["consecutive_failures"] == 0
        assert sh.classify(entry, now=T0 + timedelta(hours=31)) == "ok"

    def test_a_brand_new_source_is_not_called_dead_immediately(self):
        """A container that booted without network for a minute is not an outage."""
        health = run({}, [bad()], T0)
        for offset in (1, 2):
            health = run(health, [bad()], T0 + timedelta(minutes=offset))
        entry = health["sources"][ok().url]
        assert sh.classify(entry, now=T0 + timedelta(minutes=2)) == "flaky"


class TestReport:
    def test_counts_attempted_and_answered(self):
        outcomes = [ok(), bad("https://x.test/f", "x.test")]
        health = run({}, outcomes, T0)
        block = sh.report(health, outcomes, now=T0)
        assert block["attempted"] == 2
        assert block["answered"] == 1

    def test_a_chronic_source_is_announced_once_then_goes_quiet(self):
        health = run({}, [ok()], T0)          # it worked once, so it is not new
        later = T0 + timedelta(hours=30)
        for offset in (0, 1, 2):
            health = run(health, [bad()], later + timedelta(minutes=offset))
        block = sh.report(health, [bad()], now=later)
        assert block["down"] and block["down"][0]["announce"] is True

        health = sh.mark_announced(health, [bad().url], now=later)
        block = sh.report(health, [bad()], now=later + timedelta(days=1))
        assert block["down"][0]["announce"] is False, "no wallpaper"

        block = sh.report(health, [bad()], now=later + timedelta(days=8))
        assert block["down"][0]["announce"] is True, "a week later it is news again"

    def test_coverage_gap_names_the_sport_not_the_urls(self):
        outcomes = [bad("https://hltv.test/rss", "hltv.test"),
                    bad("https://dotesports.test/feed", "dotesports.test")]
        health = run({}, outcomes, T0)
        futebol = ok("https://ge.test/rss", "ge.test")
        outcomes = outcomes + [futebol]
        health = run(health, outcomes, T0)
        block = sh.report(health, outcomes, now=T0,
                          sports_planned={"esports": [o.url for o in outcomes[:2]],
                                          "futebol": [futebol.url]})
        assert block["coverage_gap"] == ["esports"]

    def test_no_gap_when_one_feed_of_the_sport_answered(self):
        outcomes = [ok("https://hltv.test/rss", "hltv.test"),
                    bad("https://dotesports.test/feed", "dotesports.test")]
        health = run({}, outcomes, T0)
        block = sh.report(health, outcomes, now=T0,
                          sports_planned={"esports": [o.url for o in outcomes]})
        assert block["coverage_gap"] == []


class TestPrune:
    def test_a_planned_url_is_always_kept(self):
        health = run({}, [ok()], T0)
        kept = sh.prune(health, [ok().url], now=T0 + timedelta(days=90))
        assert ok().url in kept["sources"]

    def test_an_unplanned_stale_url_is_dropped(self):
        health = run({}, [ok()], T0)
        kept = sh.prune(health, [], now=T0 + timedelta(days=45))
        assert kept["sources"] == {}

    def test_an_unplanned_recent_url_survives(self):
        health = run({}, [ok()], T0)
        kept = sh.prune(health, [], now=T0 + timedelta(days=3))
        assert ok().url in kept["sources"]


class TestPersistence:
    def test_health_survives_a_reload(self, store, tmp_path):
        from fandom.store import FandomStore
        health = run({}, [bad()], T0)
        store.save_health(health)
        again = FandomStore(store.home)
        entry = again.health["sources"][bad().url]
        assert entry["consecutive_failures"] == 1
        assert entry["last_error"] == "answered HTTP 503"
