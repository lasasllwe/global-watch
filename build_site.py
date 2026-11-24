"""Render the static website (docs/) from data/briefs/*.json."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .summarize import REGION_LABELS

ROOT = Path(__file__).resolve().parents[2]


def load_briefs(briefs_dir: Path) -> list[dict]:
    briefs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(briefs_dir.glob("*.json"))]
    return sorted(briefs, key=lambda b: b["week"], reverse=True)


def build_site(
    briefs_dir: Path = ROOT / "data" / "briefs",
    sources_file: Path = ROOT / "sources.yaml",
    out_dir: Path = ROOT / "docs",
    templates_dir: Path = ROOT / "templates",
) -> list[Path]:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    briefs = load_briefs(briefs_dir)
    sources = yaml.safe_load(sources_file.read_text(encoding="utf-8"))["sources"]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "briefs").mkdir(exist_ok=True)
    written: list[Path] = []

    css_src = templates_dir / "style.css"
    if css_src.exists():
        shutil.copy(css_src, out_dir / "style.css")

    ctx = {"region_labels": REGION_LABELS, "root": "."}
    page = out_dir / "index.html"
    page.write_text(env.get_template("index.html").render(briefs=briefs, **ctx), encoding="utf-8")
    written.append(page)

    for brief in briefs:
        page = out_dir / "briefs" / f"{brief['week']}.html"
        page.write_text(
            env.get_template("brief.html").render(brief=brief, **{**ctx, "root": ".."}),
            encoding="utf-8",
        )
        written.append(page)

    page = out_dir / "methodology.html"
    page.write_text(
        env.get_template("methodology.html").render(sources=sources, **ctx), encoding="utf-8"
    )
    written.append(page)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return written
