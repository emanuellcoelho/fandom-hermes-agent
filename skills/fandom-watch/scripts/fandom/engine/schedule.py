"""The cron specs to register, in the zone the container actually runs in. Pure.

`hermes cron create` takes no per-job zone: every schedule fires in the
container's TZ, and that TZ is written once, at boot, from the config. So a
user who picks their timezone during onboarding -- which is always, since
onboarding is what writes it -- leaves the container running in the zone it
booted with, usually UTC.

The old instruction was to wait for a restart before registering anything.
Nobody restarts a cloud agent, so the wait never ends: the fandom agent ran
five days in production with no schedule at all, and its whole product is a
message that arrives in the morning.

Converting is what breaks the deadlock. 08:30 in Sao Paulo is 11:30 UTC, and
a job registered at 11:30 in a UTC container lands at 08:30 for the reader --
the same instant, named in the zone that will actually be used. When the two
zones already agree, nothing is converted and nothing can drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DIGEST_NAME = "fandom-digest"
MATCHDAY_NAME = "fandom-matchday"


def zone_of(name: str | None) -> ZoneInfo | None:
    """The zone by name, or None when nothing can resolve it."""
    if not name:
        return None
    try:
        return ZoneInfo(str(name).strip())
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def _hhmm(raw: str) -> tuple[int, int] | None:
    hour, _, minute = str(raw).strip().partition(":")
    try:
        hours, minutes = int(hour), int(minute or 0)
    except ValueError:
        return None
    return (hours, minutes) if 0 <= hours < 24 and 0 <= minutes < 60 else None


def convert(times: list[str], *, user_zone: ZoneInfo, container_zone: ZoneInfo,
            now: datetime | None = None) -> list[tuple[int, int]]:
    """Local wall-clock times, restated in the container's zone.

    Crossing midnight needs no special case: a daily job is `* * *`, so an
    hour that wraps past 23 simply fires on the other side of the date line
    and still marks the same instant for the reader.
    """
    reference = (now or datetime.now(user_zone)).astimezone(user_zone)
    moved: list[tuple[int, int]] = []
    for raw in times:
        parsed = _hhmm(raw)
        if parsed is None:
            continue
        local = reference.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)
        there = local.astimezone(container_zone)
        moved.append((there.hour, there.minute))
    return moved


def cron_of(moments: list[tuple[int, int]]) -> str:
    """One daily spec for however many times of day share a minute."""
    if not moments:
        return ""
    minutes = sorted({minute for _hour, minute in moments})
    hours = sorted({hour for hour, _minute in moments})
    if len(minutes) == 1:
        return f"{minutes[0]} {','.join(str(hour) for hour in hours)} * * *"
    # Different minutes cannot share one spec; the caller registers one job
    # per moment rather than rounding somebody's schedule for tidiness.
    return ""


def observes_dst(zone: ZoneInfo, *, now: datetime | None = None) -> bool:
    """Whether this zone's offset changes during the year.

    It decides whether a converted schedule can drift: a zone that never
    shifts (Brazil since 2019) is safe forever, and one that does is safe only
    until its next transition, when the container's own zone would have
    followed along and a fixed conversion does not.
    """
    moment = now or datetime.now(zone)
    offsets = {
        (moment.replace(month=month, day=1, hour=12, minute=0, second=0,
                        microsecond=0, tzinfo=zone)).utcoffset()
        for month in range(1, 13)
    }
    return len(offsets) > 1


def plan(settings: dict[str, Any], *, container_tz: str | None,
         now: datetime | None = None) -> dict[str, Any]:
    """Every schedule this agent should have, ready to register.

    `aligned` says the container already runs in the user's zone, which is the
    ideal and needs no conversion. `drifts_after_dst` is the honest warning on
    the converted case: it is true only when the zone actually shifts, and the
    cure is a restart, which realigns the container and retires the conversion.
    """
    user_zone = zone_of(settings.get("timezone"))
    container_zone = zone_of(container_tz) or ZoneInfo("UTC")
    known = user_zone is not None
    if user_zone is None:
        user_zone = container_zone
    aligned = str(getattr(user_zone, "key", "")) == str(getattr(container_zone, "key", ""))

    digest_times = [str(item) for item in (settings.get("digest_times") or [])]
    matchday_times = [str(item) for item in (settings.get("matchday_times") or [])]

    def spec(times: list[str]) -> dict[str, Any]:
        moved = convert(times, user_zone=user_zone, container_zone=container_zone, now=now)
        return {
            "local": list(times),
            "fires": [f"{hour:02d}:{minute:02d}" for hour, minute in moved],
            "cron": cron_of(moved),
        }

    return {
        "timezone": str(getattr(user_zone, "key", "UTC")),
        "timezone_known": known,
        "container_tz": str(getattr(container_zone, "key", "UTC")),
        "aligned": aligned,
        "drifts_after_dst": (not aligned) and observes_dst(user_zone, now=now),
        "digest": {"name": DIGEST_NAME,
                   "enabled": bool(settings.get("digest_enabled", True)),
                   **spec(digest_times)},
        "matchday": {"name": MATCHDAY_NAME, "enabled": True, **spec(matchday_times)},
    }
