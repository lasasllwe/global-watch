# Global Watch

An automated, AI-assisted watch on world affairs. Every day a pipeline collects public headlines from outlets on every continent; every week it groups them into stories, summarizes each one with Google Gemini, and shows **how different regions frame the same event**. The result is a static website on GitHub Pages, built entirely by GitHub Actions.

**Live site:** https://lasasllwe.github.io/global-watch/ (once Pages is enabled)

## How it works

```
RSS feeds (6 regions) ──daily──▶ collect ──▶ data/raw/YYYY-MM-DD.json
                                     │ weekly
                                     ▼
              cluster (headline similarity, ≥2 regions per story)
                                     ▼
              summarize (Gemini, JSON output, validated, citations attached by code)
                                     ▼
              data/briefs/YYYY-Www.json ──▶ build site ──▶ docs/ ──▶ GitHub Pages
```

Design choices that matter:

- **Balance by construction.** A story is kept only if at least two regions cover it, and headlines are picked round-robin across regions.
- **Citations are not trusted to the model.** Gemini returns line indices; the code maps them to real URLs and discards any fact without a valid citation.
- **Transparent sources.** Every outlet is labeled by region and ownership (independent, private, public, NGO, state-funded) on the Method page. State-funded outlets are off by default.
- **Resilient.** A broken feed or a failed Gemini call is logged and skipped, never fatal.
- **Light on content.** Only headlines, ~280-character snippets and links are stored; no full articles are copied.

## Quick start

```bash
pip install -r requirements.txt
export PYTHONPATH=src
python -m globalwatch collect                 # fetch feeds into data/raw/
export GEMINI_API_KEY=...                     # from Google AI Studio
python -m globalwatch brief                   # cluster + summarize the last 7 days
python -m globalwatch site                    # render docs/
python -m pytest -q                           # tests (no network, no API key needed)
```

## Configuration

- `sources.yaml`: feeds, with region and ownership labels.
- `config.yaml`: Gemini model name (check the current free-tier model in AI Studio; override with `GEMINI_MODEL`), clustering threshold, number of stories, pause between API calls.
- GitHub secret `GEMINI_API_KEY`: never commit the key.

## Automation

| Workflow | When | What |
| --- | --- | --- |
| `daily-collect.yml` | every day, 06:00 Singapore | collects feeds and commits `data/raw/` |
| `weekly-brief.yml` | Sunday 18:00 Singapore | tests, Gemini brief, site build, opens a Pull Request for human review |
| `pages.yml` | on changes to `docs/` | deploys the site to GitHub Pages |

## Limits and roadmap

- Summaries are AI-generated from headlines and snippets, so they can be incomplete or wrong; the site says so and links every source.
- Clustering uses headline token overlap. Next: Gemini embeddings for better grouping across languages.
- Next: non-English sources (FR/ES/PT/AR) with translated headlines, an evaluation rubric, an RSS feed of the brief.

## License

MIT
