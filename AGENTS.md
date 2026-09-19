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
| `image/` | TZ cont-init | gateway config, plow-init, agent-index reporter — the base's |
| `Dockerfile` / `compose.yml` | how this content ships | base-image behavior |

Sibling repo: [`vigia-hermes-agent`](https://github.com/emanuellcoelho/vigia-hermes-agent)
shares this structure; `kit/` stays byte-identical across forks until a
second fork confirms the pattern graduates it into a package.

## Conventions

- **Scripts are mechanical.** One JSON object on stdout, exit 0/1/2, no human
  words. SKILL.md files are the voice. No prompt text in Python.
- **stdlib only.** No new dependencies in scripts or the image.
- **The news filter is pure** (`fandom/engine/news_filter.py`): no IO, no
  clock. A dead feed degrades with an ⚠️ line — never a crash, never silence.
- **Honesty is architectural**: a score exists only when `matchday` returned
  one; a headline exists only when `news` output it.
- **Writes are atomic** (`kit.jsonio.save_json_atomic`).
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