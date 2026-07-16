import os

import requests
from dotenv import load_dotenv

load_dotenv()
IKANOON_API_KEY = os.environ["IKANOON_API_KEY"]
IKANOON_BASE = "https://api.indiankanoon.org"


def ikanoon_document(doc_id):
    resp = requests.post(
        f"{IKANOON_BASE}/doc/{doc_id}/",
        headers={"Authorization": f"Token {IKANOON_API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    # A High Court result from our earlier search (Hs Bedi vs NHAI, Delhi HC)
    tid = "183757259"
    doc = ikanoon_document(tid)

    print("Top-level keys:", list(doc.keys()))
    for k, v in doc.items():
        if k == "doc":
            continue
        v_str = str(v)
        if len(v_str) > 200:
            v_str = v_str[:200] + "... [truncated]"
        print(f"  {k}: {v_str}")

    text = doc.get("doc", "")
    print(f"\nFull doc text length: {len(text)} chars")
    print("\n--- First 1500 chars ---")
    print(text[:1500])
    print("\n--- Last 1000 chars ---")
    print(text[-1000:])
