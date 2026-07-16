# Legal Help RAG System — Project & API Key Setup

> Internal documentation for the citizen legal-help assistant.
> Covers the system overview, architecture, and how the two API keys are
> handled securely across the retrieval and generation steps.

---

## 1. Project Overview

A self-funded, **non-profit** tool that lets ordinary citizens ask everyday legal
questions ("my landlord won't return my deposit", "what are my rights if I'm
fired") and get a **plain-language, cited explanation of the law** — not personalised
legal advice.

The system is built on **Retrieval-Augmented Generation (RAG)**:

1. The citizen asks a question.
2. The system retrieves the relevant current law / case text from **Indian Kanoon (IKanoon)**.
3. A general-purpose **LLM (Claude or GPT)** explains that retrieved text in simple language, citing its sources.
4. A safety layer attaches disclaimers and the required attribution.

**Key design principle:** the model has *no* legal knowledge baked into it. All the
"Indian law" specialisation lives in the **retrieval layer and curated content**, so
the law is always pulled fresh and stays current as BNS/BNSS/BSA get amended. This
also means the LLM provider can be swapped later without touching the core asset.

---

## 2. High-Level Architecture

```
Citizen question
      │
      ▼
Query construction  ─────────────────────────────────────────────────┐
  • Stage 1: LLM classifies legal domain (tenancy / employment etc.) │
  • Stage 2: LLM extracts legal keywords from citizen language        │
  • Stage 3: Query builder assembles IKanoon formInput string         │
  • Session context merged for follow-up questions                    │
      │                                                               │
      ▼                                                               │
Cache check (Postgres) ──► (hit? return cached answer)  ◄────────────┘
      │ miss
      ▼
Indian Kanoon retrieval (Search + Document API)   ← IKANOON_API_KEY
  • Search call  → returns list of docs (tid, title, headline, docsource)
  • Document call → fetches full text for top 2–3 docs by tid
      │
      ▼
Use the retrieved data
  • Extract full legal text  → becomes LLM context
  • Extract citation metadata (title, court, date, URL) → shown to user
  • Extract headline snippets → used for quick preview / confidence check
  • Filter by relevance      → drop docs that don't match domain
      │
      ▼
LLM generation (grounded prompt)                  ← LLM_API_KEY
  • Context = cleaned full text of top docs
  • Prompt instructs: answer only from retrieved text, cite every claim
      │
      ▼
Safety / post-processing
  • citation check
  • "powered by IKanoon" attribution  (license condition)
  • "information, not advice — see a lawyer for X" disclaimer
  • harm-signal check
      │
      ▼
Answer to citizen
```

### Component list

| Component | Role |
|---|---|
| Frontend | Chat widget on the website / app |
| Backend orchestrator | Runs the router, manages session state, calls everything below |
| Retrieval service | Wraps the IKanoon Search + Document API calls |
| Session store | Holds current chat's retrieved context briefly (follow-ups don't re-fetch) |
| Cache store | Common answers across all users, keyed by normalized query — cuts repeat cost |
| Curated content store | Content team's verified plain-language explainers (Postgres + keyword search) |
| LLM API | Same model handles both lightweight routing and final grounded answers |
| Safety / post-processing | Citation check, disclaimer, attribution, harm-signal check |
| Logging / analytics DB | Anonymised query logs so the team sees what's asked and where answers are weak |
| Admin dashboard | Content team updates explainers and tracks legal changes |

---

## 3. Recommended Tech Stack

- **Backend:** Python + FastAPI (or Node + Express — use what the team knows).
- **Database:** plain PostgreSQL — one DB holds session context, cache, curated content, and logs. No Redis or vector DB needed on day one.
- **LLM:** Claude or GPT via REST API.
- **Hosting:** Render / Railway / Fly.io for backend; Vercel / Netlify for frontend (free tiers are fine at this scale).

---

## 4. Query Construction — Translating Citizen Language to Legal Search

IKanoon is a **keyword search engine, not a semantic one**. If you send it a raw
citizen question like *"my landlord is not giving back my money after I left the
house"*, the keyword match will be weak and results will be poor. Query construction
is the translation layer that converts everyday citizen language into precise legal
search terms before anything hits the IKanoon API.

### Stage 1 — Classify the legal domain

The citizen's question is sent to the LLM first with a very short, cheap prompt just
to identify which area of law it falls under. This costs almost nothing and steers
every stage that follows.

Prompt sent to LLM:
```
Is this question about: tenancy, employment, consumer rights, family law,
criminal, or other? Reply with one word only.
```

Output: `tenancy`

### Stage 2 — Extract legal keywords

Using the domain from Stage 1, the LLM strips the citizen phrasing and pulls out the
core legal terms that IKanoon will actually match against.

Prompt sent to LLM:
```
The user asked: "my landlord is not giving back my money after I left"
Domain: tenancy
Extract the legal search terms for an Indian law database.
Reply with 3–5 keywords only.
```

Output: `security deposit refund tenant landlord`

### Stage 3 — Build the IKanoon query string

The keywords are assembled into IKanoon's `formInput` format, with optional filters
for document type or court added depending on the domain:

```
security+deposit+refund+tenant+doctypes:judgments,laws
```

This is what actually gets sent to the IKanoon Search API — never the raw citizen
question.

### Handling follow-up questions

When a citizen asks a follow-up like *"what if the landlord deducted money for
damages?"*, the query constructor looks at the **session context** (the last retrieved
documents already in the session store) and blends it with the new question rather
than treating it as a completely fresh search. This prevents re-fetching the same
documents and keeps costs down.

### The full query construction flow

```
Citizen question
  → LLM classifies domain (1 word output, very cheap)
  → LLM extracts keywords (3–5 words output, very cheap)
  → query builder adds doctype/court filters
  → IKanoon search call (this is what costs money)
```

---

## 5. How the Retrieved IKanoon Data Is Used

Every IKanoon search returns two layers of data — the **search result list** and the
**full document text** fetched per result. Each layer is used differently.

### What the search result gives you (per document)

| Field | What it contains | How it is used |
|---|---|---|
| `tid` | Unique document ID (e.g. `183757259`) | Used to fetch the full document text |
| `title` | Case or act name | Shown to citizen as citation; passed into LLM prompt |
| `headline` | Short snippet with matched keywords highlighted | Quick relevance check before fetching full doc |
| `docsource` | Court or tribunal name (e.g. Delhi High Court) | Shown alongside citation for credibility |
| `publishdate` | Date of judgment or enactment | Shown to citizen; helps flag older rulings |
| `doctype` | Type of document (judgment, law, tribunal etc.) | Used to filter and prioritise results |

### What the full document fetch gives you

Calling `/doc/{tid}/` returns the complete legal text of that document. This is the
actual substance that gets passed into the LLM as context — the statutes, the
judgment reasoning, the relevant sections. Without this step, the LLM would only have
the short headline snippet to work with, which is not enough to give a grounded
answer.

### The three things done with retrieved data

**1. Build the LLM context**
The full text of the top 2–3 documents is cleaned, joined, and passed into the LLM
prompt as the only permitted source for the answer. The LLM is explicitly instructed
to answer only from this text and cite every claim.

**2. Build the citation block shown to the citizen**
From the metadata (`title`, `docsource`, `publishdate`, `tid`), a citation block is
assembled and displayed alongside the answer:

```
Source: Hs Bedi vs National Highway Authority Of India (Delhi High Court, 14 May 2015)
Link: https://indiankanoon.org/doc/183757259/
```

This is what makes the answer trustworthy — the citizen can click through and read
the original judgment themselves. It also satisfies the IKanoon attribution
requirement.

**3. Cache the result**
The cleaned context, the LLM answer, and the citation block are stored together in
Postgres keyed by the normalised query. The next citizen who asks the same question
gets the cached answer instantly with no API call.

### What gets shown to the citizen vs what stays internal

| Data | Shown to citizen | Internal only |
|---|---|---|
| Plain-language LLM answer | Yes | — |
| Citation block (title, court, date, link) | Yes | — |
| "Powered by IKanoon" attribution | Yes (required) | — |
| Full retrieved legal text | No (too long, too complex) | Used as LLM context |
| Raw `tid`, `doctype`, `catids` | No | Used for fetching and filtering |
| Headline snippets | Optional (as a "based on" preview) | Used for relevance check |

---

## 6. API Keys — The Golden Rule

> **Both API keys live ONLY on the backend server. Never in frontend JavaScript.**

If either key is called directly from the browser, anyone can open dev tools, steal
it, and run up your bill. **Every external API call must be proxied through your own
server.**

There are **two separate keys**, one per service, never mixed:

| Key | Used for | Sent as |
|---|---|---|
| `IKANOON_API_KEY` | Retrieving law / case text from Indian Kanoon | `Authorization: Token <key>` |
| `LLM_API_KEY` | Generating the plain-language answer | `x-api-key: <key>` (Anthropic) |

---

## 7. Step-by-Step: Incorporating the Keys

### Step 1 — Store keys outside the code

Create a `.env` file and **add it to `.gitignore`** so it's never committed:

```
IKANOON_API_KEY=your-ikanoon-token-here
LLM_API_KEY=your-claude-or-gpt-key-here
```

Load them at runtime:

```python
import os
from dotenv import load_dotenv

load_dotenv()
IKANOON_API_KEY = os.environ["IKANOON_API_KEY"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
```

> **Production note:** prefer a real secrets manager (AWS Secrets Manager, Google
> Secret Manager, Vault) over a `.env` file once you're live.

### Step 2 — Retrieve from Indian Kanoon

IKanoon uses `Authorization: Token <key>` (**not** `Bearer`), and its endpoints are
**POST** (not GET).

```python
import requests

IKANOON_BASE = "https://api.indiankanoon.org"

def ikanoon_search(query):
    resp = requests.post(
        f"{IKANOON_BASE}/search/",
        headers={"Authorization": f"Token {IKANOON_API_KEY}"},
        data={"formInput": query, "pagenum": 0},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

def ikanoon_document(doc_id):
    resp = requests.post(
        f"{IKANOON_BASE}/doc/{doc_id}/",
        headers={"Authorization": f"Token {IKANOON_API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
```

> **Billing:** IKanoon is strictly **prepaid with no grace period** — when the
> balance hits zero, the API simply stops returning results. Wrap these calls to
> catch that failure gracefully, and set up **billing alerts**. Put the **cache
> check before** `ikanoon_search` so you don't re-pay for repeated common questions.

### Step 3 — Modify the retrieved content (build context)

Clean the text, keep the top few fragments, and **capture citation metadata** —
needed for both the prompt and the required visible attribution.

```python
def build_context(search_results, max_docs=3):
    chunks, sources = [], []
    for doc in search_results.get("docs", [])[:max_docs]:
        full = ikanoon_document(doc["tid"])
        chunks.append(full.get("doc", "").strip())
        sources.append({
            "title": doc.get("title"),
            "url": f"https://indiankanoon.org/doc/{doc['tid']}/",
        })
    return "\n\n---\n\n".join(chunks), sources
```

### Step 4 — Build the prompt and send to the LLM

```python
def explain_with_llm(question, context, sources):
    citation_list = "\n".join(f"- {s['title']}: {s['url']}" for s in sources)
    prompt = f"""You may only answer using the RETRIEVED TEXT below. Cite the
source for every claim. Explain the law and general process only — never give
personalised legal advice. If the text doesn't answer the question, say so.

RETRIEVED TEXT:
{context}

AVAILABLE SOURCES:
{citation_list}

QUESTION: {question}"""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]
```

### Step 5 — Tie it together with the safety layer

```python
def answer_question(question):
    # 1. (cache check goes here first — return early on hit)
    results = ikanoon_search(question)              # uses IKANOON_API_KEY
    context, sources = build_context(results)        # modify / build context
    answer = explain_with_llm(question, context, sources)  # uses LLM_API_KEY
    return attach_disclaimer_and_attribution(answer, sources)
```

---

## 8. Where Each Key Is Used (Summary)

- **`IKANOON_API_KEY`** → goes into the `Authorization: Token` header on the
  **retrieval** calls (`ikanoon_search`, `ikanoon_document`).
- **`LLM_API_KEY`** → goes into the `x-api-key` header on the **generation** call
  (`explain_with_llm`).
- Both are loaded from environment variables on the backend.
- Neither ever appears in source code, in the frontend, or in version control.

---

## 9. Legal & Compliance Requirements (Do Not Skip)

1. **Attribution is a license condition.** A clear, conspicuous **"powered by
   IKanoon"** logo/credit must be visible to users — somewhere prominent like an
   About section or documentation, not just a footer link.
2. **No accuracy warranty.** IKanoon provides data "as is" from public government
   sources. *Your* product is the one telling citizens "this is accurate," so your
   own disclaimers and citation display must carry that weight.
3. **Information, not advice.** Every answer must frame itself as general legal
   information and route users to a lawyer for anything case-specific or high-risk.
4. **Harm-signal check** runs on every message, regardless of topic.

---

## 10. Cost Notes

- Roughly **₹0.50–0.90 per citizen question** (one search + one or two document fetches).
- IKanoon offers a **₹500 sandbox credit** to start and a **₹10,000/month
  non-commercial free tier** (subject to use-case verification) — worth applying for
  given the non-profit nature; that tier covers roughly **10,000–20,000 questions/month** free.
- **Cache aggressively** for common queries to keep per-question cost down.

---

## 11. Build Order (Get the Core Working First)

1. One backend function: question → IKanoon search → print top results. Confirm retrieval works.
2. Add the LLM call: retrieved text → grounded prompt → print answer. **Full RAG loop now works** — test against 10–15 real questions.
3. Wrap step 2 in a single endpoint (`POST /ask`). Test with curl / Postman. Still no UI.
4. Build the simplest chat widget that calls that one endpoint. End-to-end demo.
5. Add session memory + router (chit-chat vs. new question).
6. Add the cache check before the IKanoon call.
7. Add the safety/compliance layer (citation check, disclaimer, attribution, harm check).
8. Add logging + a bare admin page.
9. Pre-seed the cache with 30–50 reviewed common questions.
10. Soft launch to a small group before opening up.