#!/usr/bin/env python3
"""fandom.py -- the Fandom engine's CLI. Every command answers one JSON object.

Commands:
    teams list                                  followed subjects, compact
    teams add <name> --sport S [--aliases ...] [--feed URL]
    teams remove <key>
    search_team <name>                          TheSportsDB candidates
    news [--limit N]                            fetch feeds, filter, cache
    matchday [key ...]                          fixtures and results
    digest                                      the morning payload
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
from fandom.models import _SPORT_ALIASES, Sport, Team  # noqa: E402
from fandom import sources as sources_module  # noqa: E402
from fandom.sources import thesportsdb  # noqa: E402
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
    """Fetch + filter + build in one command -- what the digest cron runs."""
    store = FandomStore(HOME)
    store.seed_defaults()
    teams = store.all()
    settings = fandom_config.load(HOME)
    items, failed, outcomes = _sweep(teams, settings)
    health_block = _record_health(store, outcomes, teams, settings, announce=True)
    payload = digest.build(teams, items, failed,
                           per_team_limit=int(settings["news_limit_per_team"]),
                           sources=health_block)
    payload["timezone"] = settings["timezone"]
    return emit(payload)


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

    verbs.add_parser("digest").set_defaults(run=cmd_digest)

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
