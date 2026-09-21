"""Source contract shared by every fandom reader."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceError(RuntimeError):
    """One provider's failure. A digest survives any of these."""

    source: str
    reason: str

    def __str__(self) -> str:
        return f"{self.source}: {self.reason}"

@dataclass(frozen=True)
class PlannedSource:
    """One URL the sweep will read, once, however many subjects want it.

    Feeds are shared: the BBC sport feed used to be fetched three times a run
    because the seed follows three subjects that list it. The plan is the set
    of distinct URLs, so a shared feed is read once and -- when it fails --
    reported once.
    """

    url: str
    label: str


@dataclass(frozen=True)
class SourceOutcome:
    """What one planned source actually did. Never raised, always returned."""

    url: str
    label: str
    ok: bool
    items: tuple = ()
    error: str = ""

    def as_failure_line(self) -> str:
        """The legacy `failed_sources` string, unchanged for the skills."""
        return f"{self.label}: {self.error[:120]}"
