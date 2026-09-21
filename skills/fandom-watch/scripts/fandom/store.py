"""The followed-teams store, the news cache and source health: JSON, written whole."""

from __future__ import annotations

import re
from typing import Any

from kit.jsonio import load_json, save_json_atomic

from fandom.models import Sport, Team

_TEAMS_FILE = "teams.json"
_NEWS_FILE = "news.json"
_HEALTH_FILE = "sources.json"


def teams_path(home: str) -> str:
    return f"{home}/{_TEAMS_FILE}"


def news_path(home: str) -> str:
    return f"{home}/{_NEWS_FILE}"


def health_path(home: str) -> str:
    return f"{home}/{_HEALTH_FILE}"


def team_key_for(name: str) -> str:
    """A stable slug: 'São Paulo FC' and 'sao paulo' land on the same team."""
    import unicodedata
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


class FandomStore:
    """Followed teams plus the last fetched news cache, loaded once."""

    def __init__(self, home: str) -> None:
        self.home = home
        raw = load_json(teams_path(home), {"teams": []}) or {}
        self.teams: dict[str, Team] = {
            data["key"]: Team.from_dict(data) for data in raw.get("teams", [])
        }
        # How each source has behaved across runs, keyed by URL. Read by the
        # health engine; a single run cannot tell a hiccup from a week of silence.
        self.health: dict[str, Any] = load_json(health_path(home), {"sources": {}}) or {}

    def save(self) -> None:
        save_json_atomic(teams_path(self.home),
                         {"teams": [team.as_dict() for team in self.teams.values()]})

    def save_news(self, items: list[dict[str, Any]]) -> None:
        """The last run's matched items, for inspection.

        Nothing reads this back, and that is on purpose. It used to be loaded
        into `self.news_cache` on every construction, which made it look like a
        cache -- but no caller ever consulted it, so it was load cost for
        nothing. Serving yesterday's headlines as today's would break the rule
        the persona is built on: if it did not come out of today's script, it
        is not today's news.
        """
        save_json_atomic(news_path(self.home), {"items": items})

    def save_health(self, health: dict[str, Any]) -> None:
        save_json_atomic(health_path(self.home), health)

    def seed_defaults(self) -> bool:
        """Install the BR seed once, into an empty store only."""
        if self.teams:
            return False
        for raw in self.config_seed():
            team = Team.from_dict({**raw, "sport": str(raw["sport"])})
            self.teams[team.key] = team
        self.save()
        return True

    @staticmethod
    def config_seed() -> list[dict[str, Any]]:
        from fandom import config
        return config.SEED_TEAMS

    def add(self, team: Team) -> Team:
        self.teams[team.key] = team
        return team

    def remove(self, key: str) -> Team:
        return self.teams.pop(key)

    def all(self) -> list[Team]:
        return sorted(self.teams.values(), key=lambda team: team.key)

    def get(self, key: str) -> Team:
        if key not in self.teams:
            raise KeyError(f"not following {key!r}")
        return self.teams[key]

    def compact_view(self, team: Team) -> dict[str, Any]:
        return {
            "key": team.key, "name": team.name, "sport": str(team.sport),
            "league": team.league, "aliases": team.aliases,
            "source_id": team.source_id, "extra_feeds": len(team.feeds),
            "odds_linked": bool(team.odds_sport),
        }
