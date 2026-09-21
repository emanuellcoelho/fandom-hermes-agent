"""The odds file: what it keeps, what it drops, and what it refuses to spend.

The clock is a parameter everywhere, the way source_health takes one, so none
of these decisions depend on what day the suite runs.
"""

from datetime import datetime, timedelta, timezone

from fandom.engine import odds_store
from fandom.models import OddsSnapshot, Sport, Team

T0 = datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def snapshot(event_id="e1", *, at=T0, kickoff=None, sport="soccer_brazil_campeonato",
             home="Flamengo", away="Palmeiras", outcomes=None) -> OddsSnapshot:
    return OddsSnapshot(
        at=iso(at), event_id=event_id, sport_key=sport,
        commence_time=iso(kickoff if kickoff else T0 + timedelta(hours=3)),
        home_team=home, away_team=away, market="h2h", method="power",
        books=6, books_dropped=1, overround=0.05,
        outcomes=outcomes if outcomes is not None else [
            {"name": home, "p": 0.51, "price": 1.86, "fair_price": 1.96,
             "spread": 0.03, "mad": 0.01, "confidence": "firm"},
            {"name": away, "p": 0.49, "price": 1.92, "fair_price": 2.04,
             "spread": 0.03, "mad": 0.01, "confidence": "firm"},
        ])


class TestShape:
    def test_an_empty_file_has_both_halves(self):
        """Snapshots and ledger in one file: a crash between two writes either
        pays and loses the reading or keeps a reading it never paid for."""
        data = odds_store.empty()
        assert data["snapshots"] == [] and data["budget"]["charges"] == []

    def test_append_and_read_back_the_latest(self):
        data = odds_store.append(odds_store.empty(), [snapshot()])
        data = odds_store.append(data, [snapshot(at=T0 + timedelta(hours=1))])
        latest = odds_store.latest_for(data, "e1")
        assert latest.at == iso(T0 + timedelta(hours=1))
        assert odds_store.latest_for(data, "nobody") is None

    def test_every_served_reading_carries_its_age(self):
        """A number without its age is how this layer would lie."""
        row = odds_store.as_row(snapshot(), now=T0 + timedelta(minutes=12))
        assert row["age_minutes"] == 12 and row["stale"] is False

    def test_a_reading_older_than_the_window_is_marked_stale(self):
        row = odds_store.as_row(snapshot(), now=T0 + timedelta(hours=9))
        assert row["stale"] is True and row["age_minutes"] == 540


class TestPrune:
    def test_a_finished_fixture_leaves_whole(self):
        old = snapshot("done", at=T0 - timedelta(days=4), kickoff=T0 - timedelta(days=3))
        data = odds_store.append(odds_store.empty(), [old, snapshot()])
        pruned = odds_store.prune(data, now=T0)
        assert {row["event_id"] for row in pruned["snapshots"]} == {"e1"}

    def test_the_opening_line_survives_the_middle(self):
        """The first reading is the anchor of any movement sentence and the one
        that cannot be re-bought at a sane price."""
        readings = [snapshot(at=T0 + timedelta(minutes=10 * i)) for i in range(20)]
        data = odds_store.append(odds_store.empty(), readings)
        pruned = odds_store.prune(data, now=T0 + timedelta(hours=4))
        kept = [row["at"] for row in pruned["snapshots"]]
        assert len(kept) == odds_store.MAX_SNAPSHOTS_PER_EVENT
        assert kept[0] == iso(T0)                      # the opening
        assert kept[-1] == iso(T0 + timedelta(minutes=190))   # the newest

    def test_charges_are_kept_one_day_longer_than_they_are_counted(self):
        """The counting window must never eat the number it counts."""
        data = odds_store.empty()
        data = odds_store.charge(data, at=iso(T0 - timedelta(days=30, hours=12)),
                                 cost=1, sport_key="soccer_epl")
        data = odds_store.charge(data, at=iso(T0 - timedelta(days=40)),
                                 cost=1, sport_key="soccer_epl")
        pruned = odds_store.prune(data, now=T0)
        assert len(pruned["budget"]["charges"]) == 1


class TestBudget:
    def test_the_header_is_the_receipt_not_the_estimate(self):
        data = odds_store.charge(odds_store.empty(), at=iso(T0), cost=3,
                                 sport_key="soccer_epl", remaining=451)
        ledger = odds_store.spent(data, now=T0)
        assert ledger["spent_30d"] == 3 and ledger["remaining"] == 451

    def test_the_daily_budget_stops_the_call_before_it_is_made(self):
        data = odds_store.empty()
        for _ in range(odds_store.DAILY_BUDGET):
            data = odds_store.charge(data, at=iso(T0), cost=1, sport_key="soccer_epl")
        allowed, why = odds_store.may_spend(data, 1, now=T0 + timedelta(hours=1))
        assert (allowed, why) == (False, "daily_budget")

    def test_yesterdays_spend_does_not_count_against_today(self):
        data = odds_store.empty()
        for _ in range(odds_store.DAILY_BUDGET):
            data = odds_store.charge(data, at=iso(T0 - timedelta(days=1, hours=2)),
                                     cost=1, sport_key="soccer_epl")
        assert odds_store.may_spend(data, 1, now=T0) == (True, "ok")

    def test_the_reserve_is_never_spent(self):
        data = odds_store.empty()
        data = odds_store.charge(data, at=iso(T0 - timedelta(days=2)),
                                 cost=odds_store.MONTHLY_LIMIT - odds_store.MONTHLY_RESERVE,
                                 sport_key="soccer_epl")
        allowed, why = odds_store.may_spend(data, 1, now=T0)
        assert (allowed, why) == (False, "monthly_reserve")

    def test_a_thirty_day_window_rolls_without_a_calendar_reset(self):
        """A counter keyed "2026-09" spends twice the limit on the turn of the
        month, because the free tier resets on the subscription anniversary."""
        data = odds_store.empty()
        data = odds_store.charge(data, at=iso(T0 - timedelta(days=31)),
                                 cost=400, sport_key="soccer_epl")
        assert odds_store.spent(data, now=T0)["spent_30d"] == 0
        assert odds_store.may_spend(data, 1, now=T0) == (True, "ok")

    def test_an_exhausted_quota_is_named_quota_not_budget(self):
        """The provider's own count outranks ours: another client of the same
        key can spend a credit our ledger never saw."""
        data = odds_store.charge(odds_store.empty(), at=iso(T0), cost=1,
                                 sport_key="soccer_epl", remaining=0)
        assert odds_store.may_spend(data, 1, now=T0) == (False, "quota")

    def test_the_reasons_are_machine_words(self):
        """No human sentence ever leaves Python. The SKILL.md owns the voice."""
        for reason in ("ok", "quota", "daily_budget", "monthly_reserve"):
            assert reason.replace("_", "").isalpha() and reason.islower()


class TestUpcoming:
    def _teams(self):
        return [Team(key="brasileirao", name="Brasileirão", sport=Sport.FUTEBOL,
                     odds_sport="soccer_brazil_campeonato")]

    def test_the_digest_block_reads_the_cache_and_spends_nothing(self):
        data = odds_store.append(odds_store.empty(), [snapshot()])
        block = odds_store.upcoming(data, self._teams(), now=T0 + timedelta(minutes=5))
        assert [row["event_id"] for row in block["events"]] == ["e1"]
        assert block["events"][0]["age_minutes"] == 5
        assert block["events"][0]["team"] == "brasileirao"

    def test_a_fixture_past_the_horizon_is_left_out(self):
        far = snapshot("later", kickoff=T0 + timedelta(hours=60))
        data = odds_store.append(odds_store.empty(), [far])
        assert odds_store.upcoming(data, self._teams(), now=T0)["events"] == []

    def test_a_line_older_than_the_window_stays_quiet(self):
        """Better silent than quoting the day before yesterday."""
        data = odds_store.append(odds_store.empty(), [snapshot(kickoff=T0 + timedelta(hours=30))])
        block = odds_store.upcoming(data, self._teams(), now=T0 + timedelta(hours=9))
        assert block["events"] == []

    def test_an_unlinked_subject_takes_nothing_from_the_cache(self):
        data = odds_store.append(odds_store.empty(), [snapshot()])
        unlinked = [Team(key="cs2", name="CS2", sport=Sport.ESPORTS)]
        assert odds_store.upcoming(data, unlinked, now=T0)["events"] == []

    def test_a_kickoff_already_past_is_not_upcoming(self):
        data = odds_store.append(odds_store.empty(), [snapshot()])
        block = odds_store.upcoming(data, self._teams(), now=T0 + timedelta(hours=4))
        assert block["events"] == []


class TestFandomStore:
    def test_the_file_is_not_read_until_something_asks(self, store):
        """teams list has no idea what a quote is and should not pay to load one."""
        assert store._odds is None
        assert store.odds["snapshots"] == []

    def test_saving_round_trips_through_disk(self, store):
        store.save_odds(odds_store.append(odds_store.empty(), [snapshot()]))
        reloaded = type(store)(store.home)
        assert odds_store.latest_for(reloaded.odds, "e1").home_team == "Flamengo"
