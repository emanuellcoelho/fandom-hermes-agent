"""Prices in, probabilities out. Pure: no IO, no clock, no network.

A decimal price is not a probability. It carries the bookmaker's margin, so
the raw implied numbers of a market sum to more than one -- that surplus is
the house's cut, not anyone's chance. Removing it is this module's job, and
the way it is removed changes the answer in a direction that matters here.

The guards matter more than the method. A book that suspended one side posts
a single price, and normalizing a single price yields 1.0 -- "your team has a
100% chance", the worst sentence this agent could emit.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime
from typing import Any, Sequence

from fandom.models import OddsEvent, OddsSnapshot

DEFAULT_METHOD = "power"
METHODS = ("power", "proportional")

MIN_BOOKS = 3                 # below this the consensus is labelled thin
FIRM_SPREAD = 0.04            # books this far apart are not agreeing
QUOTE_MAX_AGE_MIN = 60        # a book that has not moved in an hour is stale

_K_TOL = 1e-12
_K_CEILING = 1024.0
_OVERROUND_EPS = 1e-9


def implied(price: float) -> float:
    """1/price.

    A decimal price at or below 1.00 pays back no more than the stake and is
    not a price: it is a suspended outcome the feed forgot to drop.
    """
    if price <= 1.0:
        raise ValueError(f"decimal price must exceed 1.0, got {price!r}")
    return 1.0 / price


def overround(prices: Sequence[float]) -> float:
    """Sum(1/price) - 1: the house's cut, as a fraction of the market."""
    return sum(implied(price) for price in prices) - 1.0


def devig_proportional(prices: Sequence[float]) -> list[float]:
    """p_i / Sum(p). Removes the margin without touching its shape."""
    raws = [implied(price) for price in prices]
    total = sum(raws)
    return [raw / total for raw in raws]


def _power_exponent(raws: Sequence[float]) -> float:
    """The k with Sum(p_i ** k) = 1, by bisection.

    Every p_i lies in (0,1), so p_i**k and therefore the sum are strictly
    decreasing in k: the root is unique and bisection cannot land on the wrong
    one. f(1) is the overround, positive by the guard, and f(inf) is 0, so a
    bracket exists. Its upper end is found by doubling rather than fixed,
    because a price of 1.01 gives p = 0.990 and 0.990**64 is still 0.53 -- a
    fixed 64 would fail to bracket exactly the lopsided market this method
    exists for.
    """
    if sum(raws) <= 1.0 + _K_TOL:
        return 1.0
    low, high = 1.0, 2.0
    while sum(raw ** high for raw in raws) > 1.0:
        high *= 2.0
        if high > _K_CEILING:
            return 1.0          # unbracketed: the caller falls back to proportional
    while high - low > _K_TOL:
        mid = (low + high) / 2.0
        if sum(raw ** mid for raw in raws) > 1.0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def devig_power(prices: Sequence[float]) -> list[float]:
    """p_i ** k, normalized.

    k > 1 shrinks the long shots harder than the favourites, which is the
    direction a bookmaker's margin actually runs. On 1.10/8.00 the naive
    division hands the underdog 12.1% where the book's own structure implies
    10.0% -- a fifth too much, on the side of hope, in an agent whose persona
    exists to not do that. On a balanced market the two methods agree to the
    last digit, so nothing is paid for the default.
    """
    raws = [implied(price) for price in prices]
    exponent = _power_exponent(raws)
    if exponent <= 1.0:
        return devig_proportional(prices)
    powered = [raw ** exponent for raw in raws]
    total = sum(powered)
    return [value / total for value in powered]


def devig(prices: Sequence[float], *, method: str = DEFAULT_METHOD) -> list[float]:
    """The market's own probabilities, with the house's cut taken out.

    `power` is the default and `proportional` is kept because the method name
    travels in the snapshot: swapping it later is a line, not a migration.
    Shin is the other standard of the literature and is not implemented --
    that is a choice worth revisiting against real calibration, not a claim
    that power is the last word.
    """
    if method == "proportional":
        return devig_proportional(prices)
    if method == "power":
        return devig_power(prices)
    raise ValueError(f"unknown de-vig method {method!r} -- one of {list(METHODS)}")


def by_book(event: OddsEvent) -> dict[str, dict[str, Any]]:
    """The event's quotes regrouped per bookmaker: prices and their ages."""
    books: dict[str, dict[str, Any]] = {}
    for quote in event.quotes:
        entry = books.setdefault(quote.book, {"prices": {}, "updates": {}})
        entry["prices"][quote.outcome] = float(quote.price)
        entry["updates"][quote.outcome] = quote.last_update
    return books


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def _modal_outcomes(books: dict[str, dict[str, Any]]) -> frozenset[str]:
    """The outcome set most books agree the market has.

    One shop writing "Tie" where the rest write "Draw" is not a disagreement
    about the game; it is a different market, and averaging across the two
    silently invents a fourth outcome nobody priced.
    """
    counts = Counter(frozenset(entry["prices"]) for entry in books.values())
    if not counts:
        return frozenset()
    best = max(counts.items(), key=lambda pair: (pair[1], len(pair[0]), sorted(pair[0])))
    return best[0]


def keep_books(books: dict[str, dict[str, Any]], *, at: str | None = None,
               max_age_min: int = QUOTE_MAX_AGE_MIN
               ) -> tuple[dict[str, dict[str, float]], list[str]]:
    """The books whose market is whole enough to de-vig, and the ones dropped.

    Five conditions, all required:

    1. two prices or more -- a one-sided market is not a market
    2. a real overround -- without a cut there is nothing to remove, and a
       sum at or below 1.0 means the feed is mid-update or mispriced
    3. every price above 1.00
    4. the same outcome names the rest of the board is using
    5. a quote no older than `max_age_min`

    One and two are the important pair. A book that suspended one side posts
    a single price; normalizing it produces 1.0, and certainty is the one
    thing a market never sells.

    A quote with no timestamp, or one this module cannot parse, is kept: the
    board was just read, and dropping every book over a field the provider
    happens to omit would turn an absent field into an absent answer.
    """
    moment = _parse(at)
    wanted = _modal_outcomes(books)
    kept: dict[str, dict[str, float]] = {}
    dropped: list[str] = []
    for book, entry in books.items():
        prices: dict[str, float] = entry["prices"]
        if len(prices) < 2 or frozenset(prices) != wanted:
            dropped.append(book)
            continue
        if any(price <= 1.0 for price in prices.values()):
            dropped.append(book)
            continue
        if overround(list(prices.values())) <= _OVERROUND_EPS:
            dropped.append(book)
            continue
        if moment is not None and _stale(entry.get("updates") or {}, moment, max_age_min):
            dropped.append(book)
            continue
        kept[book] = dict(prices)
    return kept, sorted(dropped)


def _stale(updates: dict[str, str], moment: datetime, max_age_min: int) -> bool:
    ages = [(moment - stamp).total_seconds() / 60.0
            for stamp in (_parse(value) for value in updates.values())
            if stamp is not None]
    return bool(ages) and min(ages) > max_age_min


def consensus(kept: dict[str, dict[str, float]], *,
              method: str = DEFAULT_METHOD) -> tuple[list[dict[str, Any]], float]:
    """One row per outcome, plus the median cut the books were taking.

    Each book is de-vigged inside itself before anything is compared. Taking
    a median of raw prices first would mix margins: every book posts a market
    coherent with its own cut, and the shape of that cut is exactly what is
    being removed.

    Median and not mean: with five to eight books, one shop posting a stale or
    exotic line moves a mean and does not move a median. Dispersion is the
    honest part of the row -- it is what says whether the number has earned a
    decimal place.
    """
    if not kept:
        return [], 0.0
    names = sorted(next(iter(kept.values())))
    probabilities: dict[str, list[float]] = {name: [] for name in names}
    prices: dict[str, list[float]] = {name: [] for name in names}
    cuts: list[float] = []
    for book in sorted(kept):
        offered = kept[book]
        ordered = [offered[name] for name in names]
        cuts.append(overround(ordered))
        for name, clean in zip(names, devig(ordered, method=method)):
            probabilities[name].append(clean)
            prices[name].append(offered[name])

    medians = {name: statistics.median(values) for name, values in probabilities.items()}
    total = sum(medians.values()) or 1.0
    rows: list[dict[str, Any]] = []
    for name in names:
        values = probabilities[name]
        # The medians are taken per outcome, so their sum misses 1.0 by about
        # a thousandth. Renormalizing is what keeps the vector a probability.
        share = medians[name] / total
        rows.append({
            "name": name,
            "p": round(share, 4),
            # Both prices, because they answer different questions. `price` is
            # what the board actually posts, which is the quote. `fair_price`
            # is 1/p, the same bet with the house's cut removed -- a number no
            # shop offers, and labelled so it is never mistaken for one.
            "price": round(statistics.median(prices[name]), 3),
            "fair_price": round(1.0 / share, 3) if share else None,
            "spread": round(max(values) - min(values), 4),
            # MAD, not stdev: with three to eight books a standard deviation is
            # one outlier's opinion and pretends a normal curve nobody checked.
            # No 1.4826 factor either -- this is not a sigma in disguise.
            "mad": round(statistics.median([abs(value - medians[name]) for value in values]), 4),
        })
    rows.sort(key=lambda row: row["p"], reverse=True)
    return rows, round(statistics.median(cuts), 4)


def confidence(row: dict[str, Any], books: int) -> str:
    """thin, split or firm.

    Both conditions, the way source_health.classify takes both. Counting books
    alone calls eight shops copying one feed a consensus; measuring agreement
    alone calls two shops that happen to match a consensus.
    """
    if books < MIN_BOOKS:
        return "thin"
    return "firm" if row.get("spread", 1.0) <= FIRM_SPREAD else "split"


def build_snapshot(event: OddsEvent, *, at: str,
                   method: str = DEFAULT_METHOD) -> OddsSnapshot:
    """What the market said about one fixture at one instant.

    `books_dropped` travels with it: discarding a shop in silence is the same
    fault as three dead feeds behind a comment saying they were alive.
    """
    kept, dropped = keep_books(by_book(event), at=at)
    rows, cut = consensus(kept, method=method)
    for row in rows:
        row["confidence"] = confidence(row, len(kept))
    return OddsSnapshot(
        at=at, event_id=event.event_id, sport_key=event.sport_key,
        commence_time=event.commence_time, home_team=event.home_team,
        away_team=event.away_team, market=event.market,
        method=method if rows else "",
        books=len(kept), books_dropped=len(dropped),
        overround=cut, outcomes=rows,
    )
