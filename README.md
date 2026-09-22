# Fandom

> **Seu time, seu noticiário: futebol, NBA, NFL e e-sports.**
> **Your teams, your news — scores and the digest, three times a day.**

A sports-fandom [Plow](https://plow.co) agent, Brazilian first. Text it a
team, a league or an esports scene and it follows the headlines for you:
matches, signings, market moves, championships — futebol 🇧🇷, NBA 🏀, NFL 🏈,
CBLOL/CS2/Valorant 🎮. Digest three times a day (manhã, tarde, noite) by
default, matchday alerts, honest about what it could not confirm.

A Hermes agent built on the
[`plow-hermes-agent`](https://github.com/plow-pbc/plow-hermes-agent) base
image for the AI Worth Using Hackathon, September 2026. Sibling of
[`vigia-hermes-agent`](https://github.com/emanuellcoelho/vigia-hermes-agent)
— same template, different domain.

## What it does

- **Follow by name** — "me acompanha no Corinthians" creates the follow with
  nicknames ("Timão") that match headlines; leagues and esports scenes
  follow the same way ("Brasileirão", "CBLOL").
- **Digest, three times a day** — news grouped by followed subject from live
  feeds (ge.globo, ESPN, BBC), one line each with link; transfers marked as
  *Mercado:* rumor, never as fact. Fires manhã/tarde/noite (08:00/12:00/18:00)
  by default, configurable during onboarding.
- **Matchday** — next fixture, live score and last result when the provider
  has them; when it does not, the agent says "placar não confirmado" instead
  of guessing.
- **Bilingual** — pt-BR voice by default, English when the user writes in
  English.

## Install

```sh
git clone https://github.com/plow-pbc/plow-agents.git
export PATH="$PWD/plow-agents/bin:$PATH"

git clone https://github.com/emanuellcoelho/fandom-hermes-agent.git
cd fandom-hermes-agent

plow-agents login             # once per account; text the activation phrase
plow-agents lines             # pick a free line
plow-agents mint ln_xxx       # writes ./plow-credentials
docker compose up --build -d
```

`mint` must run **before** `up`: the compose file mounts `./plow-credentials`,
and Docker silently creates it as a *directory* if the file is not there yet.
If that happened, `docker compose down -v && rmdir plow-credentials`, then
mint the line and start over.

Watch `docker compose logs -f agent` until
`plow-init: configured ... as cht_` appears, then text your line. The first
team you mention is followed immediately — onboarding happens after that,
never before.

If the build fails pulling the base image from `public.ecr.aws` with a 403,
the cause is a stale credential: `docker logout public.ecr.aws`, then build
again.

Optional: `SCRAPERAPI_KEY` turns on the professional scraping fallback for
JSON APIs this network cannot reach directly.

## Architecture

```
skills/fandom-watch/scripts/
├── fandom.py           # thin CLI; every command answers one JSON object
├── kit/                # domain-free infrastructure: clock, http, jsonio
└── fandom/
    ├── models.py       # Team (team, league or scene), NewsItem, Match
    ├── store.py        # teams.json + news cache, written atomically
    ├── sources/        # RSS (ge, ESPN, BBC), TheSportsDB; dead feed = ⚠️
    └── engine/
        ├── news_filter.py  # pure: aliases, accents, market topics, dedup
        ├── digest.py       # the roundup payload (fires 3x/day by default)
        └── matchday.py     # fixtures, live, results — honest by design

skills/fandom-watch/SKILL.md      # the voice: follows, news, matchday
skills/fandom-news/SKILL.md       # the day's reads (manhã, tarde, noite)
skills/fandom-onboarding/SKILL.md # first contact, after the first value
```

Scripts are mechanical (one JSON object, no human words); SKILL.md files are
the voice. The news filter is pure — normalized aliases decide what matches
("Timão", "Mengão", "atletico mg"), never a guess. A score exists only when
`matchday` returned one.

Schedules, registered by the agent itself during onboarding:

| name | schedule (container TZ) | delivery |
| --- | --- | --- |
| `fandom-digest` | `0 8,12,18 * * *` (yours to choose) | cron `--deliver` to your chat |
| `fandom-matchday` | `0 12,19 * * *` | one message only when there is a game or result |

## Privacy

The usage reporter publishes **token counts only** — day × model, no prompts,
no URLs, no followed teams. Followed subjects live in the agent's own volume
(`/var/lib/hermes/fandom/`); nothing under the tracked tree carries a
credential, a chat id, or personal data.

## Tests

```sh
python3 -m pytest tests/ -q
```

Fixture-fed with real saved feeds (ge.globo, BBC, TheSportsDB): no network,
no clock sleeps.

## Where changes go

- Boot, `plow-init`, gateway config —
  [`plow-hermes-agent`](https://github.com/plow-pbc/plow-hermes-agent).
- This repo's conventions and the fork guide — [`AGENTS.md`](AGENTS.md).

## License

[MIT](LICENSE) — with Apache-2.0 attributions for parts derived from
[plow-pbc](https://github.com/plow-pbc) repositories, in [NOTICE](NOTICE).