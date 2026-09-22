#!/usr/bin/env python3
"""fandom.py -- the Fandom engine's CLI. Every command answers one JSON object.

Commands:
    teams list                                  followed subjects, compact
    teams add <name> --sport S [--aliases ...] [--feed URL]
    teams remove <key>
    search_team <name>                          TheSportsDB candidates
    news [--limit N]                            fetch feeds, filter, cache
    matchday [key ...]                          fixtures and results
    odds show [key ...]                         the board, folded into the cache
    odds link <key> --sport-key K (--name N | --league)
    odds sports [--sport S]                     what the board carries, free
    digest                                      the roundup payload (fires 3x/day by default)
    schedule                                    the cron specs to register
    config get | config set KEY=VALUE ...

Exit 0 on success, 2 on failure with an `error` field. stdout is data only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from kit import clock  # noqa: E402

from fandom import config as fandom_config  # noqa: E402
from fandom import store as store_module  # noqa: E402
from fandom.engine import digest, matchday  # noqa: E402
from fandom.engine import odds as odds_engine  # noqa: E402
from fandom.engine import odds_match, odds_store  # noqa: E402
from fandom.engine import schedule as schedule_engine  # noqa: E402
from fandom.models import _SPORT_ALIASES, Sport, Team  # noqa: E402
from fandom import sources as sources_module  # noqa: E402
from fandom.sources import odds as odds_source  # noqa: E402
from fandom.sources import thesportsdb  # noqa: E402
from fandom.sources.base import SourceError, SourceOutcome  # noqa: E402
from fandom.store import FandomStore  # noqa: E402

HOME = os.environ.get("FANDOM_HOME", "/var/lib/hermes/fandom")


def emit(payload: object, code: int = 0) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return code


def fail(message: str) -> int:
    return emit({"error": message}, 2)


def cmd_teams(args: argparse.Namespace) -> int:
    store = FandomStore(HOME)
    if args.action == "list":
        store.seed_defaults()
        return emit({
            "teams": [store.compact_view(team) for team in store.all()],
            "onboarding_missing": fandom_config.missing_keys(HOME),
        })
    if args.action == "remove":
        try:
            removed = store.remove(args.key)
        except KeyError as error:
            return fail(str(error))
        store.save()
        return emit({"removed": store.compact_view(removed)})

    # add
    name = " ".join(args.name)
    if not name:
        return fail("team name is required")
    try:
        sport = Sport.parse(args.sport)
    except ValueError:
        names = sorted(s.value for s in Sport) + sorted(_SPORT_ALIASES)
        return fail(f"unknown sport {args.sport!r} -- one of {names}")
    team = Team(
        key=store_module.team_key_for(name),
        name=name, sport=sport,
        aliases=list(args.aliases),
        feeds=list(args.feed),
        source_id=args.source_id,
    )
    store.add(team)
    store.save()
    return emit({"added": store.compact_view(team)})


def _sweep(teams, settings):
    """The whole followed set's news, read once per distinct URL.

    Returns (items, failed, outcomes). `failed` keeps the shape the skills
    already read; `outcomes` carries one entry per source, answered or not,
    which is what lets a caller count sources instead of guessing from items.
    """
    plan = sources_module.sweep_plan(teams, language=str(settings["language"]))
    items, outcomes = sources_module.sweep(plan)
    return items, sources_module.failures(outcomes), outcomes


def _sports_planned(teams, settings) -> dict[str, list[str]]:
    """Which URLs stand behind each followed sport, for the coverage check."""
    planned: dict[str, list[str]] = {}
    for team in teams:
        urls = sources_module.urls_for(team, language=str(settings["language"]))
        planned.setdefault(str(team.sport), []).extend(urls)
    return planned


def _record_health(store, outcomes, teams, settings, *, announce: bool = False):
    """Fold this run into the health file and return the payload's `sources` block.

    Only the digest passes announce=True: an ad-hoc `news` must not burn the
    weekly announcement for a source the morning message has yet to mention.
    """
    from fandom.engine import source_health
    health = source_health.record(store.health, outcomes)
    block = source_health.report(health, outcomes,
                                 sports_planned=_sports_planned(teams, settings))
    if announce:
        announced = [entry["url"] for entry in block["down"] if entry.get("announce")]
        if announced:
            health = source_health.mark_announced(health, announced)
    health = source_health.prune(health, [outcome.url for outcome in outcomes])
    store.save_health(health)
    return block


def cmd_search_team(args: argparse.Namespace) -> int:
    try:
        candidates = thesportsdb.search_team(" ".join(args.words))
    except Exception as error:
        return fail(f"team search failed: {error}")
    return emit({"query": " ".join(args.words), "results": candidates})


def cmd_news(args: argparse.Namespace) -> int:
    store = FandomStore(HOME)
    store.seed_defaults()  # the BR seed, once, into an empty store
    teams = store.all()
    settings = fandom_config.load(HOME)
    items, failed, outcomes = _sweep(teams, settings)
    buckets = _filter(items, teams)
    cache = []
    for bucket in buckets.values():
        cache.extend(item.as_dict() for item in bucket)
    store.save_news(cache)
    health_block = _record_health(store, outcomes, teams, settings)
    return emit({
        "at": clock.iso(),
        "teams": {key: [item.as_dict() for item in bucket[:args.limit]]
                  for key, bucket in buckets.items()},
        "failed_sources": failed,
        "sources_read": sum(1 for outcome in outcomes if outcome.ok),
        "items_read": len(items),
        "sources": health_block,
    })


def _filter(items, teams):
    from fandom.engine import news_filter
    return news_filter.filter_news(items, teams)


def cmd_matchday(args: argparse.Namespace) -> int:
    store = FandomStore(HOME)
    teams = [store.get(key) for key in args.keys] if args.keys else store.all()
    return emit(matchday.build_all(teams))


def cmd_live(args: argparse.Namespace) -> int:
    """'o que está rolando agora': fixtures quando há provedor, headlines
    'Ao vivo' quando não há -- e nunca um placar que ninguém confirmou."""
    store = FandomStore(HOME)
    store.seed_defaults()
    teams = store.all()
    settings = fandom_config.load(HOME)
    items, failed, _outcomes = _sweep(teams, settings)
    from fandom.engine import live
    payload = {
        "at": clock.iso(),
        "live_headlines": [item.as_dict() for item in live.pick_live(items)[:8]],
        "fixtures": [matchday.build(team) for team in teams if team.source_id],
        "failed_sources": sorted(set(failed)),
    }
    return emit(payload)


def cmd_digest(args: argparse.Namespace) -> int:
    """Fetch + filter + build in one command -- what the digest cron runs,
    by default three times a day (manhã, tarde, noite)."""
    store = FandomStore(HOME)
    store.seed_defaults()
    teams = store.all()
    settings = fandom_config.load(HOME)
    items, failed, outcomes = _sweep(teams, settings)
    health_block = _record_health(store, outcomes, teams, settings, announce=True)
    odds_block = odds_store.upcoming(store.odds, teams, now=clock.now())
    payload = digest.build(teams, items, failed,
                           per_team_limit=int(settings["news_limit_per_team"]),
                           sources=health_block, odds=odds_block)
    payload["timezone"] = settings["timezone"]
    return emit(payload)


# A fixture three days out is still "o próximo jogo" to someone asking. The
# digest's horizon is shorter because it speaks unprompted.
ODDS_SHOW_HORIZON_H = 72

# Which board group stands behind each sport we follow. Esports is absent
# because this board carries none, and that absence is the answer the linking
# flow gives instead of an empty list with no explanation.
ODDS_GROUPS = {
    Sport.FUTEBOL: "Soccer",
    Sport.BASQUETE: "Basketball",
    Sport.FUTEBOL_AMERICANO: "American Football",
}


def _read_board(data, teams, sport_keys, *, at, method):
    """Spend, fold, and report -- never raise.

    A provider failure is a SourceOutcome like any other: the precedent is
    `sources.read_source`, and a command that dies because a board was busy
    is a command that tells a user nothing.
    """
    outcomes, spend = [], []
    for sport_key in sport_keys:
        estimate = odds_source.plan_cost()
        try:
            url = odds_source.safe_url(f"{odds_source.SPORTS_PATH}/{sport_key}/odds",
                                       {"regions": odds_source.DEFAULT_REGIONS,
                                        "markets": odds_source.DEFAULT_MARKETS})
        except SourceError:
            spend.append({"sport_key": sport_key, "reason": "unconfigured", "cost": 0})
            continue
        allowed, reason = odds_store.may_spend(data, estimate, now=clock.now())
        if not allowed:
            spend.append({"sport_key": sport_key, "reason": reason, "cost": 0})
            continue
        label = f"odds:{sport_key}"
        try:
            events, answer = odds_source.fetch_odds(sport_key)
        except Exception as error:      # SourceError, OddsQuota, HttpError alike
            outcomes.append(SourceOutcome(url=url, label=label, ok=False, error=str(error)))
            spend.append({"sport_key": sport_key, "reason": "error", "cost": 0})
            continue
        # The header is the receipt; the estimate was only ever for the gate.
        charged = answer.cost if answer.cost is not None else estimate
        data = odds_store.charge(data, at=at, cost=charged, sport_key=sport_key,
                                 remaining=answer.remaining)
        snapshots = [
            odds_engine.build_snapshot(event, at=at, method=method)
            for event in events
            if any(odds_match.owns(team, event.sport_key, event.home_team, event.away_team)
                   for team in teams)
        ]
        data = odds_store.append(data, snapshots)
        outcomes.append(SourceOutcome(url=url, label=label, ok=True))
        spend.append({"sport_key": sport_key, "reason": "ok", "cost": charged,
                      "events": len(snapshots)})
    return data, outcomes, spend


def cmd_odds(args: argparse.Namespace) -> int:
    """The board for the followed set, folded into the cache and served with its age.

    Exit 0 even when nothing could be read: a spent quota is not a broken
    command, and the cached line with `age_minutes` on it is still an answer.
    """
    store = FandomStore(HOME)
    store.seed_defaults()
    try:
        teams = [store.get(key) for key in args.keys] if args.keys else store.all()
    except KeyError as error:
        return fail(str(error))
    settings = fandom_config.load(HOME)
    now = clock.now()
    stamp = clock.iso(now)
    data = store.odds
    # A machine word, not a sentence: the SKILL.md decides how to say "esse
    # assunto ainda nao tem quadro".
    unlinked = [{"key": team.key, "reason": "unlinked"}
                for team in teams if not team.odds_sport]
    wanted = sorted({team.odds_sport for team in teams if team.odds_sport})
    outcomes, spend = [], []
    if wanted and not args.no_spend:
        data, outcomes, spend = _read_board(data, teams, wanted, at=stamp, method=args.method)
    data = odds_store.prune(data, now=now)
    store.save_odds(data)
    block = odds_store.upcoming(data, teams, now=now, horizon_h=ODDS_SHOW_HORIZON_H,
                                include_stale=True)
    payload = {
        "at": stamp,
        "method": args.method,
        "events": block["events"],
        "unlinked": unlinked,
        "spend": spend,
        "budget": odds_store.spent(data, now=now),
    }
    if outcomes:
        payload["sources"] = _record_health(store, outcomes, teams, settings)
    return emit(payload)


def cmd_odds_link(args: argparse.Namespace) -> int:
    """Name the board entry for a subject. Costs nothing in any of its modes.

    Without --sport-key it lists the competitions this subject could belong
    to; with one it ranks the board's spellings; with --name or --league it
    commits. Nothing is ever matched by resemblance at read time, so this
    conversation is the only place a link is made.
    """
    store = FandomStore(HOME)
    store.seed_defaults()
    try:
        team = store.get(args.key)
    except KeyError as error:
        return fail(str(error))

    if not args.sport_key:
        group = ODDS_GROUPS.get(team.sport)
        if group is None:
            return emit({"team": team.key, "sports": [], "reason": "sport_not_covered"})
        try:
            sports, _answer = odds_source.list_sports()
        except Exception as error:
            return fail(f"odds: {error}")
        return emit({"team": team.key, "reason": "ok", "cost": 0,
                     "sports": [sport for sport in sports
                                if sport.get("group") == group and sport.get("active")]})

    try:
        events, _answer = odds_source.list_events(args.sport_key)
    except Exception as error:
        return fail(f"odds: {error}")

    if args.league:
        team.odds_sport, team.odds_key = args.sport_key, None
        store.save()
        return emit({"linked": store.compact_view(team), "scope": "league",
                     "sport_key": args.sport_key, "fixtures": len(events)})

    if args.name:
        spelled = {event.home_team for event in events} | {event.away_team for event in events}
        if args.name not in spelled:
            # Exact, deliberately: a near match here is the wrong club, and the
            # candidate list exists so nobody has to type from memory.
            return fail(f"no team spelled {args.name!r} on {args.sport_key}")
        team.odds_sport, team.odds_key = args.sport_key, args.name
        store.save()
        return emit({"linked": store.compact_view(team), "scope": "team",
                     "sport_key": args.sport_key, "name": args.name})

    from dataclasses import replace
    probe = replace(team, odds_sport=args.sport_key)
    return emit({"team": team.key, "sport_key": args.sport_key, "cost": 0,
                 "candidates": odds_match.candidates(events, probe),
                 "fixtures": len(events)})


def cmd_odds_sports(args: argparse.Namespace) -> int:
    """What the board carries, in season or not. Free."""
    try:
        sports, _answer = odds_source.list_sports()
    except Exception as error:
        return fail(f"odds: {error}")
    if args.group:
        sports = [sport for sport in sports if sport.get("group") == args.group]
    return emit({"sports": sports, "cost": 0})


def cmd_schedule(args: argparse.Namespace) -> int:
    """The schedules this agent should have, in the zone the container runs in.

    `hermes cron create` has no per-job zone, so a job fires in the container's
    TZ -- written once, at boot, from a config the user had not filled in yet.
    Waiting for a restart to fix that is what left this agent five days in
    production with no schedule at all. This converts instead: the same
    instant, named in the zone that will actually be used.
    """
    settings = fandom_config.load(HOME)
    return emit(schedule_engine.plan(settings, container_tz=os.environ.get("TZ")))


def cmd_config(args: argparse.Namespace) -> int:
    if args.action == "get":
        return emit(fandom_config.load(HOME))
    current = fandom_config.load(HOME)
    for pair in args.pairs:
        key, _, raw = pair.partition("=")
        if key not in fandom_config.DEFAULTS:
            return fail(f"unknown config key {key!r}")
        if key == "digest_enabled":
            current[key] = raw.strip().lower() in ("1", "true", "yes", "on")
        elif key == "digest_times":
            current[key] = [part.strip() for part in raw.split(",") if part.strip()]
        else:
            current[key] = raw.strip()
    fandom_config.save(HOME, current)
    return emit({"saved": current, "onboarding_missing": fandom_config.missing_keys(HOME)})


def main() -> int:
    parser = argparse.ArgumentParser(prog="fandom", description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest="command", required=True)

    it = verbs.add_parser("teams")
    sub = it.add_subparsers(dest="action", required=True)
    sub.add_parser("list").set_defaults(run=lambda a: cmd_teams(a), action="list")
    it_add = sub.add_parser("add")
    it_add.add_argument("name", nargs="+")
    it_add.add_argument("--sport", default="futebol")
    it_add.add_argument("--aliases", nargs="*", default=[])
    it_add.add_argument("--feed", action="append", default=[])
    it_add.add_argument("--source-id", default=None)
    it_add.set_defaults(run=lambda a: cmd_teams(a), action="add")
    it_rm = sub.add_parser("remove")
    it_rm.add_argument("key")
    it_rm.set_defaults(run=lambda a: cmd_teams(a), action="remove")

    it = verbs.add_parser("search_team")
    it.add_argument("words", nargs="+")
    it.set_defaults(run=cmd_search_team)

    it = verbs.add_parser("news")
    it.add_argument("--limit", type=int, default=5)
    it.set_defaults(run=cmd_news)

    it = verbs.add_parser("matchday")
    it.add_argument("keys", nargs="*")
    it.set_defaults(run=cmd_matchday)

    verbs.add_parser("live").set_defaults(run=cmd_live)

    # `odds` takes subverbs rather than a bare key list: a positional nargs="*"
    # next to subparsers is ambiguous to argparse, and the gymnastics to make
    # it work would cost more than the two extra characters of "show".
    it = verbs.add_parser("odds")
    sub = it.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show")
    show.add_argument("keys", nargs="*")
    show.add_argument("--method", choices=list(odds_engine.METHODS),
                      default=odds_engine.DEFAULT_METHOD)
    show.add_argument("--no-spend", action="store_true")
    show.set_defaults(run=cmd_odds)
    link = sub.add_parser("link")
    link.add_argument("key")
    link.add_argument("--sport-key", default=None)
    link.add_argument("--name", default=None)
    link.add_argument("--league", action="store_true")
    link.set_defaults(run=cmd_odds_link)
    sports = sub.add_parser("sports")
    sports.add_argument("--group", default=None)
    sports.set_defaults(run=cmd_odds_sports)

    verbs.add_parser("digest").set_defaults(run=cmd_digest)

    verbs.add_parser("schedule").set_defaults(run=cmd_schedule)

    it = verbs.add_parser("config")
    it.add_argument("action", choices=["get", "set"])
    it.add_argument("pairs", nargs="*")
    it.set_defaults(run=cmd_config)

    args = parser.parse_args()
    try:
        return args.run(args)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
