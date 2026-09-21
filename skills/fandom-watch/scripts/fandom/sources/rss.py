"""RSS reader: RSS 2.0 and Atom, namespace-tolerant, via xml.etree."""

from __future__ import annotations

import email.utils
import xml.etree.ElementTree as ET
from datetime import datetime

from kit import clock, http

from fandom.models import NewsItem


class FeedError(RuntimeError):
    """One feed's failure. A digest survives any of these."""


def _local(tag: str) -> str:
    return tag.rpartition("}")[2].lower()


def _find(node: ET.Element, name: str) -> ET.Element | None:
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _parse_instant(raw: str | None) -> str:
    if not raw:
        return clock.iso()
    for parser in (email.utils.parsedate_to_datetime, datetime.fromisoformat):
        try:
            moment = parser(raw.strip())
            return moment.astimezone(tz=moment.tzinfo).isoformat(timespec="seconds")
        except (ValueError, TypeError):
            continue
    return clock.iso()


# RSS 2.0 roots as <rss>, Atom as <feed>, RSS 1.0 as <RDF>. Anything else that
# still parses is a page, not a feed -- a bot wall or an error screen served
# with HTTP 200. Those used to parse cleanly and yield zero items, which is
# indistinguishable from a quiet day, so a walled feed could stay walled for
# days without a word. The check reads the ROOT ELEMENT and never the item
# count: <rss><channel/></rss> is a real feed with no news today and must keep
# coming back empty, which is what test_empty_feed_yields_nothing guards.
_FEED_ROOTS = ("rss", "feed", "rdf")


def parse(body: bytes, source: str) -> list[NewsItem]:
    """Every item in an RSS or Atom body; raises FeedError when it is not one."""
    if not body.strip():
        raise FeedError(f"{source}: empty response body")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise FeedError(f"{source}: unparseable XML ({error})") from error
    if _local(root.tag) not in _FEED_ROOTS:
        raise FeedError(f"{source}: not a feed (root <{_local(root.tag)}>, {len(body)} bytes)")

    items: list[NewsItem] = []
    for element in root.iter():
        name = _local(element.tag)
        if name == "item":
            # Namespace-tolerant like the Atom branch below: RSS 1.0 puts every
            # child under the purl.org namespace, so `find(".//title")` -- which
            # matches the literal tag -- came back empty on a feed the root gate
            # had just accepted. `_find` matches on the local name instead.
            title_node = _find(element, "title")
            link_node = _find(element, "link")
            title = (title_node.text or "").strip() if title_node is not None else ""
            link = (link_node.text or "").strip() if link_node is not None else ""
            stamp = _find(element, "pubdate")          # RSS 2.0
            if stamp is None:
                stamp = _find(element, "date")          # RSS 1.0 / dc:date
            published = _parse_instant(stamp.text if stamp is not None else None)
            if title and link:
                items.append(NewsItem(title=title, link=link,
                                      published_at=published, source=source))
        elif name == "entry":
            title_node = _find(element, "title")
            link_node = _find(element, "link")
            link = (link_node.get("href") or (link_node.text or "")) if link_node is not None else ""
            title = (title_node.text or "").strip() if title_node is not None else ""
            published = _parse_instant(element.findtext("updated") or element.findtext("published"))
            if title and link:
                items.append(NewsItem(title=title, link=link,
                                      published_at=published, source=source))
    return items


def fetch_feed(url: str, *, timeout_s: float = 8.0) -> list[NewsItem]:
    status, body = http.fetch(url, timeout_s=timeout_s)
    if status != 200:
        raise FeedError(f"{url} answered HTTP {status}")
    source = url.split("//", 1)[-1].split("/", 1)[0]
    return parse(body, source)