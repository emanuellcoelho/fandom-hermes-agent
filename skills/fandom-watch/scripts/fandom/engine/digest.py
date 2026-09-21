"""The digest payload: what the morning message says, as data. Pure."""

from __future__ import annotations

from typing import Any

from kit import clock

from fandom.engine import news_filter
from fandom.models import Team, NewsItem


def build(teams: list[Team], items: list[NewsItem], failed_sources: list[str],
          *, per_team_limit: int = 5, sources: dict[str, Any] | None = None,
          odds: dict[str, Any] | None = None) -> dict[str, Any]:
    """Teams with their headlines, transfers flagged, failures named."""
    buckets = news_filter.filter_news(items, teams)
    followed: list[dict[str, Any]] = []
    for team in teams:
        team_items = buckets[team.key]
        transfers = [item.as_dict() for item in team_items
                     if news_filter.classify(item) == "transfer"][:3]
        followed.append({
            "team": team.name, "key": team.key, "sport": str(team.sport),
            "count": len(team_items),
            "top": [item.as_dict() for item in team_items[:per_team_limit]],
            "transfers": transfers,
        })
    return {
        "at": clock.iso(),
        "teams": followed,
        # Shared feeds are swept once per followed team, so the same dead feed
        # is reported once per team -- the digest needs it once, period.
        "failed_sources": sorted(set(failed_sources)),
        "quiet": bool(teams) and all(entry["count"] == 0 for entry in followed),
        "sources_read": len(items),
        # Built by the caller, which is what reads and writes the health file:
        # this stays pure.
        "sources": sources or {},
        # Read from the odds cache by the caller, never fetched here. The
        # morning message spends no credit: three leagues every day is ninety
        # a month for a block most mornings have no game to fill.
        "odds": odds or {},
    }
