"""Which board entries belong to a followed subject. Pure.

The news filter matches a headline by substring containment and can afford to:
a headline about the wrong club is cheap and visibly wrong. A probability
attached to the wrong club is neither. "Inter" is Internacional in Porto
Alegre and Inter Miami in Florida, and the board prints both.

So nothing is matched at runtime that a person did not confirm. `resolve`
reads only what was stored; `candidates` does the guessing, and only inside
the linking conversation, where a wrong guess is free because someone answers.
"""

from __future__ import annotations

from typing import Any

from fandom.engine.news_filter import normalize
from fandom.models import OddsEvent, Team

EXACT = 3
RUN = 2
FIRST_TOKEN = 1


def owns(team: Team, sport_key: str, home: str, away: str) -> bool:
    """Whether this board fixture is this subject's, by what was stored.

    A league follow (`odds_key` is None) takes every fixture of its sport. A
    club follow takes the fixtures where the board's exact spelling stands on
    one of the two sides -- exact, because a near name is a different club.
    """
    if not team.odds_sport or team.odds_sport != sport_key:
        return False
    if not team.odds_key:
        return True
    return team.odds_key in (home, away)


def resolve(events: list[OddsEvent], team: Team) -> list[OddsEvent]:
    """This subject's events. Decided by what was stored, never by resemblance."""
    return [event for event in events
            if owns(team, event.sport_key, event.home_team, event.away_team)]


def _score(needle: str, board_name: str) -> int:
    """How much one alias looks like one board name, 0 when it does not.

    Substring containment is deliberately absent: it is what makes "inter"
    match "inter miami", and it is the only scoring rule cheap enough to be
    wrong here.
    """
    needle_tokens = normalize(needle).split()
    board_tokens = normalize(board_name).split()
    if not needle_tokens or not board_tokens:
        return 0
    if needle_tokens == board_tokens:
        return EXACT
    size = len(needle_tokens)
    runs = (board_tokens[start:start + size] for start in range(len(board_tokens) - size + 1))
    if any(run == needle_tokens for run in runs):
        return RUN
    if needle_tokens[0] == board_tokens[0]:
        return FIRST_TOKEN
    return 0


def candidates(events: list[OddsEvent], team: Team, *, limit: int = 5) -> list[dict[str, Any]]:
    """Ranked guesses for the linking conversation, best first.

    The near miss is ranked, not hidden: "Inter Miami CF" stays on the list
    under "Internacional", because the point of showing candidates is that a
    person can see the trap and step around it. Nothing here commits anything.
    """
    needles = [team.name, *team.aliases]
    seen: dict[str, dict[str, Any]] = {}
    for event in events:
        if team.odds_sport and event.sport_key != team.odds_sport:
            continue
        for side, opponent in ((event.home_team, event.away_team),
                               (event.away_team, event.home_team)):
            score = max((_score(needle, side) for needle in needles), default=0)
            if not score:
                continue
            entry = seen.setdefault(side, {
                "name": side, "sport_key": event.sport_key,
                "sport_title": event.sport_title, "score": score, "fixtures": 0,
                "next_against": opponent, "commence_time": event.commence_time,
            })
            entry["score"] = max(entry["score"], score)
            entry["fixtures"] += 1
            if event.commence_time and event.commence_time < entry["commence_time"]:
                entry["next_against"] = opponent
                entry["commence_time"] = event.commence_time
    ranked = sorted(seen.values(),
                    key=lambda entry: (-entry["score"], -entry["fixtures"], entry["name"]))
    return ranked[:limit]
