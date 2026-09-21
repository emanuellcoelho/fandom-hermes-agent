# Fandom — AGENTS.md

A sports-fandom Plow agent (BR-first), and the second agent built on the
Vigia template. Read this before changing anything; it says who owns what
and where a change goes.

## The one test

**Who else would have to change if this fact changed?** That owner is where
the change goes.

| Path | Owns | Never here |
| --- | --- | --- |
| `plow-pbc/plow-hermes-agent` (base) | boot, `plow-init`, gateway config, base persona, plugin pin | anything Fandom-specific |
| `persona.md` | Fandom's voice: language mirroring, first-value rule, honesty about scores | per-turn plumbing, tool how-tos |
| `skills/fandom-watch/` | the engine: models, sources, news filter, matchday, store — and its SKILL.md | chat delivery (post_chat.py is its only exception, mechanically) |
| `skills/fandom-news/` | the morning digest conversation and sports small-talk | news filtering (engine owns those) |
| `skills/fandom-onboarding/` | first contact, config questions, cron registration | the engine's defaults (config.py owns those) |
| `skills/fandom-watch/scripts/kit/` | generic infrastructure: clock, http, jsonio — domain-free | anything that knows what a match is |
| `fandom/engine/odds*.py` | de-vig, consensus, the odds file, the credit ledger, board name matching | fetching, and any human word about a price |
| `fandom/sources/odds.py` | calling the board and stripping the key out of every URL that leaves | what a probability means |
| the odds edge (outside this repo) | holding the API key, caching, speaking v4 verbatim | anything this suite can test — it is operated elsewhere |
| `image/` | s6 services (agent-index reporter), TZ cont-init | gateway config, plow-init — the base's |
| `vendor/client.pin` | which agent-index-client commit runs inside the agent | a vendored copy that drifts |
| `Dockerfile` / `compose.yml` | how this content ships | base-image behavior |

Sibling repo: [`vigia-hermes-agent`](https://github.com/emanuellcoelho/vigia-hermes-agent)
shares this structure. `kit/` is **compatible, not byte-identical**: the two
copies of `http.py` already differ, in the User-Agent (Vigia still sends a
browser's; this one sends its own name, which is what stopped ESPN answering
202 with an empty body) and in the retry backoff. Same names, same
signatures, same meanings — a function added to one belongs in the other, and
`fetch_headers` is the next thing to carry across.

## Conventions

- **Scripts are mechanical.** One JSON object on stdout, exit 0/1/2, no human
  words. SKILL.md files are the voice. No prompt text in Python.
- **stdlib only.** No new dependencies in scripts or the image.
- **The news filter is pure** (`fandom/engine/news_filter.py`): no IO, no
  clock. A dead feed degrades with an ⚠️ line — never a crash, never silence.
- **Honesty is architectural**: a score exists only when `matchday` returned
  one; a headline exists only when `news` output it.
- **Writes are atomic** (`kit.jsonio.save_json_atomic`).
- **No credential in this tree.** The odds board needs a key; the agent does
  not carry it. An edge outside this repo holds it and speaks the provider's
  API verbatim, so the agent calls a public URL. The one function allowed to
  read `ODDS_API_KEY` is `sources/odds.py::_base_and_auth`, for development
  against the origin, and it writes nothing. Every URL that leaves that
  module is redacted, because `source_health` keys its record by URL and
  writes it to disk; `test_odds_cli.py` walks the whole home reading bytes to
  prove it.
- **State lives in `/var/lib/hermes/fandom/`** (override `FANDOM_HOME` for
  tests). Nothing under this tree carries a credential, a chat id, or
  personal data.
- **TZ is fixed at boot** from `fandom/config.json`.

## Commits

Conventional, scoped by the table above, imperative, one concern per commit:
`feat(engine):`, `feat(sources):`, `feat(skills):`, `feat(report):`,
`fix(...)`, `docs:`, `chore:`. The body says **why**; the diff says what.
Never in a commit: `plow-credentials`, state files, anything under a
`FANDOM_HOME`. A pin bump is its own commit naming what moved and why.

## Tests

A URL only enters `config.FEEDS` — or `sources/odds.py::_EDGE_DEFAULT` — after
its live test passes on it:

    FANDOM_LIVE_FEEDS=1 python -m pytest tests/test_feeds_live.py -q
    FANDOM_LIVE_ODDS=1 python -m pytest tests/test_odds_live.py -q

It fetches through `kit.http`, the same path production uses. Validating a feed
with curl proves nothing about this agent -- ESPN answered our old spoofed
User-Agent with HTTP 202 and an empty body while answering curl with the feed,
and three sources stayed dead for days behind a comment saying they were alive.


    python3 -m pytest tests/ -q

Pure and fixture-fed: real saved RSS bodies and provider answers, no network,
no clock sleeps.

## Schedules (the registered spec)

| name | schedule (container TZ) | deliver |
| --- | --- | --- |
| `fandom-digest` | `30 8 * * *` (onboarding writes the user's time) | native `--deliver` to `plow_chat:${PLOW_HOME_CHANNEL}` |
| `fandom-matchday` | `0 12,19 * * *` | post_chat.py only when there is a game/result; quiet = NO_REPLY |

Changing these rows is an edit to `fandom-onboarding/SKILL.md` and this table
together.

## Forking this into a new agent

Same as Vigia's guide: copy the tree, swap `persona.md` + the domain layer
(`fandom/` → yours; `kit/` stays), new `AGENT_ID`, new registration, new
compose `AGENT_ID`. LICENSE stays MIT; NOTICE keeps the Apache attributions.