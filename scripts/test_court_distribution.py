import os
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()
IKANOON_API_KEY = os.environ["IKANOON_API_KEY"]
IKANOON_BASE = "https://api.indiankanoon.org"

# Rough classification of docsource strings into a precedent tier.
# IKanoon's docsource is a free-text court/tribunal name, so this is
# a keyword heuristic, not an official ranking.
HIGH_COURT_MARKERS = ["High Court"]
SUPREME_COURT_MARKERS = ["Supreme Court"]
TRIBUNAL_MARKERS = ["Tribunal", "Commission", "Forum", "Appellate"]
DISTRICT_MARKERS = ["District Court", "Sessions Court", "Civil Court", "Munsiff"]


def classify(docsource):
    if not docsource:
        return "unknown"
    if any(m in docsource for m in SUPREME_COURT_MARKERS):
        return "supreme_court"
    if any(m in docsource for m in HIGH_COURT_MARKERS):
        return "high_court"
    if any(m in docsource for m in TRIBUNAL_MARKERS):
        return "tribunal"
    if any(m in docsource for m in DISTRICT_MARKERS):
        return "district_or_lower"
    return "other"


def ikanoon_search(query, pagenum=0):
    resp = requests.post(
        f"{IKANOON_BASE}/search/",
        headers={"Authorization": f"Token {IKANOON_API_KEY}"},
        data={"formInput": query, "pagenum": pagenum},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    query = "security deposit refund tenant landlord"
    num_pages = 3  # 3 pages x 10 docs = 30 docs sampled

    tier_counter = Counter()
    docsource_counter = Counter()
    doctype_counter = Counter()
    rows = []

    for page in range(num_pages):
        result = ikanoon_search(query, pagenum=page)
        docs = result.get("docs", [])
        if not docs:
            break
        for doc in docs:
            docsource = doc.get("docsource") or "(none)"
            tier = classify(docsource)
            tier_counter[tier] += 1
            docsource_counter[docsource] += 1
            doctype_counter[doc.get("doctype")] += 1
            rows.append((tier, docsource, doc.get("doctype"), doc.get("title")))

    print(f"Query: {query!r}")
    print(f"Sampled {len(rows)} docs across {num_pages} pages\n")

    print("--- Tier distribution ---")
    total = sum(tier_counter.values())
    for tier, count in tier_counter.most_common():
        pct = 100 * count / total
        print(f"  {tier:20s} {count:3d}  ({pct:.0f}%)")

    print("\n--- docsource distribution ---")
    for source, count in docsource_counter.most_common():
        print(f"  {count:3d}  {source}")

    print("\n--- doctype code distribution ---")
    for dtype, count in doctype_counter.most_common():
        print(f"  {count:3d}  doctype={dtype}")

    print("\n--- Per-doc detail ---")
    for tier, source, dtype, title in rows:
        print(f"  [{tier:18s}] doctype={dtype!s:6s} {source:35s} | {title}")
