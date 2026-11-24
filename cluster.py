"""Group headlines about the same event.

MVP method: token overlap (Jaccard) between headlines, with an inverted index so it
stays fast on a few thousand items. Upgrade path: Gemini embeddings (see README).
"""
from __future__ import annotations

import re
from collections import defaultdict

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "after", "over", "into", "amid",
    "says", "say", "said", "new", "news", "live", "updates", "update", "what", "how", "why",
    "who", "will", "are", "was", "has", "have", "not", "but", "its", "his", "her", "their",
    "more", "than", "about", "year", "years", "week", "day", "report", "reports", "video",
    "watch", "analysis", "opinion", "explained", "latest", "first", "could", "may", "out",
}
WORD_RE = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(title: str) -> frozenset[str]:
    words = WORD_RE.findall(title.lower())
    return frozenset(_stem(w) for w in words if len(w) >= 3 and w not in STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster(items: list[dict], threshold: float = 0.3) -> list[dict]:
    """Greedy clustering. Returns clusters with their items, regions and sources."""
    clusters: list[dict] = []
    index: dict[str, set[int]] = defaultdict(set)  # token -> cluster ids

    for item in sorted(items, key=lambda i: i["published"]):
        toks = tokens(item["title"])
        candidates: set[int] = set()
        for tok in toks:
            candidates |= index[tok]

        best_id, best_score = None, 0.0
        for cid in candidates:
            for member_tokens in clusters[cid]["_tokens"]:
                score = jaccard(toks, member_tokens)
                if score > best_score:
                    best_id, best_score = cid, score

        if best_id is not None and best_score >= threshold:
            target = clusters[best_id]
        else:
            target = {"id": len(clusters), "items": [], "_tokens": []}
            clusters.append(target)
            best_id = target["id"]

        target["items"].append(item)
        target["_tokens"].append(toks)
        for tok in toks:
            index[tok].add(best_id)

    result = []
    for c in clusters:
        regions = sorted({i["region"] for i in c["items"]})
        sources = sorted({i["source"] for i in c["items"]})
        result.append(
            {
                "id": c["id"],
                "items": c["items"],
                "regions": regions,
                "sources": sources,
                "score": 3 * len(regions) + len(sources),
            }
        )
    return result


def select_stories(
    clusters: list[dict], max_stories: int = 12, min_regions: int = 2, max_items: int = 12
) -> list[dict]:
    """Keep the stories covered by the most regions (balance rule), best first."""
    eligible = [c for c in clusters if len(c["regions"]) >= min_regions]
    eligible.sort(key=lambda c: (-c["score"], c["id"]))
    selected = eligible[:max_stories]
    for story in selected:
        story["items"] = _balanced_items(story["items"], max_items)
    return selected


def _balanced_items(items: list[dict], max_items: int) -> list[dict]:
    """Round-robin over regions so one region cannot crowd out the others."""
    by_region: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_region[item["region"]].append(item)
    picked: list[dict] = []
    while len(picked) < max_items and any(by_region.values()):
        for region in sorted(by_region):
            if by_region[region] and len(picked) < max_items:
                picked.append(by_region[region].pop(0))
    return picked
