"""The odds file as a value: snapshots kept, credits counted. Pure.

Nothing here opens a file. `FandomStore` owns the bytes, the way it owns the
health file, and this module owns the shape and the arithmetic -- the same
split `source_health` uses, for the same reason: a decision that depends on a
clock and a disk is a decision no test can pin down.

The snapshots and the ledger live in one file on purpose. Two files means a
process that dies between the writes either paid and lost the data or kept
data it never paid for.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fandom.engine import odds_match
from fandom.models import OddsSnapshot, Team

VERSION = 1

# The free tier is 500 credits a month and one h2h/eu call reads a whole
# league, so 8 a day is 248 in a 31-day month: under half, leaving the rest
# for someone asking in the middle of the afternoon.
DAILY_BUDGET = 8
MONTHLY_LIMIT = 500
MONTHLY_RESERVE = 50           # never spend the last fifty
WINDOW_DAYS = 30
CHARGES_KEEP_DAYS = 31         # one day more than the window, so the edge
                               # never eats the number it is counting

KEEP_AFTER_KICKOFF_H = 48
MAX_SNAPSHOTS_PER_EVENT = 12
MAX_EVENTS = 60

DIGEST_HORIZON_H = 36
DIGEST_MAX_AGE_MIN = 240       # four hours: older than that, the morning stays quiet


def empty() -> dict[str, Any]:
    return {"version": VERSION, "snapshots": [],
            "budget": {"charges": [], "last_remaining": None, "last_seen_at": None}}


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def age_minutes(stamp: str | None, now: datetime) -> int | None:
    """How old a reading is, in whole minutes. None when it has no age.

    Every number this layer serves carries one: a probability without its age
    is how a cache lies while telling the truth about the past.
    """
    moment = _parse(stamp)
    if moment is None:
        return None
    return max(0, int((now - moment).total_seconds() // 60))


def append(data: dict[str, Any], snapshots: list[OddsSnapshot]) -> dict[str, Any]:
    """Fold new readings in. Returns a new dict; the caller writes it."""
    kept = list(data.get("snapshots") or [])
    kept.extend(snapshot.as_dict() for snapshot in snapshots)
    return {**data, "version": VERSION, "snapshots": kept}


def latest_for(data: dict[str, Any], event_id: str) -> OddsSnapshot | None:
    """The most recent reading of one fixture, or None."""
    rows = [row for row in (data.get("snapshots") or []) if row.get("event_id") == event_id]
    if not rows:
        return None
    return OddsSnapshot.from_dict(max(rows, key=lambda row: row.get("at", "")))


def prune(data: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Drop what no sentence will ever need again.

    Per fixture: the oldest reading and the most recent eleven. The opening
    line is the anchor of any movement sentence and the one reading that
    cannot be re-bought at a sane price -- the historical endpoint costs ten
    credits a call, which is the whole reason this file exists. The middle is
    what downsamples without losing the story.

    Fixtures kicked off more than two days ago leave whole, and then the file
    is capped at sixty by nearness of kickoff.
    """
    cutoff = now - timedelta(hours=KEEP_AFTER_KICKOFF_H)
    per_event: dict[str, list[dict[str, Any]]] = {}
    for row in data.get("snapshots") or []:
        started = _parse(row.get("commence_time"))
        if started is not None and started < cutoff:
            continue
        per_event.setdefault(str(row.get("event_id")), []).append(row)

    def kickoff(rows: list[dict[str, Any]]) -> str:
        return rows[0].get("commence_time") or "9999"

    ordered = sorted(per_event.items(), key=lambda pair: kickoff(pair[1]))[:MAX_EVENTS]
    kept: list[dict[str, Any]] = []
    for _event_id, rows in ordered:
        rows.sort(key=lambda row: row.get("at", ""))
        if len(rows) > MAX_SNAPSHOTS_PER_EVENT:
            rows = [rows[0]] + rows[-(MAX_SNAPSHOTS_PER_EVENT - 1):]
        kept.extend(rows)
    kept.sort(key=lambda row: (row.get("commence_time") or "", row.get("at") or ""))

    budget = dict(data.get("budget") or {})
    charge_cutoff = now - timedelta(days=CHARGES_KEEP_DAYS)
    budget["charges"] = [
        charge for charge in (budget.get("charges") or [])
        if (_parse(charge.get("at")) or now) >= charge_cutoff
    ]
    return {"version": VERSION, "snapshots": kept, "budget": budget}


def spent(data: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """What the ledger says has been spent, in both windows the gate uses.

    Thirty rolling days, not the calendar month: the free tier resets on the
    subscription anniversary, and a counter keyed by "2026-09" spends twice
    the limit every time the two disagree.
    """
    budget = data.get("budget") or {}
    charges = budget.get("charges") or []
    month_cutoff = now - timedelta(days=WINDOW_DAYS)
    day_cutoff = now - timedelta(hours=24)
    in_window = [c for c in charges if (_parse(c.get("at")) or now) >= month_cutoff]
    today = [c for c in in_window if (_parse(c.get("at")) or now) >= day_cutoff]
    return {
        "spent_30d": sum(int(c.get("cost", 0)) for c in in_window),
        "daily_spent": sum(int(c.get("cost", 0)) for c in today),
        "daily_budget": DAILY_BUDGET,
        "remaining": budget.get("last_remaining"),
        "remaining_seen_at": budget.get("last_seen_at"),
    }


def may_spend(data: dict[str, Any], cost: int, *, now: datetime) -> tuple[bool, str]:
    """Whether this call is affordable, and the machine word for why not.

    Three conditions, for the reason `source_health.classify` takes two: our
    own count cannot see a credit another client of the same key just spent,
    and the provider's header is a fact about the past that says nothing about
    how much of today is already gone. The reasons are tokens; the sentence
    lives in the SKILL.md.
    """
    ledger = spent(data, now=now)
    remaining = ledger["remaining"]
    if remaining is not None and int(remaining) < cost:
        return False, "quota"
    if ledger["daily_spent"] + cost > DAILY_BUDGET:
        return False, "daily_budget"
    if ledger["spent_30d"] + cost > MONTHLY_LIMIT - MONTHLY_RESERVE:
        return False, "monthly_reserve"
    return True, "ok"


def charge(data: dict[str, Any], *, at: str, cost: int, sport_key: str,
           remaining: int | None = None) -> dict[str, Any]:
    """Write one call into the ledger.

    `cost` should be what the provider's header charged, never the pre-flight
    estimate: the estimate is markets times regions and stops being true the
    day the provider reprices. The estimate is for the gate; the header is
    the receipt.
    """
    budget = dict(data.get("budget") or {})
    charges = list(budget.get("charges") or [])
    charges.append({"at": at, "cost": int(cost), "sport_key": sport_key})
    budget["charges"] = charges
    if remaining is not None:
        budget["last_remaining"] = int(remaining)
        budget["last_seen_at"] = at
    return {**data, "version": VERSION, "budget": budget}


def as_row(snapshot: OddsSnapshot, *, now: datetime,
           stale_after_min: int = DIGEST_MAX_AGE_MIN) -> dict[str, Any]:
    """One reading, shaped for a payload, with its age attached."""
    age = age_minutes(snapshot.at, now)
    return {
        "event_id": snapshot.event_id, "sport_key": snapshot.sport_key,
        "home_team": snapshot.home_team, "away_team": snapshot.away_team,
        "commence_time": snapshot.commence_time, "market": snapshot.market,
        "captured_at": snapshot.at, "age_minutes": age,
        "stale": age is None or age > stale_after_min,
        "method": snapshot.method, "books": snapshot.books,
        "books_dropped": snapshot.books_dropped, "overround": snapshot.overround,
        "outcomes": snapshot.outcomes,
    }


def upcoming(data: dict[str, Any], teams: list[Team], *, now: datetime,
             horizon_h: int = DIGEST_HORIZON_H,
             max_age_min: int = DIGEST_MAX_AGE_MIN,
             include_stale: bool = False) -> dict[str, Any]:
    """The cached lines for the followed set. Spends nothing.

    Three leagues read every day at 08:30 is ninety credits a month for a
    block most mornings have no game to fill, so the digest reads what the
    matchday runs already paid for.

    `include_stale` is the difference between being asked and volunteering.
    Someone who asked for the odds is owed the old reading with its age on it;
    the morning message, which nobody asked for, stays quiet rather than
    opening with the day before yesterday.
    """
    horizon = now + timedelta(hours=horizon_h)
    rows: list[dict[str, Any]] = []
    for event_id in {str(row.get("event_id")) for row in (data.get("snapshots") or [])}:
        snapshot = latest_for(data, event_id)
        if snapshot is None or not snapshot.outcomes:
            continue
        starts = _parse(snapshot.commence_time)
        if starts is None or not (now <= starts <= horizon):
            continue
        owner = next((team for team in teams
                      if odds_match.owns(team, snapshot.sport_key,
                                         snapshot.home_team, snapshot.away_team)), None)
        if owner is None:
            continue
        row = as_row(snapshot, now=now, stale_after_min=max_age_min)
        if row["stale"] and not include_stale:
            continue
        row["team"] = owner.key
        rows.append(row)
    rows.sort(key=lambda row: row["commence_time"])
    return {"horizon_h": horizon_h, "events": rows}
