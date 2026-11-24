"""Collect headlines from RSS feeds (titles, short snippets and links only)."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import feedparser
import requests
import yaml

log = logging.getLogger("globalwatch.collect")

USER_AGENT = "global-watch/0.1 (+https://github.com/lasasllwe/global-watch)"
MAX_SNIPPET_CHARS = 280
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def load_sources(path: str | Path) -> list[dict]:
    """Load the list of feeds from sources.yaml (only enabled ones)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [s for s in data["sources"] if s.get("enabled", True)]


def fetch(url: str, timeout: int = 20) -> bytes:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.content


def clean(text: str | None) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not text:
        return ""
    text = TAG_RE.sub(" ", html.unescape(text))
    return WS_RE.sub(" ", text).strip()


def _entry_date(entry) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def parse_feed(content: bytes, source: dict, limit: int = 40) -> list[dict]:
    """Turn raw feed bytes into normalized items."""
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries[:limit]:
        title = clean(entry.get("title"))
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        snippet = clean(entry.get("summary"))[:MAX_SNIPPET_CHARS]
        items.append(
            {
                "id": hashlib.sha1(link.encode("utf-8")).hexdigest()[:12],
                "title": title,
                "link": link,
                "published": _entry_date(entry),
                "snippet": snippet,
                "source": source["name"],
                "region": source["region"],
                "ownership": source.get("ownership", "unknown"),
            }
        )
    return items


def dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for item in items:
        if item["link"] in seen:
            continue
        seen.add(item["link"])
        unique.append(item)
    return unique


def collect(
    sources: list[dict],
    fetcher: Callable[[str], bytes] = fetch,
    limit_per_feed: int = 40,
) -> tuple[list[dict], list[dict]]:
    """Fetch every feed. A failing feed never stops the run: it is recorded as an error."""
    items: list[dict] = []
    errors: list[dict] = []
    for source in sources:
        try:
            content = fetcher(source["url"])
            parsed = parse_feed(content, source, limit_per_feed)
            if not parsed:
                raise ValueError("feed returned no usable entries")
            items.extend(parsed)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not break the run
            log.warning("feed failed: %s (%s)", source["name"], exc)
            errors.append({"source": source["name"], "url": source["url"], "error": str(exc)[:200]})
    return dedupe(items), errors


def save_day(items: list[dict], errors: list[dict], out_dir: str | Path, day: str) -> Path:
    """Write data/raw/YYYY-MM-DD.json, merging with an existing file for that day."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    existing: list[dict] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8")).get("items", [])
    merged = dedupe(existing + items)
    payload = {"day": day, "items": merged, "errors": errors}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
