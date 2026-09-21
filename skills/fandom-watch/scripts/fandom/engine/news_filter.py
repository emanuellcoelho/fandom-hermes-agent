"""The news filter -- pure: normalization, alias matching, topic classification.

No IO here. Headlines come in, relevance decisions come out, all testable
against saved fixtures.
"""

from __future__ import annotations

import unicodedata

from fandom.models import NewsItem, Team

_TRANSFER_KEYWORDS = (
    "contrata", "contratação", "reforço", "negocia", "negociação", "propõe",
    "proposta", "janela", "rescisão", "despedida", "anuncia",
    "transfer", "signs", "signing", "deal", "free agent", "trade", "bid",
)


def normalize(text: str) -> str:
    """Lower, accent-free, punctuation as space, whitespace-collapsed:
    'São Paulo' == 'sao paulo', 'Timão!' == 'timao'."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode()
    spaced = "".join(ch if ch.isalnum() else " " for ch in ascii_text)
    return " ".join(spaced.lower().split())


_TRANSFER_NEEDLES = tuple(normalize(keyword) for keyword in (
    "contrata", "contratação", "reforço", "negocia", "negociação", "propõe",
    "proposta", "janela", "rescisão", "despedida", "anuncia",
    "transfer", "signs", "signing", "deal", "free agent", "trade", "bid",
))


def team_matches(item: NewsItem, team: Team) -> bool:
    """Whether a headline is about this team -- aliases decide, never guesses."""
    haystack = normalize(item.title)
    needles = [normalize(team.name), *(normalize(alias) for alias in team.aliases)]
    return any(needle and needle in haystack for needle in needles)


def classify(item: NewsItem) -> str:
    """'transfer' when the headline smells like the market, 'general' else."""
    haystack = normalize(item.title)
    return "transfer" if any(needle in haystack for needle in _TRANSFER_NEEDLES) else "general"


def filter_news(items: list[NewsItem], teams: list[Team]) -> dict[str, list[NewsItem]]:
    """Items grouped by followed team, newest first, deduped by link.

    One headline can serve two teams; each team's list is independent.
    """
    seen: set[str] = set()
    buckets: dict[str, list[NewsItem]] = {team.key: [] for team in teams}
    # The link breaks ties on the timestamp. Sources are read concurrently now,
    # so arrival order is no longer stable between runs -- without a tiebreak,
    # two headlines published in the same second could swap places run to run,
    # and with dedup-by-link that changes which copy survives.
    for item in sorted(items, key=lambda i: (i.published_at, i.link), reverse=True):
        if item.link in seen:
            continue
        seen.add(item.link)
        for team in teams:
            if team_matches(item, team):
                buckets[team.key].append(item)
    return buckets
