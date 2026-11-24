import json

import pytest

from globalwatch import build_site, cluster, collect, summarize

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Talks open in Geneva over trade tariffs</title><link>https://a.example/1</link>
<description>&lt;p&gt;Delegates met &lt;b&gt;today&lt;/b&gt;.&lt;/p&gt;</description>
<pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>No link item</title></item>
</channel></rss>"""

SRC = {"name": "Test Wire", "url": "http://x", "region": "global", "ownership": "public"}


def make_item(i, title, region, source=None):
    return {
        "id": str(i), "title": title, "link": f"https://e.example/{i}",
        "published": f"2026-11-2{i % 9}T00:00:00+00:00", "snippet": "",
        "source": source or f"Outlet{i}", "region": region, "ownership": "private",
    }


def test_parse_feed_cleans_html_and_skips_invalid_entries():
    items = collect.parse_feed(RSS, SRC)
    assert len(items) == 1
    assert items[0]["title"].startswith("Talks open in Geneva")
    assert items[0]["snippet"] == "Delegates met today ."
    assert items[0]["region"] == "global"


def test_collect_survives_a_failing_feed_and_dedupes():
    def fetcher(url):
        if url == "bad":
            raise OSError("boom")
        return RSS

    sources = [SRC, {**SRC, "name": "Bad", "url": "bad"}, {**SRC, "name": "Dup"}]
    items, errors = collect.collect(sources, fetcher=fetcher)
    assert len(items) == 1  # same link from two feeds is kept once
    assert [e["source"] for e in errors] == ["Bad"]


def test_save_day_merges(tmp_path):
    a = collect.parse_feed(RSS, SRC)
    collect.save_day(a, [], tmp_path, "2026-11-23")
    collect.save_day(a, [], tmp_path, "2026-11-23")
    data = json.loads((tmp_path / "2026-11-23.json").read_text())
    assert len(data["items"]) == 1


def test_cluster_groups_same_event_across_regions_and_balances():
    items = [
        make_item(1, "Earthquake strikes northern Japan, tsunami warning issued", "asia_pacific"),
        make_item(2, "Japan earthquake: tsunami warning issued after northern quake", "global"),
        make_item(3, "Earthquake in northern Japan triggers tsunami warning", "americas"),
        make_item(4, "Parliament passes budget after long debate", "europe_eurasia"),
    ]
    clusters = cluster.cluster(items)
    big = max(clusters, key=lambda c: len(c["items"]))
    assert len(big["items"]) == 3
    assert set(big["regions"]) == {"asia_pacific", "global", "americas"}
    stories = cluster.select_stories(clusters, min_regions=2)
    assert len(stories) == 1  # the single-region story is dropped


def test_balanced_items_round_robin():
    items = [make_item(i, f"t{i}", "global") for i in range(5)] + [make_item(9, "x", "africa")]
    picked = cluster._balanced_items(items, 3)
    assert {i["region"] for i in picked} == {"global", "africa"}


def good_output():
    return json.dumps({
        "headline": "Quake hits Japan",
        "summary": "A strong earthquake struck northern Japan.",
        "key_facts": [{"fact": "A tsunami warning was issued.", "items": [0, 1, 99]}, {"fact": "Uncited", "items": []}],
        "framing": [
            {"region": "asia_pacific", "description": "Focus on local safety.", "items": [0]},
            {"region": "mars", "description": "Invalid region.", "items": [0]},
        ],
        "confidence": "high",
    })


def test_validate_drops_invalid_citations_and_regions():
    items = [make_item(1, "a", "asia_pacific"), make_item(2, "b", "global")]
    out = summarize.validate(good_output(), items)
    assert out["key_facts"] == [{"fact": "A tsunami warning was issued.", "items": [0, 1]}]
    assert [f["region"] for f in out["framing"]] == ["asia_pacific"]


@pytest.mark.parametrize("raw", ["not json", "[]", json.dumps({"headline": "h", "summary": "s", "key_facts": []})])
def test_validate_rejects_unusable_output(raw):
    with pytest.raises(Exception):
        summarize.validate(raw, [make_item(1, "a", "global")])


def test_summarize_stories_attaches_real_links_and_survives_errors():
    items = [make_item(1, "a", "asia_pacific"), make_item(2, "b", "global")]
    stories = [{"id": 0, "items": items}, {"id": 1, "items": items}]
    calls = {"n": 0}

    def fake_generate(prompt):
        calls["n"] += 1
        assert "[0]" in prompt and "ONE story" in prompt
        if calls["n"] == 2:
            raise RuntimeError("rate limited")
        return good_output()

    results, errors = summarize.summarize_stories(stories, fake_generate)
    assert len(results) == 1 and len(errors) == 1
    urls = {s["url"] for s in results[0]["key_facts"][0]["sources"]}
    assert urls == {"https://e.example/1", "https://e.example/2"}  # links come from input, not from the model


def test_build_site_renders_and_escapes(tmp_path):
    briefs = tmp_path / "briefs"
    briefs.mkdir()
    items = [make_item(1, "<script>x</script>", "asia_pacific"), make_item(2, "b", "global")]
    story = summarize.attach_sources(summarize.validate(good_output(), items), items)
    story["headline"] = "<b>Injected</b>"
    brief = {"week": "2026-W48", "period_start": "2026-11-22", "period_end": "2026-11-28",
             "items_analyzed": 2, "model": "m", "stories": [story]}
    (briefs / "2026-W48.json").write_text(json.dumps(brief))
    out = tmp_path / "docs"
    root = build_site.ROOT
    pages = build_site.build_site(briefs, root / "sources.yaml", out, root / "templates")
    html = (out / "briefs" / "2026-W48.html").read_text()
    assert "&lt;b&gt;Injected&lt;/b&gt;" in html and "<b>Injected</b>" not in html
    assert (out / "index.html").exists() and (out / "methodology.html").exists()
    assert "2026-W48" in (out / "index.html").read_text()
    assert len(pages) == 3
