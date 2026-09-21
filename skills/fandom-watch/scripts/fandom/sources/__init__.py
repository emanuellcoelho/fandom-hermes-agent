"""News sources: RSS feeds, TheSportsDB. One dead source never kills a digest.

The sweep is global, not per subject. Nothing downstream depends on which
subject a feed was fetched for -- `news_filter` re-groups every item by alias
afterwards -- so planning by URL costs nothing and buys two things: a shared
feed is read once instead of three times, and a dead one is reported once
instead of three times.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fandom.sources import gnews, rss, thesportsdb
from fandom.sources.base import PlannedSource, SourceError, SourceOutcome

__all__ = ["PlannedSource", "SourceError", "SourceOutcome", "gnews", "rss",
           "sweep", "sweep_plan", "thesportsdb"]


def _label_for(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def urls_for(team, *, language: str = "") -> list[str]:
    """Every URL one subject's news comes from, in order of preference.

    The subject's own feeds first -- whoever added one knew what they wanted --
    then the sport's feeds for this user's language, then the subject's Google
    News query, which is what keeps scenes without a live dedicated feed
    supplied.
    """
    from fandom import config
    urls = list(team.feeds) + config.feeds_for(str(team.sport), language)
    query = gnews.search_url(gnews.terms_for(team.name, team.aliases), language)
    if query:
        urls.append(query)
    return urls


def sweep_plan(teams, *, language: str = "") -> list[PlannedSource]:
    """Every distinct URL the followed set needs, in a stable order."""
    seen: dict[str, PlannedSource] = {}
    for team in teams:
        for url in urls_for(team, language=language):
            seen.setdefault(url, PlannedSource(url=url, label=_label_for(url)))
    return list(seen.values())


def read_source(source: PlannedSource, *, timeout_s: float = 8.0) -> SourceOutcome:
    """Read one planned source. Never raises: failure is a returned value."""
    try:
        items = rss.fetch_feed(source.url, timeout_s=timeout_s)
    except Exception as error:  # one feed's failure is never the sweep's
        return SourceOutcome(url=source.url, label=source.label, ok=False,
                             error=str(error))
    return SourceOutcome(url=source.url, label=source.label, ok=True,
                         items=tuple(items))


def sweep(plan: list[PlannedSource], *, max_workers: int = 4,
          timeout_s: float = 8.0) -> tuple[list, list[SourceOutcome]]:
    """Read the whole plan concurrently; return every item and every outcome.

    `executor.map` and not `as_completed`: it yields in submission order, so
    the item list and the failure list stay deterministic run to run, which is
    what makes them testable. A slow feed now costs one timeout instead of
    adding its timeout to everyone else's.
    """
    if not plan:
        return [], []
    workers = max(1, min(max_workers, len(plan)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(lambda s: read_source(s, timeout_s=timeout_s), plan))
    items = [item for outcome in outcomes for item in outcome.items]
    return items, outcomes


def failures(outcomes: list[SourceOutcome]) -> list[str]:
    """The legacy `failed_sources` shape: one line per source that did not answer."""
    return [outcome.as_failure_line() for outcome in outcomes if not outcome.ok]
