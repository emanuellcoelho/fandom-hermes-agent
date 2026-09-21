"""Agent preferences and the BR-first seed. Missing keys mean onboarding is
unfinished; the seed exists so a fresh agent has something to follow."""

from __future__ import annotations

from typing import Any

from kit.jsonio import load_json, save_json_atomic

REQUIRED_KEYS = ("timezone", "digest_time", "language")

DEFAULTS: dict[str, Any] = {
    "timezone": "UTC",
    "digest_time": "08:30",
    "digest_enabled": True,
    "language": "",                   # "" = mirror the user each turn
    "news_limit_per_team": 5,
    "matchday_times": ["12:00", "19:00"],
}

# Feeds per sport, then per language. Every URL here passed
# tests/test_feeds_live.py through kit.http -- the path production uses --
# because the previous list was validated with curl and three ESPN feeds sat
# dead behind a comment claiming they were alive.
#
# Team-specific feeds are mostly dead or bot-walled, so the design is a pure
# alias filter over general feeds plus the subject's Google News query: any
# single feed here can die without breaking the digest.
FEEDS = {
    "futebol": {
        # uol.com.br was a candidate and was cut here: it answers 200 with an
        # <rss> root and malformed XML inside. The live harness caught it.
        "pt": ["https://ge.globo.com/rss/ge/"],
        "en": [
            "https://feeds.bbci.co.uk/sport/football/rss.xml",
            "https://www.theguardian.com/football/rss",
            "https://www.espn.com/espn/rss/soccer/news",
        ],
    },
    "basquete": {
        "pt": ["https://ge.globo.com/rss/ge/"],
        "en": [
            "https://www.espn.com/espn/rss/nba/news",
            "https://feeds.bbci.co.uk/sport/basketball/rss.xml",
        ],
    },
    "futebol_americano": {
        "pt": [],
        "en": [
            "https://www.espn.com/espn/rss/nfl/news",
            "https://www.cbssports.com/rss/headlines/nfl/",
            "https://feeds.bbci.co.uk/sport/american-football/rss.xml",
        ],
    },
    # The BBC's general sport feed used to stand here and never carried a line
    # of esports, which left two of the four seeded subjects living entirely
    # off the Google News query.
    "esports": {
        "pt": [],
        "en": [
            "https://www.hltv.org/rss/news",
            "https://dotesports.com/feed",
        ],
    },
}


def feeds_for(sport: str, language: str = "") -> list[str]:
    """This sport's feeds for this user: their language first, English as floor.

    A Brazilian wants the ge AND the Champions League off the BBC, so pt-BR
    gets both with pt first. Someone in Chicago has no use for ge.globo, so a
    non-pt language gets English only. An empty language means onboarding has
    not asked yet, and the seed is Brazilian, so it keeps the pt+en reach.
    """
    buckets = FEEDS.get(str(sport), {})
    lang = (language or "").strip().lower()[:2]
    wanted = [lang, "en"] if lang else ["pt", "en"]
    urls: list[str] = []
    for key in wanted:
        for url in buckets.get(key, []):
            if url not in urls:
                urls.append(url)
    return urls


# The demo seed: Brasileirão, CBLOL, NBA. Onboarding replaces or extends it.
SEED_TEAMS: list[dict[str, Any]] = [
    {
        "key": "brasileirao", "name": "Brasileirão Série A", "sport": "futebol",
        "aliases": ["brasileirão", "brasileirao", "série a", "serie a",
                    "flamengo", "palmeiras", "corinthians", "são paulo", "sao paulo",
                    "grêmio", "gremio", "internacional", "cruzeiro", "atlético-mg",
                    "atletico-mg", "fluminense", "botafogo", "vasco", "santos", "bahia", "fortaleza"],
        "league": "Brasileirão Série A",
    },
    {
        "key": "cblol", "name": "CBLOL", "sport": "esports",
        "aliases": ["cblol", "cboll", "league of legends brasileiro", "lol brasileiro"],
        "league": "CBLOL",
    },
    {
        "key": "cs2", "name": "CS2", "sport": "esports",
        "aliases": ["cs2", "counter-strike", "counter strike", "csgo",
                    "counter-strike 2", "furia", "mibr", "loud cs2"],
        "league": "Counter-Strike 2",
    },
    {
        "key": "nba", "name": "NBA", "sport": "basquete",
        "aliases": ["nba", "basquete", "lakers", "celtics", "warriors", "bucks"],
        "league": "NBA",
    },
]


def config_path(home: str) -> str:
    return f"{home}/config.json"


def load(home: str) -> dict[str, Any]:
    stored = load_json(config_path(home), {}) or {}
    return {**DEFAULTS, **stored}


def save(home: str, config: dict[str, Any]) -> None:
    save_json_atomic(config_path(home), config)


def missing_keys(home: str) -> list[str]:
    """Keys onboarding has not asked about yet -- judged on the FILE, never on
    the defaults: a default is what the agent runs on, not what the user chose."""
    stored = load_json(config_path(home), {}) or {}
    return [key for key in REQUIRED_KEYS if key not in stored]
