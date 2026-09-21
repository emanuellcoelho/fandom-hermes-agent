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
    # The odds board is a second id universe that shares nothing with
    # TheSportsDB's: it knows leagues by a sport_key and clubs by the exact
    # spelling it prints. Both are None until a person confirms them, because
    # a probability attached to the wrong club is the one error this agent
    # may not make -- and "Inter" is two different clubs on two continents.
    odds_sport: str | None = None     # "soccer_brazil_campeonato"
    odds_key: str | None = None       # the board's exact spelling of this club

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "sport": str(self.sport),
            "aliases": self.aliases, "league": self.league,
            "feeds": self.feeds, "source_id": self.source_id,
            "odds_sport": self.odds_sport, "odds_key": self.odds_key,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Team":
        return cls(
            key=raw["key"], name=raw["name"], sport=Sport(raw.get("sport", Sport.FUTEBOL)),
            aliases=list(raw.get("aliases", [])), league=raw.get("league"),
            feeds=list(raw.get("feeds", [])), source_id=raw.get("source_id"),
            odds_sport=raw.get("odds_sport"), odds_key=raw.get("odds_key"),
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


@dataclass(frozen=True)
class Quote:
    """One bookmaker's price for one outcome of one market."""

    book: str                         # bookmaker key: "pinnacle", "betfair_ex_eu"
    outcome: str                      # exactly as the board spells it: "Flamengo" | "Draw"
    price: float                      # decimal
    last_update: str = ""             # the book's own ISO instant, not ours

    def as_dict(self) -> dict[str, Any]:
        return {"book": self.book, "outcome": self.outcome,
                "price": self.price, "last_update": self.last_update}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Quote":
        return cls(book=raw["book"], outcome=raw["outcome"],
                   price=float(raw["price"]), last_update=raw.get("last_update", ""))


@dataclass
class OddsEvent:
    """One fixture as the odds board names it, with every price it carries.

    A different id universe from TheSportsDB's: nothing here joins on
    `source_id`, and the team names are the board's spellings, untouched.
    """

    event_id: str
    sport_key: str                    # "soccer_brazil_campeonato"
    sport_title: str                  # "Brasileirão Série A"
    commence_time: str                # ISO
    home_team: str
    away_team: str
    market: str = "h2h"
    quotes: list[Quote] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "sport_key": self.sport_key,
            "sport_title": self.sport_title, "commence_time": self.commence_time,
            "home_team": self.home_team, "away_team": self.away_team,
            "market": self.market, "quotes": [q.as_dict() for q in self.quotes],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OddsEvent":
        return cls(
            event_id=raw["event_id"], sport_key=raw["sport_key"],
            sport_title=raw.get("sport_title", ""),
            commence_time=raw.get("commence_time", ""),
            home_team=raw.get("home_team", ""), away_team=raw.get("away_team", ""),
            market=raw.get("market", "h2h"),
            quotes=[Quote.from_dict(q) for q in raw.get("quotes", [])],
        )


@dataclass
class OddsSnapshot:
    """What the market said about one fixture at one instant.

    The unit of persistence. It carries how it was computed -- the de-vig
    method, how many books survived the guards and how many did not -- because
    a probability whose derivation is invisible is the kind of number this
    repo refuses to print.
    """

    at: str                           # our clock, ISO
    event_id: str
    sport_key: str
    commence_time: str
    home_team: str
    away_team: str
    market: str = "h2h"
    method: str = ""                  # "power" | "proportional"
    books: int = 0                    # how many bookmakers survived the guards
    books_dropped: int = 0            # and how many did not
    overround: float = 0.0            # median of the per-book cuts, as a fraction
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at, "event_id": self.event_id, "sport_key": self.sport_key,
            "commence_time": self.commence_time, "home_team": self.home_team,
            "away_team": self.away_team, "market": self.market,
            "method": self.method, "books": self.books,
            "books_dropped": self.books_dropped, "overround": self.overround,
            "outcomes": self.outcomes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OddsSnapshot":
        return cls(
            at=raw["at"], event_id=raw["event_id"], sport_key=raw.get("sport_key", ""),
            commence_time=raw.get("commence_time", ""),
            home_team=raw.get("home_team", ""), away_team=raw.get("away_team", ""),
            market=raw.get("market", "h2h"), method=raw.get("method", ""),
            books=int(raw.get("books", 0)), books_dropped=int(raw.get("books_dropped", 0)),
            overround=float(raw.get("overround", 0.0)),
            outcomes=list(raw.get("outcomes", [])),
        )
