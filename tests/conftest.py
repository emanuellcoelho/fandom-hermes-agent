"""Test wiring: make the scripts package importable, hand out fresh homes."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "fandom-watch" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from fandom.store import FandomStore  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture()
def store(tmp_path):
    return FandomStore(str(tmp_path / "fandom"))


@pytest.fixture()
def ge_feed() -> bytes:
    return (FIXTURES / "ge-geral.xml").read_bytes()


@pytest.fixture()
def bbc_feed() -> bytes:
    return (FIXTURES / "bbc-sport.xml").read_bytes()


@pytest.fixture()
def sdb_team() -> dict:
    import json
    return json.loads((FIXTURES / "sdb-corinthians.json").read_text())

@pytest.fixture()
def odds_traps() -> list:
    """The name-trap board: hand-built, and the only fixture here that is.

    Every other fixture is a real saved body, because a parser must be tested
    against what a provider really sends. This one tests a decision, not a
    parser: the pairs are the clubs whose names collide, shaped the way the
    matcher consumes them.
    """
    import json
    from fandom.models import OddsEvent
    raw = json.loads((FIXTURES / "odds-traps.json").read_text())
    return [OddsEvent.from_dict(event) for event in raw["events"]]
