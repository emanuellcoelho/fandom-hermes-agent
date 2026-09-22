"""The schedules, computed instead of postponed.

The bug these exist for: the agent ran five days in production with no cron at
all, because the instruction was to wait for a restart that realigns the
container's zone, and nobody restarts a cloud agent.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fandom.engine import schedule

SP = ZoneInfo("America/Sao_Paulo")
JUNE = datetime(2026, 6, 15, 12, 0, tzinfo=SP)
JANUARY = datetime(2026, 1, 15, 12, 0, tzinfo=SP)


def settings(**kwargs):
    base = {"timezone": "America/Sao_Paulo", "digest_times": ["08:00", "12:00", "18:00"],
            "digest_enabled": True, "matchday_times": ["12:00", "19:00"]}
    return {**base, **kwargs}


class TestConversion:
    def test_a_utc_container_gets_the_sao_paulo_hour_restated(self):
        """08:00/12:00/18:00 in Sao Paulo is 11:00/15:00/21:00 UTC, and a job
        at those hours in a UTC container lands at the reader's local hours --
        the same instants."""
        plan = schedule.plan(settings(), container_tz="UTC", now=JUNE)
        assert plan["digest"]["cron"] == "0 11,15,21 * * *"
        assert plan["digest"]["fires"] == ["11:00", "15:00", "21:00"]
        assert plan["matchday"]["cron"] == "0 15,22 * * *"
        assert plan["aligned"] is False

    def test_an_aligned_container_converts_nothing(self):
        """The ideal case, and the one a restart produces: no arithmetic at all."""
        plan = schedule.plan(settings(), container_tz="America/Sao_Paulo", now=JUNE)
        assert plan["aligned"] is True
        assert plan["digest"]["cron"] == "0 8,12,18 * * *"
        assert plan["matchday"]["cron"] == "0 12,19 * * *"

    def test_a_late_hour_wraps_past_midnight_without_a_special_case(self):
        """22:00 in Sao Paulo is 01:00 UTC the next day, and a daily job is
        `* * *`, so the wrap marks the same instant."""
        plan = schedule.plan(settings(digest_times=["22:00"]), container_tz="UTC", now=JUNE)
        assert plan["digest"]["cron"] == "0 1 * * *"

    def test_a_missing_container_zone_is_utc_explicitly(self):
        plan = schedule.plan(settings(), container_tz=None, now=JUNE)
        assert plan["container_tz"] == "UTC" and plan["digest"]["cron"] == "0 11,15,21 * * *"

    def test_a_zone_nothing_can_resolve_falls_back_and_says_so(self):
        """Never a crash over a value the agent itself wrote, and never a
        silent pretence that the zone was understood."""
        plan = schedule.plan(settings(timezone="Mars/Olympus"), container_tz="UTC", now=JUNE)
        assert plan["timezone_known"] is False
        assert plan["timezone"] == "UTC" and plan["aligned"] is True

    def test_a_malformed_time_is_dropped_not_guessed(self):
        plan = schedule.plan(settings(digest_times=["quando der"]), container_tz="UTC", now=JUNE)
        assert plan["digest"]["cron"] == "" and plan["digest"]["fires"] == []


class TestDrift:
    def test_brazil_never_drifts(self):
        """No DST since 2019, so a conversion made today holds all year."""
        plan = schedule.plan(settings(), container_tz="UTC", now=JUNE)
        assert plan["drifts_after_dst"] is False

    def test_a_dst_zone_is_flagged_when_converted(self):
        """London is UTC in January and UTC+1 in June: a fixed conversion is
        right for half the year, and the caller has to know that."""
        london = settings(timezone="Europe/London")
        plan = schedule.plan(london, container_tz="UTC",
                             now=datetime(2026, 6, 15, 12, tzinfo=ZoneInfo("Europe/London")))
        assert plan["drifts_after_dst"] is True
        assert plan["digest"]["cron"] == "0 7,11,17 * * *"      # BST in June

    def test_the_same_dst_zone_converts_differently_in_winter(self):
        london = settings(timezone="Europe/London")
        plan = schedule.plan(london, container_tz="UTC",
                             now=datetime(2026, 1, 15, 12, tzinfo=ZoneInfo("Europe/London")))
        assert plan["digest"]["cron"] == "0 8,12,18 * * *"      # GMT in January

    def test_an_aligned_dst_zone_is_not_flagged(self):
        """Alignment is the cure: the container follows the transition too."""
        plan = schedule.plan(settings(timezone="Europe/London"),
                             container_tz="Europe/London", now=JANUARY)
        assert plan["drifts_after_dst"] is False


class TestShape:
    def test_the_names_match_what_the_skill_registers(self):
        plan = schedule.plan(settings(), container_tz="UTC", now=JUNE)
        assert plan["digest"]["name"] == "fandom-digest"
        assert plan["matchday"]["name"] == "fandom-matchday"

    def test_a_declined_digest_is_carried_not_dropped(self):
        """The spec is still computed: the user may turn it back on, and the
        skill decides, not this."""
        plan = schedule.plan(settings(digest_enabled=False), container_tz="UTC", now=JUNE)
        assert plan["digest"]["enabled"] is False and plan["digest"]["cron"]

    def test_times_that_do_not_share_a_minute_get_no_single_spec(self):
        """Rounding somebody's schedule for the tidiness of one cron line is
        not this module's call to make."""
        plan = schedule.plan(settings(matchday_times=["12:00", "19:30"]),
                             container_tz="UTC", now=JUNE)
        assert plan["matchday"]["cron"] == ""
        assert plan["matchday"]["fires"] == ["15:00", "22:30"]

    def test_the_payload_carries_no_human_words(self):
        """Every value is a token, a time or a flag; the sentence is the
        SKILL.md's."""
        plan = schedule.plan(settings(), container_tz="UTC", now=JUNE)
        for value in (plan["timezone"], plan["container_tz"], plan["digest"]["cron"]):
            assert " " not in value.strip() or value.count(" ") == 4   # a cron spec
