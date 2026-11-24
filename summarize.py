"""Summarize each story with Gemini, with citations attached by code (not by the model)."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable

log = logging.getLogger("globalwatch.summarize")

REGION_LABELS = {
    "global": "Global / multilateral",
    "asia_pacific": "Asia-Pacific",
    "mena": "Middle East & North Africa",
    "africa": "Africa",
    "europe_eurasia": "Europe & Eurasia",
    "americas": "Americas",
}

PROMPT = """You write a neutral, factual world-affairs brief for a general audience.

Below are {n} headlines (with short snippets) about ONE story, from outlets in different regions.
Each line looks like: [index] Outlet (region, ownership) - headline - snippet.

STRICT RULES
- Use ONLY information present in these lines. Do not add facts, numbers, names or context from memory.
- If the lines disagree or are unclear, say so instead of choosing a side.
- Neutral tone. No opinions, no adjectives of judgment.
- "framing": describe in one sentence how outlets from a region present the story (angle, emphasis, wording).
  Only include regions that appear in the lines. Cite the line indices you relied on.
- Every key fact must cite at least one line index.

Return JSON only, with exactly this shape:
{{
  "headline": "max 12 words",
  "summary": "max 70 words",
  "key_facts": [{{"fact": "...", "items": [0, 2]}}],
  "framing": [{{"region": "<region key from the lines>", "description": "...", "items": [1]}}],
  "confidence": "high" | "medium" | "low"
}}

LINES
{lines}
"""


def build_prompt(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items):
        snippet = f" - {item['snippet']}" if item.get("snippet") else ""
        lines.append(
            f"[{i}] {item['source']} ({item['region']}, {item['ownership']}) - {item['title']}{snippet}"
        )
    return PROMPT.format(n=len(items), lines="\n".join(lines))


def validate(raw: str, items: list[dict]) -> dict:
    """Parse and check the model output. Drops uncited or unknown entries; raises if unusable."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    headline = str(data.get("headline", "")).strip()
    summary = str(data.get("summary", "")).strip()
    if not headline or not summary:
        raise ValueError("missing headline or summary")

    n = len(items)
    allowed_regions = {i["region"] for i in items}

    def valid_indices(values) -> list[int]:
        if not isinstance(values, list):
            return []
        return sorted({v for v in values if isinstance(v, int) and 0 <= v < n})

    facts = []
    for f in data.get("key_facts", []) or []:
        idx = valid_indices(f.get("items"))
        text = str(f.get("fact", "")).strip()
        if text and idx:
            facts.append({"fact": text, "items": idx})
    if not facts:
        raise ValueError("no key fact with a valid citation")

    framing = []
    for fr in data.get("framing", []) or []:
        region = fr.get("region")
        idx = valid_indices(fr.get("items"))
        text = str(fr.get("description", "")).strip()
        if region in allowed_regions and text and idx:
            framing.append({"region": region, "description": text, "items": idx})

    confidence = data.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    return {
        "headline": headline,
        "summary": summary,
        "key_facts": facts,
        "framing": framing,
        "confidence": confidence,
    }


def attach_sources(story: dict, items: list[dict]) -> dict:
    """Replace line indices with real links and outlet names taken from the input items."""

    def link(i: int) -> dict:
        it = items[i]
        return {"outlet": it["source"], "title": it["title"], "url": it["link"], "region": it["region"]}

    return {
        "headline": story["headline"],
        "summary": story["summary"],
        "confidence": story["confidence"],
        "key_facts": [
            {"fact": f["fact"], "sources": [link(i) for i in f["items"]]} for f in story["key_facts"]
        ],
        "framing": [
            {
                "region": fr["region"],
                "region_label": REGION_LABELS.get(fr["region"], fr["region"]),
                "description": fr["description"],
                "sources": [link(i) for i in fr["items"]],
            }
            for fr in story["framing"]
        ],
        "regions": sorted({it["region"] for it in items}),
        "outlets": sorted({it["source"] for it in items}),
        "all_links": [link(i) for i in range(len(items))],
    }


def make_gemini_generator(model: str | None = None, retries: int = 3) -> Callable[[str], str]:
    """Return a function prompt -> JSON text, using the Gemini API (key from GEMINI_API_KEY)."""
    from google import genai  # imported lazily so tests do not need the SDK configured
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    client = genai.Client(api_key=api_key)
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)

    def generate(prompt: str) -> str:
        delay = 10
        for attempt in range(1, retries + 1):
            try:
                response = client.models.generate_content(model=model_name, contents=prompt, config=config)
                return response.text
            except Exception as exc:  # noqa: BLE001 - retry on rate limits / transient errors
                if attempt == retries:
                    raise
                log.warning("Gemini call failed (%s), retrying in %ss", exc, delay)
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    return generate


def summarize_stories(
    stories: list[dict],
    generate: Callable[[str], str],
    pause_seconds: float = 0.0,
) -> tuple[list[dict], list[dict]]:
    """Summarize each story. A failed story is skipped and reported, never fatal."""
    results, errors = [], []
    for n, story in enumerate(stories):
        items = story["items"]
        try:
            raw = generate(build_prompt(items))
            results.append(attach_sources(validate(raw, items), items))
        except Exception as exc:  # noqa: BLE001
            log.warning("story %s failed: %s", story["id"], exc)
            errors.append({"story": story["id"], "error": str(exc)[:200]})
        if pause_seconds and n < len(stories) - 1:
            time.sleep(pause_seconds)
    return results, errors
