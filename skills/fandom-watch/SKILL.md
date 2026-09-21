---
name: fandom-watch
description: Follow teams, leagues and esports scenes; fetch and filter the news; check matchday fixtures. Use when the user mentions a team or league to follow, asks what is new about their teams, asks about games, or when the news/matchday crons fire.
---

# Fandom Watch — the engine

Every followed subject, every headline, every fixture goes through one CLI.
The scripts are mechanical and answer **one JSON object on stdout**; you own
every human word around them.

    FANDOM=/var/lib/hermes/skills/fandom-watch/scripts
    /opt/hermes/.venv/bin/python3 $FANDOM/fandom.py <command>

Exit 0 is success, 2 is failure with an `error` field — read it, never guess.

## Following — the first-value rule

A message naming a team, league or scene is always a follow request.
**Never add a bare name — always carry aliases:**

    fandom.py search_team Arsenal          # -> results[].id, league, sport
    fandom.py teams add Arsenal --sport soccer --source-id 133604 \
        --aliases "Arsenal FC" "Gunners"

Aliases are not decoration, they are the disambiguation. The Google News
query is `name OR alias OR alias`, so a bare common noun drags in whatever
else carries it: "Arsenal" alone returns a munitions plant in Arkansas,
"Flamengo" alone returns Flamengo-PI and the under-17 side. Measured on
Arsenal, 6 headlines each run: **4 of 6 off-subject with the name alone,
0 of 6 once "Arsenal FC" and "Gunners" ride along.** The `--source-id`
changes nothing here — it buys fixtures, not relevance — so aliases are the
part you must not skip.

`search_team` still comes first: it confirms which subject the name means
and answers with the league, which is what tells you the right aliases.

`--sport` takes the name in the user's language — `soccer`, `football`,
`basketball`, `american football`, `nfl`, `gaming` all resolve, as do
`futebol`, `basquete`, `futebol_americano`, `esports`.

Aliases are what match headlines — include nicknames ("Gunners", "Timão",
"Mengão") and common spellings, in the language the headlines are written
in. For esports, the scene is the subject:

    fandom.py teams add CBLOL --sport esports --aliases "CBLOL" "LoL brasileiro"
    fandom.py teams add "Team Liquid" --sport gaming --aliases "Liquid" "TL"

Confirm the follow in one short line. Never gate it on onboarding.

## The news sweep

    fandom.py news --limit 5

Run it when the user asks what's new, or when the digest cron fires. The
output groups headlines by followed team. Present them in the user's
language — **only headlines the JSON carries**, each with its link. A
headline the script did not output does not exist.

The sweep reads the sport's general feeds (ge, ESPN, BBC) **plus one Google
News search per subject**, built from its name and aliases in the user's
language — that is how scenes without dedicated feeds (CS2, CBLOL) still
get headlines. Team-specific feeds stay dead silently if a provider refuses;
the subject's search feed carries it.

## Matchday — honest by design

    fandom.py matchday            # every followed team
    fandom.py matchday <key>      # one team

A team without `source_id` answers with a `note` — say the fixture is not
confirmed instead of guessing. A `result` with a `score` is the only placar
you may state. The free provider often answers empty: that is "não achei
jogo confirmado", never "não tem jogo".

**Live games have a second road.** When a matchday answer is empty — a
league follow with no provider, or the free tier's silence — run:

    fandom.py live

It merges what the feeds are literally shouting (headlines carrying
"Ao vivo" / "Live") with the fixtures of teams that do have a provider.
Present the headlines as **what the feeds show right now**, with their
links — "o ge está marcando Flamengo x Corinthians como ao vivo agora" —
and never attach a score to them. A live headline is a pointer; a placar
comes only from `matchday`. Then offer to turn on the team's placar em
tempo real (live scores) — in those words, never "provedor" — which is
what unlocks real scores.

## Cotação — o mercado como descrição, nunca como conselho

    fandom.py odds show                    # every linked subject
    fandom.py odds show flamengo           # one of them
    fandom.py odds show flamengo --no-spend    # cache only, costs nothing

**Only when asked.** Never open a resumo, a matchday reply or a follow
confirmation with a cotação. The number answers a question; it never starts a
conversation.

### Linking first — nothing is matched by resemblance

An unlinked subject answers `{"key": "...", "reason": "unlinked"}` and no
number. That is by design: the board prints "Internacional" and also "Inter
Miami CF", and attaching a probability to the wrong club is the one error
this agent may not make. The link is a short conversation:

    fandom.py odds link flamengo                                   # which competitions
    fandom.py odds link flamengo --sport-key soccer_brazil_campeonato   # ranked spellings
    fandom.py odds link flamengo --sport-key soccer_brazil_campeonato --name "Flamengo"
    fandom.py odds link brasileirao --sport-key soccer_brazil_campeonato --league

All three modes are free. Ask with the opponent, never with the key —
"o Internacional que pega o Grêmio no domingo?" — because `next_against` is
in every candidate and `sport_key` means nothing to a person. `--league`
follows the whole competition; `--name` follows one club and must be the
board's exact spelling, which is why you pick it from `candidates` instead
of typing it.

### Saying the number

Every event carries `outcomes[].p` (the probability with the house's margin
removed), `price` (what the board posts), `confidence`, `books`, `age_minutes`
and `stale`.

    📊 *Flamengo x Palmeiras* — domingo, 19h
    O mercado dá *51%* pro Mengão, 26% empate, 23% pro Palmeiras.
    7 casas, lidas há 12 minutos.

Rules that are not style:

- **Age, always.** Say "há 12 minutos", "de ontem à noite". `stale: true`
  means say it or say nothing — never serve an old number bare.
- **`p`, not the raw division.** The payload already removed the margin;
  `overround` is how big the cut was, and it is *not* anyone's chance.
- **`price` is a quote, `fair_price` is not.** `fair_price` is the same bet
  without the house's cut — a number no shop offers. If you say it, say that.
- **`confidence`**: `firm` = the books agree, say the number plainly. `split`
  = "as casas discordam, entre 46% e 58%" — say the range instead. `thin` =
  fewer than three books, "pouca casa cotando, dá pra ficar de olho mas não
  vale número redondo".
- **`books_dropped`** is only worth mentioning when it is most of them.
- Nenhuma casa é destino. Cite "7 casas" como origem do número; nunca
  "na Bet X está 1.95", nunca um link, nunca onde apostar.
- Nunca palpite, valor, entrada, banca, unidade. A frase é sobre o mercado,
  não sobre a noite de ninguém.

### When there is no number — the tokens and what they mean

| token | what happened | say |
| --- | --- | --- |
| `unlinked` | nobody confirmed which board entry this is | offer the link conversation |
| `sport_not_covered` | this board carries no such sport | say it once, and drop it |
| `quota` / `monthly_reserve` | the credits for the window are gone | "o quadro de cotação fechou por hoje", then serve the cached line with its age |
| `daily_budget` | today's reads are spent | same, and the cache still answers |
| `unconfigured` | no board is wired to this agent | not the user's problem — say cotação is not turned on here |
| `error` | the board failed | it is in `sources` like any dead feed: ⚠️ once, never every morning |

**E-sports has no board.** CBLOL and CS2 answer `sport_not_covered`, and that
is a fact about the market, not a bug. Say it once, in one line, and never
bring it up again.

### The digest carries the block and does not print it

`fandom.py digest` includes an `odds` block, read from the cache, costing
nothing. The morning message still says nothing about cotação. It is there so
that a "e a cotação do jogo?" right after the resumo is answered from what is
already in hand instead of a new call.

## Reply formats

Follow confirmed:

    ✅ Seguindo *Flamengo* 🇧🇷 ⚽ — notícias do ge, ESPN e BBC, digest todo dia às 08:30.

Morning digest (the final response IS the digest — cron `--deliver` relays it):

    📰 *Fandom do dia* — 13/09

    ⚽ *Brasileirão* — 4 notícias
    • Flamengo vence e assume a liderança — ge.globo.com/…
    • 🛒 *Mercado:* Vasco propõe por atacante do Bahia — ge.globo.com/…

    🏀 *NBA* — 1 notícia
    • Lakers anunciam renovação — espn.com/…

    ⚠️ Sem resposta de: espn.com — tento de novo amanhã.

Movement marks: 🛒 `transfers` are market *rumor*, labeled as such. Sport
emojis: ⚽ futebol, 🏀 basquete, 🏈 NFL, 🎮 e-sports. Flag follows the league
country (Brasileirão 🇧🇷, NBA 🇺🇸, CBLOL 🇧🇷). A quiet day is two lines, not
silence:

    📰 *Fandom do dia* — nada se mexeu nas 3 cenas que você segue. Dia de treino.

## Config

    fandom.py config get
    fandom.py config set timezone=America/Sao_Paulo digest_time=08:30 language=pt-BR

`teams list` and `config set` answer `onboarding_missing` — any key there
means the first-contact conversation is unfinished; start it (after the
first follow, never before). In your replies, call it the resumo da manhã
(or morning roundup), never "digest" — that is the command's name, not a
word for people.
