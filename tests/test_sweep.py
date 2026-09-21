"""The global sweep plan: distinct URLs, stable order, failure as a value."""

import pytest

from fandom import config, sources
from fandom.models import Sport, Team
from fandom.sources import rss
from fandom.sources.base import PlannedSource
from kit.http import HttpError


def _team(key, name, sport, aliases=(), feeds=()):
    return Team(key=key, name=name, sport=sport, aliases=list(aliases), feeds=list(feeds))


SEEDLIKE = [
    _team("brasileirao", "Brasileirão", Sport.FUTEBOL),
    _team("nba", "NBA", Sport.BASQUETE),
    _team("cblol", "CBLOL", Sport.ESPORTS),
    _team("cs2", "CS2", Sport.ESPORTS),
]


class TestPlan:
    def test_a_shared_feed_is_planned_once(self):
        """Two esports subjects, one set of esports feeds, no duplicate reads."""
        plan = sources.sweep_plan(SEEDLIKE, language="pt-BR")
        urls = [source.url for source in plan]
        assert len(urls) == len(set(urls))

    def test_every_subject_still_gets_its_own_query(self):
        plan = sources.sweep_plan(SEEDLIKE, language="pt-BR")
        queries = [s.url for s in plan if "news.google.com" in s.url]
        assert len(queries) == len(SEEDLIKE)

    def test_order_is_stable_across_calls(self):
        first = [s.url for s in sources.sweep_plan(SEEDLIKE, language="pt-BR")]
        second = [s.url for s in sources.sweep_plan(SEEDLIKE, language="pt-BR")]
        assert first == second

    def test_a_subjects_own_feed_comes_first(self):
        team = _team("arsenal", "Arsenal", Sport.FUTEBOL, feeds=["https://arsenal.test/rss"])
        plan = sources.sweep_plan([team], language="en-US")
        assert plan[0].url == "https://arsenal.test/rss"

    def test_label_is_the_host(self):
        plan = sources.sweep_plan([SEEDLIKE[0]], language="pt-BR")
        assert plan[0].label == "ge.globo.com"


class TestSweep:
    def test_one_dead_source_never_hides_the_others(self, monkeypatch):
        def selective(url, **kw):
            if "ge.globo" in url:
                raise HttpError("blocked")
            return 200, (b'<?xml version="1.0"?><rss version="2.0"><channel>'
                         b'<item><title>Brasileirao roundup</title>'
                         b'<link>https://ok.test/1</link></item></channel></rss>')

        monkeypatch.setattr(rss.http, "fetch", selective)
        plan = sources.sweep_plan([SEEDLIKE[0]], language="pt-BR")
        items, outcomes = sources.sweep(plan)
        assert items, "the feeds that answered must still deliver"
        assert any(not o.ok for o in outcomes)
        assert any(o.ok for o in outcomes)
        assert sources.failures(outcomes) == ["ge.globo.com: blocked"]

    def test_worker_count_never_changes_the_result(self, monkeypatch):
        body = (b'<?xml version="1.0"?><rss version="2.0"><channel>'
                b'<item><title>NBA tonight</title>'
                b'<link>https://ok.test/nba</link></item></channel></rss>')
        monkeypatch.setattr(rss.http, "fetch", lambda url, **kw: (200, body))
        plan = sources.sweep_plan(SEEDLIKE, language="pt-BR")
        serial = [i.link for i in sources.sweep(plan, max_workers=1)[0]]
        parallel = [i.link for i in sources.sweep(plan, max_workers=4)[0]]
        assert serial == parallel

    def test_an_empty_plan_is_not_an_error(self):
        assert sources.sweep([]) == ([], [])

    def test_read_source_returns_failure_never_raises(self, monkeypatch):
        def boom(url, **kw):
            raise HttpError("down")

        monkeypatch.setattr(rss.http, "fetch", boom)
        outcome = sources.read_source(PlannedSource(url="https://x.test/f", label="x.test"))
        assert outcome.ok is False
        assert "down" in outcome.error


class TestFeedsForLanguage:
    def test_a_brazilian_gets_home_and_abroad(self):
        urls = config.feeds_for("futebol", "pt-BR")
        assert "https://ge.globo.com/rss/ge/" in urls
        assert any("bbci.co.uk" in url for url in urls)
        assert urls[0] == "https://ge.globo.com/rss/ge/", "home first"

    def test_an_american_is_not_served_brazilian_feeds(self):
        urls = config.feeds_for("futebol", "en-US")
        assert not any("globo.com" in url for url in urls)
        assert urls

    def test_an_unset_language_keeps_the_seeds_reach(self):
        """Onboarding has not asked yet and the seed is Brazilian."""
        urls = config.feeds_for("futebol", "")
        assert any("globo.com" in url for url in urls)
        assert any("bbci.co.uk" in url for url in urls)

    def test_esports_has_dedicated_feeds_now(self):
        urls = config.feeds_for("esports", "pt-BR")
        assert urls, "esports used to live entirely off the Google News query"
        assert not any(url.endswith("/sport/rss.xml") for url in urls)

    def test_an_unknown_sport_is_empty_not_an_error(self):
        assert config.feeds_for("handebol", "pt-BR") == []
        assert config.feeds_for("", "") == []

    def test_no_bucket_repeats_a_url(self):
        for sport, buckets in config.FEEDS.items():
            for language, urls in buckets.items():
                assert len(urls) == len(set(urls)), f"{sport}/{language} repeats a URL"
                assert all(url.startswith("https://") for url in urls)
