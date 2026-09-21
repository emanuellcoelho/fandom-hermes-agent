"""Which fixtures belong to a subject -- and, above all, which do not.

The news filter may match "inter" inside "inter miami": a wrong headline is
cheap. These tests exist because a wrong probability is not.
"""

from fandom.engine import odds_match
from fandom.models import Sport, Team


def team(**kwargs) -> Team:
    base = {"key": "inter", "name": "Internacional", "sport": Sport.FUTEBOL,
            "aliases": ["inter", "colorado"]}
    return Team(**{**base, **kwargs})


class TestResolve:
    def test_returns_nothing_without_a_stored_link(self, odds_traps):
        """No link, no guess. Never a best effort, because a best effort here
        is a number about the wrong club."""
        assert odds_match.resolve(odds_traps, team()) == []

    def test_never_matches_a_near_name(self, odds_traps):
        """The whole reason this module is not the news filter."""
        linked = team(odds_sport="soccer_brazil_campeonato", odds_key="Internacional")
        found = odds_match.resolve(odds_traps, linked)
        assert [event.event_id for event in found] == ["t1"]
        assert all("Miami" not in event.home_team for event in found)

    def test_a_league_follow_takes_the_whole_board(self, odds_traps):
        """A league is followed by sport alone: every fixture is its fixture."""
        league = team(key="brasileirao", name="Brasileirão Série A",
                      aliases=[], odds_sport="soccer_brazil_campeonato")
        found = odds_match.resolve(odds_traps, league)
        assert {event.event_id for event in found} == {"t1", "t3", "t6"}

    def test_the_wrong_sport_key_never_matches_even_on_an_exact_name(self, odds_traps):
        """Two boards can print the same club in different competitions; the
        stored link names one of them."""
        linked = team(odds_sport="soccer_epl", odds_key="Internacional")
        assert odds_match.resolve(odds_traps, linked) == []


class TestCandidates:
    def test_rank_the_right_club_first_and_still_list_the_trap(self, odds_traps):
        """The near miss is shown, not hidden: seeing the trap is how the
        person confirming avoids it."""
        found = odds_match.candidates(odds_traps, team())
        assert found[0]["name"] == "Internacional"
        assert any(entry["name"] == "Inter Miami CF" for entry in found)
        assert found[0]["score"] > next(e for e in found if e["name"] == "Inter Miami CF")["score"]

    def test_three_atleticos_are_all_offered(self, odds_traps):
        """"Atlético" alone is three clubs on two continents. The list says so
        instead of picking."""
        mineiro = team(key="galo", name="Atlético", aliases=["atletico"])
        names = {entry["name"] for entry in odds_match.candidates(odds_traps, mineiro)}
        assert {"Atlético Mineiro", "Atlético Goianiense", "Atlético Madrid"} <= names

    def test_the_two_manchesters_are_both_offered(self, odds_traps):
        united = team(key="manchester", name="Manchester", aliases=[])
        names = {entry["name"] for entry in odds_match.candidates(odds_traps, united)}
        assert names == {"Manchester United", "Manchester City"}

    def test_an_exact_alias_outranks_a_shared_first_token(self, odds_traps):
        exact = team(key="atletico-mg", name="Atlético Mineiro", aliases=["atlético-mg"])
        found = odds_match.candidates(odds_traps, exact)
        assert found[0]["name"] == "Atlético Mineiro"

    def test_a_sport_key_already_chosen_narrows_the_list(self, odds_traps):
        """Half the linking conversation is choosing the league; after that,
        the other league's clubs are noise."""
        narrowed = team(odds_sport="soccer_brazil_campeonato")
        names = {entry["name"] for entry in odds_match.candidates(odds_traps, narrowed)}
        assert names == {"Internacional"}

    def test_candidates_never_commit_anything(self, odds_traps):
        """It proposes; the person disposes. Nothing is written here."""
        subject = team()
        odds_match.candidates(odds_traps, subject)
        assert subject.odds_key is None and subject.odds_sport is None

    def test_an_unknown_name_ranks_nothing(self, odds_traps):
        assert odds_match.candidates(odds_traps, team(key="x", name="Wolfsburg", aliases=[])) == []

    def test_the_candidate_carries_the_next_opponent_for_the_conversation(self, odds_traps):
        """"Internacional, que pega o Grêmio" is how a person recognizes the
        right club without knowing what a sport_key is."""
        found = odds_match.candidates(odds_traps, team())
        assert found[0]["next_against"] == "Grêmio"
        assert found[0]["sport_key"] == "soccer_brazil_campeonato"
