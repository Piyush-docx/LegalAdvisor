import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
IKANOON_API_KEY = os.environ["IKANOON_API_KEY"]
IKANOON_BASE = "https://api.indiankanoon.org"


def ikanoon_search(query, pagenum=0, extra_params=None):
    data = {"formInput": query, "pagenum": pagenum}
    if extra_params:
        data.update(extra_params)
    resp = requests.post(
        f"{IKANOON_BASE}/search/",
        headers={"Authorization": f"Token {IKANOON_API_KEY}"},
        data=data,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def run_and_report(query, out_path, extra_params=None):
    print(f"Query: {query!r}  extra_params={extra_params}\n")

    result = ikanoon_search(query, extra_params=extra_params)

    print("Top-level keys:", list(result.keys()))
    print("Found (total):", result.get("found"))
    print("Number of docs returned:", len(result.get("docs", [])))
    print()

    for i, doc in enumerate(result.get("docs", [])[:5], start=1):
        print(f"--- Result {i} ---")
        for k in ("title", "docsource", "doctype", "publishdate", "catids"):
            print(f"  {k}: {doc.get(k)}")
        print()

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Full raw response saved to {out_path}")
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("UNFILTERED (plain keywords)")
    print("=" * 70)
    run_and_report(
        "security deposit refund tenant landlord",
        "scripts/last_search_raw.json",
    )

    print()
    print("=" * 70)
    print("FILTERED (doctypes:judgments,laws in formInput string)")
    print("=" * 70)
    run_and_report(
        "security deposit refund tenant landlord doctypes:judgments,laws",
        "scripts/last_search_filtered_raw.json",
    )

    print()
    print("=" * 70)
    print("FILTERED (doctypes as separate POST param = 'judgments')")
    print("=" * 70)
    run_and_report(
        "security deposit refund tenant landlord",
        "scripts/last_search_doctypes_param_judgments.json",
        extra_params={"doctypes": "judgments"},
    )

    print()
    print("=" * 70)
    print("FILTERED (maxcites / sortby, common IKanoon params)")
    print("=" * 70)
    run_and_report(
        "security deposit refund tenant landlord",
        "scripts/last_search_sortby.json",
        extra_params={"sortby": "mostrecent"},
    )
