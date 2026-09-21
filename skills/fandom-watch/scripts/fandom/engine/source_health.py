"""How each source has been behaving, across runs. Pure.

The payload of a single run cannot tell "ESPN just failed" from "ESPN has been
failing since Tuesday" -- both are one line in `failed_sources`. That gap is
how three dead feeds stayed dead for days. This module keeps the little that
is needed to tell them apart, keyed by URL because feeds are shared between
subjects.

It records and classifies. It never decides to skip a source: a source marked
down that is no longer tried can never be seen to recover.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from kit import clock

CHRONIC_AFTER_FAILURES = 3
CHRONIC_AFTER_HOURS = 24
ANNOUNCE_COOLDOWN_DAYS = 7
KEEP_DAYS = 30


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _hours_since(stamp: str | None, now: datetime) -> float:
    moment = _parse(stamp)
    if moment is None:
        return float("inf")
    return (now - moment).total_seconds() / 3600.0


def record(health: dict[str, Any], outcomes, *, now: datetime | None = None) -> dict[str, Any]:
    """Fold one run's outcomes into the health record. Returns a new dict."""
    moment = now or clock.now()
    stamp = clock.iso(moment)
    sources = dict(health.get("sources") or {})
    for outcome in outcomes:
        entry = dict(sources.get(outcome.url) or {})
        entry.setdefault("first_seen_at", stamp)
        entry["label"] = outcome.label
        if outcome.ok:
            entry["last_ok_at"] = stamp
            entry["consecutive_failures"] = 0
            entry["ok_runs"] = int(entry.get("ok_runs", 0)) + 1
        else:
            entry["last_error_at"] = stamp
            entry["last_error"] = (outcome.error or "")[:200]
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            entry["fail_runs"] = int(entry.get("fail_runs", 0)) + 1
        sources[outcome.url] = entry
    return {"version": 1, "sources": sources}


def classify(entry: dict[str, Any], *, now: datetime | None = None) -> str:
    """ok, flaky, or down.

    Both conditions are needed for `down`. Counting failures alone calls a
    source dead on a day the user asks for news six times; counting elapsed
    time alone calls it dead when it 503'd at 08:29 and answered at 08:31.
    Together they say: it has failed repeatedly AND has not delivered in a day.
    """
    moment = now or clock.now()
    failures = int(entry.get("consecutive_failures", 0))
    if failures == 0:
        return "ok"
    if failures < CHRONIC_AFTER_FAILURES:
        return "flaky"
    since = entry.get("last_ok_at") or entry.get("first_seen_at")
    if _hours_since(since, moment) < CHRONIC_AFTER_HOURS:
        return "flaky"
    return "down"


def _summary(url: str, entry: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "url": url,
        "label": entry.get("label") or url,
        "status": status,
        "reason": entry.get("last_error", ""),
        "consecutive_failures": int(entry.get("consecutive_failures", 0)),
        "last_ok_at": entry.get("last_ok_at"),
    }


def report(health: dict[str, Any], outcomes, *, now: datetime | None = None,
           sports_planned: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """The `sources` block of a payload: counts, what is degraded, what is gone.

    `announce` marks a chronic source the user has not been told about in the
    cooldown window. Saying "espn.com is down" every morning for two weeks
    keeps the letter of the promise and destroys its point -- it becomes
    wallpaper. Saying it when it happens, offering to swap the source, and
    then staying quiet is the same honesty at a volume someone can hear.
    """
    moment = now or clock.now()
    sources = health.get("sources") or {}
    degraded, down = [], []
    for outcome in outcomes:
        if outcome.ok:
            continue
        entry = sources.get(outcome.url) or {}
        status = classify(entry, now=moment)
        summary = _summary(outcome.url, entry, status)
        if status == "down":
            summary["announce"] = _hours_since(entry.get("reported_at"), moment) >= ANNOUNCE_COOLDOWN_DAYS * 24
            down.append(summary)
        else:
            degraded.append(summary)
    block: dict[str, Any] = {
        "attempted": len(outcomes),
        "answered": sum(1 for outcome in outcomes if outcome.ok),
        "degraded": degraded,
        "down": down,
    }
    if sports_planned:
        # Only sports whose URLs were actually attempted can be judged. A sport
        # planned but absent from this run's outcomes is unknown, not a gap.
        attempted = {outcome.url for outcome in outcomes}
        answered = {outcome.url for outcome in outcomes if outcome.ok}
        block["coverage_gap"] = sorted(
            sport for sport, urls in sports_planned.items()
            if (set(urls) & attempted) and not (set(urls) & answered)
        )
    return block


def mark_announced(health: dict[str, Any], urls, *, now: datetime | None = None) -> dict[str, Any]:
    """Remember that these were announced, so tomorrow stays quiet about them."""
    stamp = clock.iso(now or clock.now())
    sources = dict(health.get("sources") or {})
    for url in urls:
        if url in sources:
            entry = dict(sources[url])
            entry["reported_at"] = stamp
            sources[url] = entry
    return {**health, "version": 1, "sources": sources}


def prune(health: dict[str, Any], planned_urls, *, now: datetime | None = None,
          keep_days: int = KEEP_DAYS) -> dict[str, Any]:
    """Drop sources nobody plans to read and nothing has touched in a month."""
    moment = now or clock.now()
    cutoff = moment - timedelta(days=keep_days)
    planned = set(planned_urls)
    kept = {}
    for url, entry in (health.get("sources") or {}).items():
        if url in planned:
            kept[url] = entry
            continue
        touched = _parse(entry.get("last_ok_at")) or _parse(entry.get("last_error_at"))
        if touched is not None and touched >= cutoff:
            kept[url] = entry
    return {"version": 1, "sources": kept}
