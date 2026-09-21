"""The RSS reader against real saved feeds: ge.globo, BBC, malformed bodies."""

import pytest

from fandom.sources import rss
from kit.http import HttpError


class TestRealFeeds:
    def test_ge_globo_parses_all_items(self, ge_feed):
        items = rss.parse(ge_feed, "ge.globo.com")
        assert len(items) >= 80
        assert items[0].title and items[0].link.startswith("http")
        assert items[0].source == "ge.globo.com"

    def test_bbc_parses_all_items(self, bbc_feed):
        items = rss.parse(bbc_feed, "bbc")
        assert len(items) >= 50

    def test_filter_finds_brasileirao_in_real_ge_feed(self, ge_feed):
        from fandom.engine.news_filter import filter_news
        from fandom.models import Sport, Team
        items = rss.parse(ge_feed, "ge")
        seed = Team(key="brasileirao", name="Brasileirão", sport=Sport.FUTEBOL,
                    aliases=["flamengo", "palmeiras", "corinthians", "brasileirão"])
        buckets = filter_news(items, [seed])
        assert len(buckets["brasileirao"]) > 0


class TestEdgeCases:
    def test_malformed_xml_is_a_feed_error(self):
        with pytest.raises(rss.FeedError):
            rss.parse(b"<html>not xml at all", "broken")

    def test_empty_feed_yields_nothing(self):
        assert rss.parse(b"<rss><channel></channel></rss>", "empty") == []

    def test_atom_entries_parse(self):
        atom = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                b'<title>PSG x Marseille</title>'
                b'<link href="https://x/atom/1"/><updated>2026-09-13T10:00:00Z</updated>'
                b'</entry></feed>')
        items = rss.parse(atom, "atom.example")
        assert len(items) == 1 and items[0].link == "https://x/atom/1"

    def test_http_error_raises_feed_error(self, monkeypatch):
        monkeypatch.setattr(rss.http, "fetch", lambda url, **kw: (403, b"denied"))
        with pytest.raises(rss.FeedError):
            rss.fetch_feed("https://ge.example/rss")


class TestCollect:
    def test_dead_feed_degrades_never_dies(self, monkeypatch):
        from fandom.sources import collect_news
        def boom(url, **kw):
            raise HttpError("blocked")
        monkeypatch.setattr(rss.http, "fetch", boom)
        items, failed = collect_news([], "futebol")
        assert items == []
        assert len(failed) >= 2  # both futebol feeds reported as degraded
class TestWhatCountsAsAFeed:
    """The root-element gate: feed shapes pass, pages do not, quiet stays quiet."""

    def test_rss_1_0_rdf_parses(self):
        body = (b'<?xml version="1.0"?>'
                b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
                b' xmlns="http://purl.org/rss/1.0/"><channel/>'
                b'<item><title>Lakers sign a guard</title>'
                b'<link>https://example.test/a</link></item></rdf:RDF>')
        assert len(rss.parse(body, "example.test")) == 1

    def test_byte_order_mark_does_not_break_the_gate(self):
        body = (b'\xef\xbb\xbf<?xml version="1.0"?><rss version="2.0"><channel>'
                b'<item><title>Arsenal draw</title>'
                b'<link>https://example.test/b</link></item></channel></rss>')
        assert len(rss.parse(body, "example.test")) == 1

    def test_bot_wall_names_the_root(self):
        body = b'<!DOCTYPE html><html><body><p>Checking your browser</p></body></html>'
        with pytest.raises(rss.FeedError) as caught:
            rss.parse(body, "espn.com")
        assert "not a feed" in str(caught.value)
        assert "html" in str(caught.value)

    def test_xhtml_challenge_page_is_rejected(self):
        body = (b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Just a moment'
                b'</title></head><body/></html>')
        with pytest.raises(rss.FeedError):
            rss.parse(body, "espn.com")

    def test_empty_body_says_so(self):
        with pytest.raises(rss.FeedError) as caught:
            rss.parse(b"   ", "espn.com")
        assert "empty response body" in str(caught.value)

    def test_json_error_payload_is_rejected(self):
        with pytest.raises(rss.FeedError):
            rss.parse(b'{"error": "rate limited"}', "api.example.test")

    def test_quiet_feed_still_yields_nothing_not_an_error(self):
        """The false-positive guard, stated once more next to its neighbours."""
        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        assert rss.parse(body, "example.test") == []
