"""The odds board, fetched the way production fetches it.

Same reason `test_feeds_live.py` exists: a provider answer validated against
documentation is not validated. Three feeds in this repo were "proved alive"
with curl and had been dead for days through `kit.http`. The claims this
suite makes about the board -- that its prices are decimals above evens, that
it stamps its quotes, that it reports the quota in a header the budget then
trusts -- are claims about a live service, and only this file tests them.

Off by default: it touches the network, and the odds call spends a credit.

    ODDS_API_KEY=... FANDOM_LIVE_ODDS=1 python -m pytest tests/test_odds_live.py -q

Set FANDOM_LIVE_ODDS_SPEND=1 as well to allow the one paid call.
"""

import os

import pytest

from fandom.engine import odds as odds_engine
from fandom.sources import odds

pytestmark = pytest.mark.skipif(
    not os.environ.get("FANDOM_LIVE_ODDS"),
    reason="network test; set FANDOM_LIVE_ODDS=1 (and a key or an edge) to run",
)

LEAGUE = os.environ.get("FANDOM_LIVE_ODDS_LEAGUE", "soccer_brazil_campeonato")


def test_the_sports_list_answers_and_carries_our_league():
    sports, answer = odds.list_sports()
    assert answer.status == 200 and sports
    keys = {sport["sport_key"] for sport in sports}
    assert LEAGUE in keys, f"{LEAGUE} is not a key this board knows"


def test_the_free_endpoints_cost_nothing():
    """The linking conversation runs on these; onboarding must not be the
    expensive part."""
    _sports, answer = odds.list_sports()
    assert answer.cost in (None, 0), f"/v4/sports charged {answer.cost}"


def test_events_come_back_with_both_sides_named():
    events, answer = odds.list_events(LEAGUE)
    assert answer.status == 200
    if not events:
        pytest.skip(f"{LEAGUE} has no scheduled fixture right now")
    assert all(event.home_team and event.away_team for event in events)
    assert all(event.event_id for event in events)


@pytest.mark.skipif(not os.environ.get("FANDOM_LIVE_ODDS_SPEND"),
                    reason="this call spends a credit; set FANDOM_LIVE_ODDS_SPEND=1")
def test_the_board_prices_survive_the_engines_guards():
    """The one paid call, and the only proof that the whole path holds."""
    events, answer = odds.fetch_odds(LEAGUE)
    assert answer.status == 200
    if not events:
        pytest.skip(f"{LEAGUE} has no priced fixture right now")

    # The budget rests on this header being there. If it is not, the ledger is
    # counting its own guesses.
    assert answer.remaining is not None, "the board reported no x-requests-remaining"
    assert answer.cost is not None, "the board reported no x-requests-last"

    priced = [event for event in events if event.quotes]
    assert priced, "every fixture came back without a single quote"
    event = priced[0]
    assert all(quote.price > 1.0 for quote in event.quotes), "a price at or below evens"
    assert all(quote.last_update for quote in event.quotes), \
        "quotes arrive undated -- the staleness guard is doing nothing"

    snapshot = odds_engine.build_snapshot(event, at=_now())
    assert snapshot.books >= 1, f"every book was dropped: {snapshot.books_dropped} of them"
    assert sum(row["p"] for row in snapshot.outcomes) == pytest.approx(1.0, abs=1e-3)
    assert all(0.0 < row["p"] < 1.0 for row in snapshot.outcomes), \
        "a probability of 1.0 means a guard let a one-sided market through"


def _now() -> str:
    from kit import clock
    return clock.iso()
