"""The data model: followed teams, news items, matches. Serialization is
explicit -- the store files are contracts, not dict dumps."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Sport(StrEnum):
    FUTEBOL = "futebol"
    BASQUETE = "basquete"
    FUTEBOL_AMERICANO = "futebol_americano"
    ESPORTS = "esports"

    @classmethod
    def parse(cls, raw: str) -> "Sport":
        """The sport by any of its names, including the English ones.

        The stored values stay Portuguese because the store files are
        contracts and renaming them would orphan every existing home. What
        widens is the door: a user who says "basketball" is not asking for a
        different sport than one who says "basquete", and answering
        `unknown sport` to the first is a bug, not a language policy.

        "football" resolves to futebol, the way most of the world uses the
        word; American football answers to "american football" and "nfl".
        """
        key = "_".join(str(raw).strip().lower().replace("-", " ").split())
        return cls(_SPORT_ALIASES.get(key, key))


_SPORT_ALIASES = {
    "soccer": Sport.FUTEBOL,
    "football": Sport.FUTEBOL,
    "futbol": Sport.FUTEBOL,
    "fútbol": Sport.FUTEBOL,
    "basketball": Sport.BASQUETE,
    "basket": Sport.BASQUETE,
    "nba": Sport.BASQUETE,
    "american_football": Sport.FUTEBOL_AMERICANO,
    "americanfootball": Sport.FUTEBOL_AMERICANO,
    "nfl": Sport.FUTEBOL_AMERICANO,
    "e_sports": Sport.ESPORTS,
    "esport": Sport.ESPORTS,
    "gaming": Sport.ESPORTS,
}


@dataclass
class Team:
    """A followed subject: a team, a league, or an esports scene.

    The model is deliberately wider than a club -- "Brasileirão" and "CBLOL"
    follow the same news pipeline a club does, and aliases are what match
    headlines, so they carry nicknames and normalized spellings.
    """

    key: str                          # stable slug, dedup key
    name: str
    sport: Sport
    aliases: list[str] = field(default_factory=list)
    league: str | None = None
    feeds: list[str] = field(default_factory=list)  # extra, team-specific RSS
    source_id: str | None = None      # TheSportsDB team id, when known

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "sport": str(self.sport),
            "aliases": self.aliases, "league": self.league,
            "feeds": self.feeds, "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Team":
        return cls(
            key=raw["key"], name=raw["name"], sport=Sport(raw.get("sport", Sport.FUTEBOL)),
            aliases=list(raw.get("aliases", [])), league=raw.get("league"),
            feeds=list(raw.get("feeds", [])), source_id=raw.get("source_id"),
        )


@dataclass
class NewsItem:
    """One headline, from any feed."""

    title: str
    link: str
    published_at: str                 # ISO instant, best effort from the feed
    source: str                       # feed host, for degradation reporting

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "link": self.link,
                "published_at": self.published_at, "source": self.source}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NewsItem":
        return cls(title=raw["title"], link=raw["link"],
                   published_at=raw.get("published_at", ""), source=raw.get("source", ""))


@dataclass
class Match:
    """A fixture or result, best-effort from any provider."""

    when: str                         # ISO date (+time when the provider has it)
    competition: str
    home: str
    away: str
    status: str                       # "scheduled" | "finished" | "unknown"
    score: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"when": self.when, "competition": self.competition, "home": self.home,
                "away": self.away, "status": self.status, "score": self.score}
