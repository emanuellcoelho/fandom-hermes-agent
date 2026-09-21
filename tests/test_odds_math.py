"""The odds engine's arithmetic, pure: no fixtures, no network, no clock.

These are the tests that decide whether a number this agent says is true.
"""

import pytest

from fandom.engine import odds
from fandom.models import OddsEvent, Quote


def event(*quotes: Quote, commence="2026-09-21T22:00:00+00:00") -> OddsEvent:
    return OddsEvent(event_id="e1", sport_key="soccer_brazil_campeonato",
                     sport_title="Brasileirão", commence_time=commence,
                     home_team="Flamengo", away_team="Palmeiras",
                     quotes=list(quotes))


def book(name: str, prices: dict, when: str = "2026-09-21T19:00:00+00:00") -> list[Quote]:
    return [Quote(book=name, outcome=outcome, price=price, last_update=when)
            for outcome, price in prices.items()]


class TestDevig:
    def test_a_balanced_market_agrees_under_both_methods(self):
        """Nothing is paid for defaulting to power: on a level market the two
        land on the same number, because the margin has no lopsidedness to
        redistribute."""
        power = odds.devig([1.90, 1.90], method="power")
        proportional = odds.devig([1.90, 1.90], method="proportional")
        assert power == pytest.approx([0.5, 0.5], abs=1e-9)
        assert power == pytest.approx(proportional, abs=1e-9)

    def test_a_heavy_favourite_splits_the_two_methods(self):
        """The whole reason for the default: dividing by the sum inflates the
        long shot, which is the direction a fan wants to be wrong."""
        proportional = odds.devig([1.10, 8.00], method="proportional")
        power = odds.devig([1.10, 8.00], method="power")
        assert proportional == pytest.approx([0.87912, 0.12088], abs=1e-4)
        assert power == pytest.approx([0.89987, 0.10013], abs=1e-4)
        assert power[0] - proportional[0] > 0.015
        assert proportional[1] - power[1] > 0.015

    def test_the_divergence_scales_with_how_lopsided_the_market_is(self):
        """A near-level three-way barely moves; the extreme one moves a lot.
        That proportionality is the property being relied on."""
        level = odds.devig([2.10, 3.40, 3.60], method="power")
        level_naive = odds.devig([2.10, 3.40, 3.60], method="proportional")
        skewed = odds.devig([1.10, 8.00], method="power")
        skewed_naive = odds.devig([1.10, 8.00], method="proportional")
        assert abs(level[0] - level_naive[0]) < 0.01
        assert abs(skewed[0] - skewed_naive[0]) > 0.015

    @pytest.mark.parametrize("prices", [
        [1.90, 1.90], [1.10, 8.00], [2.10, 3.40, 3.60], [1.01, 50.0],
        [4.5, 3.9, 1.85], [1.33, 3.10],
    ])
    @pytest.mark.parametrize("method", ["power", "proportional"])
    def test_both_methods_always_sum_to_one(self, prices, method):
        assert sum(odds.devig(prices, method=method)) == pytest.approx(1.0, abs=1e-9)

    def test_the_exponent_brackets_an_extreme_market(self):
        """1.01 implies 0.990, and 0.990 ** 64 is still 0.53 -- a fixed upper
        bracket would fail exactly here, on the market power exists for."""
        result = odds.devig([1.01, 50.0], method="power")
        assert result[0] > result[1]
        assert sum(result) == pytest.approx(1.0, abs=1e-9)
        assert odds._power_exponent([odds.implied(1.01), odds.implied(50.0)]) > 1.0

    def test_a_price_at_or_below_one_raises(self):
        """A price that pays back no more than the stake is not a price."""
        with pytest.raises(ValueError):
            odds.implied(1.0)
        with pytest.raises(ValueError):
            odds.implied(0.5)

    def test_an_unbracketable_market_falls_back_to_proportional(self):
        """Two prices at 1.0001 have no k that sums their powers to one inside
        any sane ceiling. The answer is the naive one, not a hang."""
        result = odds.devig([1.0001, 1.0001], method="power")
        assert result == pytest.approx(odds.devig([1.0001, 1.0001], method="proportional"))

    def test_an_unknown_method_is_refused_by_name(self):
        with pytest.raises(ValueError):
            odds.devig([1.9, 1.9], method="shin")

    def test_overround_is_the_cut_not_the_total(self):
        assert odds.overround([1.90, 1.90]) == pytest.approx(0.05263, abs=1e-4)


class TestGuards:
    def test_a_single_sided_market_is_never_a_certainty(self):
        """A book that suspended one side posts one price. Normalizing one
        price gives 1.0, and "100% de chance" is the worst sentence here."""
        kept, dropped = odds.keep_books(odds.by_book(event(
            *book("suspended", {"Flamengo": 1.50}),
            *book("whole", {"Flamengo": 1.50, "Palmeiras": 2.80}),
        )))
        assert dropped == ["suspended"]
        rows, _cut = odds.consensus(kept)
        assert all(row["p"] < 1.0 for row in rows)

    def test_a_book_below_evens_is_dropped_not_devigged(self):
        """Prices summing under 1.0 mean the feed is mid-update. There is no
        cut to remove, and pretending there is invents a probability."""
        kept, dropped = odds.keep_books(odds.by_book(event(
            *book("broken", {"Flamengo": 2.60, "Palmeiras": 2.60}),
            *book("real", {"Flamengo": 1.90, "Palmeiras": 1.90}),
        )))
        assert dropped == ["broken"] and list(kept) == ["real"]

    def test_a_book_with_a_different_outcome_set_is_dropped(self):
        """One shop writing "Tie" where the rest write "Draw" is a different
        market, and mixing them invents a fourth outcome nobody priced."""
        three = {"Flamengo": 2.10, "Draw": 3.40, "Palmeiras": 3.60}
        kept, dropped = odds.keep_books(odds.by_book(event(
            *book("a", three), *book("b", three),
            *book("odd_one", {"Flamengo": 2.10, "Tie": 3.40, "Palmeiras": 3.60}),
        )))
        assert dropped == ["odd_one"] and set(kept) == {"a", "b"}

    def test_a_stale_quote_is_dropped(self):
        """A book that has not moved in two hours is answering yesterday."""
        fresh = {"Flamengo": 1.90, "Palmeiras": 1.90}
        quotes = book("fresh", fresh, when="2026-09-21T19:00:00+00:00")
        quotes += book("asleep", fresh, when="2026-09-21T17:00:00+00:00")
        kept, dropped = odds.keep_books(odds.by_book(event(*quotes)),
                                        at="2026-09-21T19:02:00+00:00")
        assert dropped == ["asleep"] and list(kept) == ["fresh"]

    def test_a_quote_without_a_timestamp_is_kept(self):
        """An absent field must not become an absent answer: the board was
        just read, and some providers do not stamp their quotes at all."""
        quotes = book("undated", {"Flamengo": 1.90, "Palmeiras": 1.90}, when="")
        kept, dropped = odds.keep_books(odds.by_book(event(*quotes)),
                                        at="2026-09-21T19:02:00+00:00")
        assert list(kept) == ["undated"] and dropped == []

    def test_the_dropped_are_counted_in_the_snapshot(self):
        """Discarding a shop in silence is three dead feeds behind a comment."""
        quotes = book("a", {"Flamengo": 1.90, "Palmeiras": 1.90})
        quotes += book("b", {"Flamengo": 1.95, "Palmeiras": 1.87})
        quotes += book("half", {"Flamengo": 1.90})
        snapshot = odds.build_snapshot(event(*quotes), at="2026-09-21T19:02:00+00:00")
        assert snapshot.books == 2 and snapshot.books_dropped == 1


class TestConsensus:
    def _spread_of_books(self, prices_per_book):
        quotes = []
        for name, prices in prices_per_book.items():
            quotes += book(name, prices)
        kept, _dropped = odds.keep_books(odds.by_book(event(*quotes)))
        return odds.consensus(kept)

    def test_the_median_resists_one_exotic_shop(self):
        """Five books, one of them wrong by twenty points. A mean would move."""
        rows, _cut = self._spread_of_books({
            "a": {"Flamengo": 1.90, "Palmeiras": 1.95},
            "b": {"Flamengo": 1.91, "Palmeiras": 1.94},
            "c": {"Flamengo": 1.89, "Palmeiras": 1.96},
            "d": {"Flamengo": 1.90, "Palmeiras": 1.95},
            "exotic": {"Flamengo": 3.50, "Palmeiras": 1.25},
        })
        flamengo = next(row for row in rows if row["name"] == "Flamengo")
        assert flamengo["p"] == pytest.approx(0.5039, abs=0.01)

    def test_dispersion_widens_when_the_books_disagree(self):
        agree, _ = self._spread_of_books({
            "a": {"Flamengo": 1.90, "Palmeiras": 1.95},
            "b": {"Flamengo": 1.91, "Palmeiras": 1.94},
            "c": {"Flamengo": 1.90, "Palmeiras": 1.95},
        })
        differ, _ = self._spread_of_books({
            "a": {"Flamengo": 1.50, "Palmeiras": 2.60},
            "b": {"Flamengo": 1.90, "Palmeiras": 1.95},
            "c": {"Flamengo": 2.40, "Palmeiras": 1.60},
        })
        assert differ[0]["spread"] > agree[0]["spread"] * 3

    def test_two_books_are_thin_never_firm(self):
        """Eight shops copying one feed is not a consensus, and neither are
        two shops that happen to agree."""
        rows, _cut = self._spread_of_books({
            "a": {"Flamengo": 1.90, "Palmeiras": 1.95},
            "b": {"Flamengo": 1.90, "Palmeiras": 1.95},
        })
        assert odds.confidence(rows[0], 2) == "thin"

    def test_eight_books_that_disagree_are_split_not_firm(self):
        row = {"name": "Flamengo", "p": 0.51, "spread": 0.18}
        assert odds.confidence(row, 8) == "split"
        assert odds.confidence({**row, "spread": 0.02}, 8) == "firm"

    def test_the_row_carries_the_posted_price_and_the_fair_one(self):
        """The quote is what a board prints; the fair price is the same bet
        with the cut removed. Both are said, and never confused."""
        rows, cut = self._spread_of_books({
            "a": {"Flamengo": 1.90, "Palmeiras": 1.90},
            "b": {"Flamengo": 1.90, "Palmeiras": 1.90},
            "c": {"Flamengo": 1.90, "Palmeiras": 1.90},
        })
        assert rows[0]["price"] == pytest.approx(1.90)
        assert rows[0]["fair_price"] == pytest.approx(2.0, abs=0.01)
        assert cut == pytest.approx(0.0526, abs=1e-3)

    def test_the_probabilities_still_sum_to_one_after_the_medians(self):
        rows, _cut = self._spread_of_books({
            "a": {"Flamengo": 2.10, "Draw": 3.40, "Palmeiras": 3.60},
            "b": {"Flamengo": 2.05, "Draw": 3.50, "Palmeiras": 3.75},
            "c": {"Flamengo": 2.20, "Draw": 3.30, "Palmeiras": 3.50},
        })
        assert sum(row["p"] for row in rows) == pytest.approx(1.0, abs=1e-3)

    def test_no_books_is_an_empty_answer_not_a_crash(self):
        rows, cut = odds.consensus({})
        assert rows == [] and cut == 0.0


class TestSnapshot:
    def test_a_snapshot_says_how_it_was_computed(self):
        quotes = book("a", {"Flamengo": 2.10, "Draw": 3.40, "Palmeiras": 3.60})
        quotes += book("b", {"Flamengo": 2.05, "Draw": 3.50, "Palmeiras": 3.75})
        quotes += book("c", {"Flamengo": 2.20, "Draw": 3.30, "Palmeiras": 3.50})
        snapshot = odds.build_snapshot(event(*quotes), at="2026-09-21T19:02:00+00:00")
        assert snapshot.method == "power" and snapshot.books == 3
        assert snapshot.overround > 0
        assert [row["name"] for row in snapshot.outcomes][0] == "Flamengo"
        assert all("confidence" in row for row in snapshot.outcomes)
        assert snapshot.as_dict()["outcomes"] == snapshot.outcomes

    def test_an_event_with_no_usable_book_names_no_method(self):
        """Saying "power" over nothing would dress an empty answer as a result."""
        snapshot = odds.build_snapshot(event(*book("half", {"Flamengo": 1.5})),
                                       at="2026-09-21T19:02:00+00:00")
        assert snapshot.outcomes == [] and snapshot.method == ""
        assert snapshot.books == 0 and snapshot.books_dropped == 1
