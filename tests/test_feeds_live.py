"""Every configured feed, fetched the way production fetches it.

This exists because of a specific failure. `config.FEEDS` carried the comment
"feeds that proved alive on 2026-09-13" -- and they had been proved alive with
curl, under a different User-Agent and a different idea of which status codes
count. Through `kit.http`, three of them answered HTTP 202 with an empty body
and had been dead for days. A feed is alive only if THIS path says so.

What this test cannot see: it answers for the network it runs on. Every ESPN
feed passed here from a laptop while answering 202 with an empty body to the
container that actually reads them -- a residential address is welcome where a
datacenter one is not, and no test run from a desk can tell you that. A green
run proves the URL and the parser, never that production can reach it; the
container has to be asked directly.

Off by default: it is the one test that touches the network.

    FANDOM_LIVE_FEEDS=1 python -m pytest tests/test_feeds_live.py -q
"""

import os

import pytest

from fandom import config
from fandom.sources import rss
from kit import http

pytestmark = pytest.mark.skipif(
    not os.environ.get("FANDOM_LIVE_FEEDS"),
    reason="network test; set FANDOM_LIVE_FEEDS=1 to run",
)


def _every_url(feeds) -> list[str]:
    """Flatten FEEDS whatever its shape -- per sport, or per sport and language."""
    urls: list[str] = []
    def walk(node):
        if isinstance(node, str):
            urls.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        else:
            for value in node:
                walk(value)
    walk(feeds)
    return sorted(set(urls))


@pytest.mark.parametrize("url", _every_url(config.FEEDS))
def test_feed_answers_and_parses(url):
    status, body = http.fetch(url)
    assert status == 200, f"{url} answered HTTP {status}"
    items = rss.parse(body, url)
    assert items, f"{url} parsed as a feed but carried no items"
