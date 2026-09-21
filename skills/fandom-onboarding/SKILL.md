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
3. **Digest time** — offer the default, in their language: "resumo todo dia
   às 08:30, bom?" / "a roundup every morning at 08:30, good?"
   Save as `digest_time=HH:MM`, `digest_enabled=false` if they decline.
   (In your own words to the user it is the "resumo da manhã" / "morning
   roundup"; `digest` is the command's name, never theirs.)
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
   leaving a Brazilian league in the morning digest of someone in Chicago.

## Timezone is fixed at boot

The container's `TZ` is set from `timezone` in the config **when the
container starts**. After saving a timezone, compare with `echo $TZ`:

- Same: register the schedules now (below).
- Different: say the zone lands "no próximo reinício" and register only after
  that restart. **Never register schedules whose zone disagrees with the
  container** — they would fire at the wrong local hour, silently.

## Registering the schedules (after config is complete)

Registered once, by you, from a turn (a turn carries the gateway's
environment; a bare exec does not):

    /opt/hermes/bin/hermes cron create "30 8 * * *" \
      "Run the fandom digest now: execute fandom.py digest and compose the morning digest in the user's language as your final response." \
      --name fandom-digest --skill fandom-news \
      --model anthropic/claude-sonnet-5 --provider plow \
      --deliver "plow_chat:${PLOW_HOME_CHANNEL}"

    /opt/hermes/bin/hermes cron create "0 12,19 * * *" \
      "Run the fandom matchday now: execute fandom.py matchday, and only if a followed team has a game today or a fresh result, compose the matchday message in the user's language and post it with post_chat.py; otherwise post nothing and end with NO_REPLY." \
      --name fandom-matchday --skill fandom-watch \
      --model anthropic/claude-sonnet-5 --provider plow

A cron created without `--model` and `--provider` lands with no LLM provider
and fails every run with "No LLM provider configured" — always pass both.

The digest's `30 8` follows the user's `digest_time` (re-register after a
change — remove the old job first with `hermes cron remove fandom-digest`).
If a job already exists, skip it — never duplicate a schedule.
