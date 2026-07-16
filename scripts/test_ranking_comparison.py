import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
IKANOON_API_KEY = os.environ["IKANOON_API_KEY"]
IKANOON_BASE = "https://api.indiankanoon.org"

# Tier ranking: lower number = stronger precedent.
# Based on observed doctype codes from our distribution test.
DOCTYPE_TIER = {
    # Acts / statutes - the law itself
    91: 0, 40: 0,
    # High Courts (various state codes we saw)
    1002: 1, 1007: 1, 1020: 1, 1024: 1, 1025: 1, 1031: 1,
    # Tribunals / commissions
    # (none observed yet in our sample, placeholder tier)
    # District / lower courts
    10000: 3, 10001: 3,
}
DEFAULT_TIER = 2  # unknown doctype -> treat as "tribunal-ish", between HC and district


def tier_of(doctype):
    return DOCTYPE_TIER.get(doctype, DEFAULT_TIER)


def ikanoon_search(query, pagenum=0):
    resp = requests.post(
        f"{IKANOON_BASE}/search/",
        headers={"Authorization": f"Token {IKANOON_API_KEY}"},
        data={"formInput": query, "pagenum": pagenum},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.min


if __name__ == "__main__":
    query = "security deposit refund tenant landlord"
    num_pages = 3

    pool = []
    for page in range(num_pages):
        result = ikanoon_search(query, pagenum=page)
        docs = result.get("docs", [])
        if not docs:
            break
        pool.extend(docs)

    print(f"Query: {query!r}")
    print(f"Candidate pool size: {len(pool)} docs\n")

    # Strategy A: search rank order (as returned by API, i.e. "top 5 as-is")
    strategy_a = pool[:5]

    # Strategy B: recency only (most recent publishdate first)
    strategy_b = sorted(pool, key=lambda d: parse_date(d.get("publishdate")), reverse=True)[:5]

    # Strategy C: tier first, recency as tiebreaker within tier
    strategy_c = sorted(
        pool,
        key=lambda d: (tier_of(d.get("doctype")), -parse_date(d.get("publishdate")).timestamp()),
    )[:5]

    def show(name, docs):
        print(f"--- {name} ---")
        for i, d in enumerate(docs, start=1):
            print(f"  {i}. [{d.get('publishdate')}] tier={tier_of(d.get('doctype'))} "
                  f"{d.get('docsource'):30s} | {d.get('title')}")
        print()

    show("Strategy A: Search rank as-is (top 5 by API order)", strategy_a)
    show("Strategy B: Recency only (latest 5 by date)", strategy_b)
    show("Strategy C: Tier first, recency as tiebreaker", strategy_c)
