---
name: fandom-onboarding
description: First-contact setup — timezone, language, digest time and which teams to follow. Use when a follow exists but onboarding is unfinished (onboarding_missing is non-empty), or the user asks to change these preferences.
---

# Fandom Onboarding — once, after the first value

The first-value rule outranks this conversation: **a team or league is
followed before any question is asked.** Onboarding starts only after a
follow is confirmed, and it is a conversation — one or two questions per
message, in the user's language.

Finished means `fandom.py teams list` answers `onboarding_missing: []`.

## The questions, in order

1. **Language** — detected from their messages; save the first time they
   reply (`config set language=pt-BR`).
2. **Timezone** — needed so the digest lands at the right local hour. A city
   name becomes its IANA zone. Save it.
3. **Digest times** — offer the default, in their language: "resumo 3x por
   dia — manhã (08:00), tarde (12:00) e noite (18:00), bom?" / "a roundup
   three times a day — morning (08:00), afternoon (12:00) and evening
   (18:00), good?" If they want fewer or different times, take them as a
   list. Save as `digest_times=HH:MM,HH:MM,HH:MM` (comma-separated, in the
   order they fire), `digest_enabled=false` if they decline entirely.
   (In your own words to the user each one is the "resumo da manhã" / "da
   tarde" / "da noite" — "morning/afternoon/evening roundup" — picked from
   the local hour it actually fires at; `digest` is the command's name,
   never theirs.)
4. **What else to follow** — ask what they actually root for, one at a time,
   and add each with its aliases. `teams remove <key>` for what they do not
   want.

   **Never add a bare name.** Run `search_team <name>` first — it confirms
   which subject the name means and gives the league — then add with
   aliases and the id: `teams add … --source-id <results[0].id> --aliases …`.

   The aliases are what keep the news on target. The sweep queries
   `name OR alias OR alias`, so a bare common noun drags in the rest of the
   language: "Arsenal" alone returns a munitions plant in Arkansas,
   "Flamengo" alone returns Flamengo-PI and the under-17 squad. Measured on
   Arsenal, 6 headlines a run: 4 of 6 off-subject with the name alone, 0 of 6
   with "Arsenal FC" and "Gunners" alongside. Ask the user for the nickname
   they actually use — it is a natural question and it is the fix.

   If `search_team` returns more than one, ask which — the league in each
   result is the question ("Premier League ou o Arsenal de Sarandí?"). If it
   returns nothing, add with aliases anyway and say live scores are
   unavailable for that one, the way the watch skill describes.

   Call the id what it is in their words: "placar em tempo real" / "live
   scores", never "provedor" or "provider".

   The seed the agent boots with is Brazilian (Brasileirão, CBLOL, NBA,
   CS2). It is a starting point, not a preference: **if their language is
   not pt-BR, do not present it** — clear what they do not recognise with
   `teams remove` as soon as they tell you what they follow, rather than
   leaving a Brazilian league in the digest of someone in Chicago.

## Registering the schedules (as soon as the config is complete)

**Never postpone this.** The container's `TZ` is written once, at boot, from a
config the user had not filled in yet — so after onboarding it is almost
always UTC while the user lives somewhere else. The old instruction here was
to wait for a restart that realigns them. Nobody restarts a cloud agent: this
agent ran five days in production with no schedule at all, and the roundup
is the whole product.

Ask the engine for the specs instead of doing the arithmetic yourself:

    fandom.py schedule

    {"timezone": "America/Sao_Paulo", "container_tz": "UTC", "aligned": false,
     "drifts_after_dst": false,
     "digest":   {"name": "fandom-digest",   "local": ["08:00","12:00","18:00"],
                  "fires": ["11:00","15:00","21:00"],
                  "cron": "0 11,15,21 * * *", "enabled": true},
     "matchday": {"name": "fandom-matchday", "local": ["12:00","19:00"],
                  "fires": ["15:00","22:00"], "cron": "0 15,22 * * *"}}

`cron` is the field to register, always — it is the user's local hours restated
in the zone the job will actually fire in, folded into one daily spec when they
share a minute (the default 08:00/12:00/18:00 always does). `local` is what
you say to them ("o resumo da manhã cai às 08:00, o da tarde às 12:00, o da
noite às 18:00"); `fires` is the same instants in the container's zone and is
never spoken aloud.

An empty `cron` has two different causes, and they call for different repairs:
a time that could not be parsed at all (ask again rather than registering a
guess), or digest times that do not share a minute (e.g. 08:15 and 12:00) --
`cron_of` refuses to round anyone's schedule for tidiness. In the second case
`fires` is still populated: register one `fandom-digest` job per moment
instead of one job for all of them, naming each `fandom-digest-1`,
`fandom-digest-2`, … in firing order, all pointing at the same prompt and
skill.

Registered once, by you, from a turn (a turn carries the gateway's
environment; a bare exec does not):

    /opt/hermes/bin/hermes cron create "<digest.cron>" \
      "Run the fandom digest now: execute fandom.py digest and compose the roundup in the user's language as your final response, calling it resumo da manhã/da tarde/da noite (or morning/afternoon/evening roundup) by the local hour it is actually firing at." \
      --name fandom-digest --skill fandom-news \
      --model anthropic/claude-sonnet-5 --provider plow \
      --deliver "plow_chat:${PLOW_HOME_CHANNEL}"

    /opt/hermes/bin/hermes cron create "<matchday.cron>" \
      "Run the fandom matchday now: execute fandom.py matchday, and only if a followed team has a game today or a fresh result, compose the matchday message in the user's language and post it with post_chat.py; otherwise post nothing and end with NO_REPLY." \
      --name fandom-matchday --skill fandom-watch \
      --model anthropic/claude-sonnet-5 --provider plow

**Use this CLI, not the scheduling tool.** A job created through the generic
scheduling tool lands with `model: null`, because that tool has no way to set
one — and a job with a provider and no model passes validation, then fails
every single run with "No LLM provider configured". The message misleads: the
provider is there, the model is what is missing. It killed `fipe-sweep` for
two rounds on 16/09 and it cost this agent its first evening of schedules on
21/09. Always pass both flags, and check afterwards:

    /opt/hermes/bin/hermes cron list            # the `model` field, not just `provider`
    /opt/hermes/bin/hermes cron edit <job_id> --model anthropic/claude-sonnet-5 --provider plow

`digest.enabled: false` means they declined the roundup: register the matchday
job anyway and skip the digest.

### When the conversion can go stale

`drifts_after_dst: true` means the user's zone changes offset during the year
(most of Europe and North America; Brazil has not since 2019). A converted job
is exact until that transition and an hour off after it, because the container
does not follow a zone it was never told about. Two things follow:

- Say nothing about it during onboarding. It is a detail about infrastructure,
  and the schedule is correct today.
- Re-run `fandom.py schedule` and re-register whenever the agent restarts, and
  after any offset change. When `aligned` is true the conversion disappears and
  the drift cannot happen at all — a restart is the cure, not a prerequisite.

After any change to `timezone` or `digest_times`, re-run `fandom.py schedule`,
remove the old job (`hermes cron remove fandom-digest`) and create it again.
If a job already exists and its spec still matches, leave it — never duplicate
a schedule.
