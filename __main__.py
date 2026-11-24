"""Command line: python -m globalwatch collect | brief | site"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import build_site as site_mod
from . import collect as collect_mod
from .cluster import cluster, select_stories
from .summarize import make_gemini_generator, summarize_stories

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("globalwatch")


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def cmd_collect(args) -> int:
    sources = collect_mod.load_sources(ROOT / "sources.yaml")
    items, errors = collect_mod.collect(sources)
    day = args.day or datetime.now(timezone.utc).date().isoformat()
    path = collect_mod.save_day(items, errors, ROOT / "data" / "raw", day)
    print(f"{len(items)} items, {len(errors)} feed errors -> {path}")
    for e in errors:
        print(f"  FEED ERROR {e['source']}: {e['error']}")
    # Fail only if almost every feed is broken, so the Action shows a real problem.
    return 1 if sources and len(errors) > 0.8 * len(sources) else 0


def _load_window(end: date, days: int) -> list[dict]:
    items: list[dict] = []
    for offset in range(days):
        path = ROOT / "data" / "raw" / f"{(end - timedelta(days=offset)).isoformat()}.json"
        if path.exists():
            items.extend(json.loads(path.read_text(encoding="utf-8"))["items"])
    return collect_mod.dedupe(items)


def cmd_brief(args) -> int:
    cfg = load_config()
    end = date.fromisoformat(args.end_date) if args.end_date else datetime.now(timezone.utc).date()
    items = _load_window(end, cfg["window_days"])
    if not items:
        print("No collected items in the window: run `collect` first.")
        return 1
    stories = select_stories(
        cluster(items, cfg["cluster_threshold"]),
        max_stories=cfg["max_stories"],
        min_regions=cfg["min_regions"],
        max_items=cfg["max_items_per_story"],
    )
    print(f"{len(items)} items -> {len(stories)} stories")
    generate = make_gemini_generator(os.environ.get("GEMINI_MODEL") or cfg["model"])
    results, errors = summarize_stories(stories, generate, cfg["pause_seconds"])
    if not results:
        print("No story could be summarized.")
        return 1
    iso = end.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    brief = {
        "week": week,
        "period_start": (end - timedelta(days=cfg["window_days"] - 1)).isoformat(),
        "period_end": end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": os.environ.get("GEMINI_MODEL") or cfg["model"],
        "items_analyzed": len(items),
        "stories": results,
        "errors": errors,
    }
    out = ROOT / "data" / "briefs"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{week}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Brief {week}: {len(results)} stories, {len(errors)} errors")
    return 0


def cmd_site(args) -> int:
    pages = site_mod.build_site()
    print(f"{len(pages)} pages written to docs/")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="globalwatch")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("collect", help="fetch all feeds into data/raw/")
    p.add_argument("--day", help="YYYY-MM-DD (default: today, UTC)")
    p.set_defaults(func=cmd_collect)
    p = sub.add_parser("brief", help="cluster the last week and summarize with Gemini")
    p.add_argument("--end-date", help="YYYY-MM-DD (default: today, UTC)")
    p.set_defaults(func=cmd_brief)
    p = sub.add_parser("site", help="render docs/ from data/briefs/")
    p.set_defaults(func=cmd_site)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
