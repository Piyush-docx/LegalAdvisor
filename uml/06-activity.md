# 06 — Activity

The decisions, branch by branch. **Every branch label is the literal value the code
returns or tests** — no paraphrases.

---

## §1 `answer_question` — the cost decision tree

The one function where all three branches meet ([pipeline.py](../src/pipeline.py)).
Colour is money: green = ₹0 in IKanoon fees, red = ₹0.50–0.90.

```mermaid
flowchart TD
    start(["POST /ask"]) --> t0["start_time = perf_counter()<br/>was_cached = False"]
    t0 --> gc["store.get_or_create(session_id, user_id)"]
    gc --> ci["classify_intent(question, session)"]

    ci --> d1{"returns"}
    d1 -->|"RouteIntent.CHITCHAT"| cc["generate_chitchat_response<br/>hardcoded string"]
    cc --> free1["0 Gemini · 0 IKanoon"]

    d1 -->|"RouteIntent.FOLLOW_UP<br/>AND session.last_context_text"| cq["can_context_answer_followup<br/>question, last_context_text"]
    d1 -->|"RouteIntent.NEW_QUERY<br/>or FOLLOW_UP with no context"| rw["rewrite_query(question)"]

    cq --> d2{"returns"}
    d2 -->|"True"| reuse["explain_with_llm on<br/>session.last_context_text<br/>attach session.last_citations"]
    reuse --> free2["1 Gemini gen · 0 IKanoon"]

    d2 -->|"False"| blend["format_conversation_summary<br/>rewrite_query(question, conversation_context)"]
    blend --> bc1["build_context(search_query)<br/>REPLACES session context"]
    bc1 --> gen1["explain_with_llm"]
    gen1 --> paid1["1 search + 5 docs"]

    rw --> cache["get_cached_query(search_query)"]
    cache --> d3{"returns"}
    d3 -->|"dict"| hit["was_cached = True<br/>json.loads citations<br/>rebuild Citation objects<br/>reuse stored llm_answer"]
    hit --> free3["0 IKanoon · generation SKIPPED"]
    d3 -->|"None"| bc2["build_context(search_query)"]
    bc2 --> gen2["explain_with_llm"]
    gen2 --> save2["cache_query(...)<br/>store for next time"]
    save2 --> paid2["1 search + 5 docs"]

    free1 --> conv
    free2 --> conv
    free3 --> conv
    paid1 --> conv
    paid2 --> conv

    conv["attach_disclaimer_and_attribution<br/>on every non-CHITCHAT path, P8"] --> fin
    fin["session.add_message user<br/>session.add_message assistant<br/>store.save"] --> lg["log_query question, intent.name,<br/>was_cached, duration_ms"]
    lg --> out(["AnswerWithSession"])

    classDef free fill:#e6f4ea,stroke:#1e8e3e,stroke-width:2px
    classDef paid fill:#fdecea,stroke:#d93025,stroke-width:2px
    class free1,free2,free3 free
    class paid1,paid2 paid
```

**Reading the tree**

- **Three of five leaves cost ₹0 in IKanoon fees.** That is the router's entire
  justification (**P3**) — and the shape makes it auditable at a glance.
- **`CHITCHAT` skips the safety layer**, correctly: no legal information, no
  disclaimer.
- **`FOLLOW_UP` never consults `query_cache`.** ⚠ A follow-up whose rewritten query
  already exists in cache still re-pays IKanoon on the `False` branch.
- **Only the `None` branch writes to the cache.** The `dict` branch cannot refresh
  the row, which is why a cached row is immortal
  ([05-state-machines.md](05-state-machines.md) §5).
- **`was_cached` only ever becomes `True` on the `dict` branch**, so the admin
  hit-rate (**P9**) ignores the two router branches that saved the most money. The
  metric measures the cache, not the savings.

---

## §2 `classify_intent` — cheap guards before expensive ones

```mermaid
flowchart TD
    m(["message, session"]) --> fast["is_fast_chitchat(message)<br/>strip non-word chars, lower, strip"]
    fast --> d1{"cleaned in<br/>FAST_CHITCHAT_PATTERNS<br/>18 entries"}
    d1 -->|"True"| ret1(["RouteIntent.CHITCHAT<br/>no network I/O at all"])

    d1 -->|"False"| sum{"session.messages empty<br/>AND no last_context_text"}
    sum -->|"True"| s1["summary = 'None (new conversation)'"]
    sum -->|"False"| s2["format_conversation_summary<br/>last 4 messages, 200 chars each"]

    s1 --> key
    s2 --> key
    key{"_get_client()<br/>LLM_API_KEY set"}
    key -->|"None"| fb1{"session.last_context_text"}
    fb1 -->|"truthy"| ret2(["RouteIntent.FOLLOW_UP"])
    fb1 -->|"falsy"| ret3(["RouteIntent.NEW_QUERY"])

    key -->|"client"| llmcall["generate_content ROUTER_PROMPT<br/>max_output_tokens=16<br/>thinking_budget=0"]
    llmcall --> d2{"raw_text = response.text<br/>strip, upper"}
    d2 -->|"contains 'CHITCHAT'"| ret4(["RouteIntent.CHITCHAT"])
    d2 -->|"contains 'FOLLOW_UP'<br/>AND last_context_text"| ret5(["RouteIntent.FOLLOW_UP"])
    d2 -->|"anything else"| ret6(["RouteIntent.NEW_QUERY"])
    llmcall -->|"raises Exception"| fb2{"session.last_context_text"}
    fb2 -->|"truthy"| ret7(["RouteIntent.FOLLOW_UP"])
    fb2 -->|"falsy"| ret8(["RouteIntent.NEW_QUERY"])

    classDef free fill:#e6f4ea,stroke:#1e8e3e,stroke-width:2px
    class ret1 free
```

**Why the guards are ordered this way**

- **Set membership before a model call.** The highest-frequency inputs to any chat
  UI are greetings; answering them from a `set` costs nothing (**P3**).
- **`"contains"`, not equality.** `"FOLLOW_UP" in raw_text` tolerates a model that
  adds punctuation or a newline. With 16 output tokens there is no room for prose, so
  substring matching is safe and strictly more robust.
- **`FOLLOW_UP` is double-guarded** — the model must say it *and* `last_context_text`
  must exist. Answering a follow-up with no context is the one failure mode worth
  two checks.
- **Every failure path degrades toward doing more work, never toward answering from
  nothing.** No API key and no exception both fall to `NEW_QUERY` unless context
  exists. Failures cost money, not correctness.
- ⚠ `except Exception` swallows the cause. A misconfigured key looks identical to a
  transient 503, and nothing is logged.

---

## §3 `extract_substantive_text` — which paragraphs reach the LLM (P2)

The 90% token saving, as a decision.

```mermaid
flowchart TD
    raw(["DocumentText.doc<br/>raw HTML, 100K+ chars"]) --> soup["BeautifulSoup html.parser"]
    soup --> hid["decompose every span.hidden_text<br/>IKanoon page-number artifacts"]
    hid --> find["find_all(attrs={'data-structure': True})"]
    find --> d1{"tagged_paragraphs"}

    d1 -->|"empty list"| fb["get_text(separator=' ')<br/>collapse whitespace"]
    fb --> fbout(["FULL cleaned text<br/>statutes have no data-structure tags"])

    d1 -->|"non-empty"| loop["for each tagged paragraph"]
    loop --> d2{"p.get('data-structure')<br/>in SUBSTANTIVE_TAGS"}
    d2 -->|"'Issue'"| keep["append get_text strip"]
    d2 -->|"'Facts'"| keep
    d2 -->|"'Conclusion'"| keep
    d2 -->|"'CDiscource' judicial reasoning"| drop["DISCARD"]
    d2 -->|"'Precedent' citations to other cases"| drop
    d2 -->|"any other value"| drop
    keep --> join["' '.join, collapse whitespace"]
    join --> out(["substantive text<br/>~10% of the original"])

    classDef good fill:#e6f4ea,stroke:#1e8e3e,stroke-width:2px
    classDef warn fill:#fef7e0,stroke:#f9ab00,stroke-width:2px
    class out good
    class fbout warn
```

**Why this is the chunking strategy**

There is **no fixed-size chunking, no overlap, no embeddings and no vector store**.
The retrieval unit is a whole document, filtered structurally. That works because:

- **IKanoon already labels each paragraph's role**, so semantic segmentation comes
  free — no embedding model has to guess boundaries.
- **Ranking happens upstream.** IKanoon's keyword search picks the documents, so
  there is nothing to re-score locally.
- **Five filtered documents fit Gemini's context window**, so sub-document splitting
  buys nothing.
- **Dropping `CDiscource` and `Precedent` is a product decision**, not just a cost
  one: a citizen needs the outcome in plain language, not the court's reasoning chain.

**⚠ Where it is weak**

1. **The fallback is unbounded.** No `data-structure` tags means the full cleaned
   text, and nothing in `build_context` or `build_prompt` caps length — so a
   statute-heavy result set can spike tokens and latency. The single highest-value
   fix: cap per-document and total context length.
2. **No passage-level relevance.** A document is included whole even if one paragraph
   matters. Precision rests entirely on `rewrite_query` (**P1**) and IKanoon's rank.
3. **Silent degradation.** If IKanoon changes its markup, every document takes the
   fallback path and token cost quietly returns to 100%. Nothing logs it.
4. **`clean_document_html` is dead code** — defined, tested, never called by
   `build_context`.

---

## §4 Auth dependency ladder

Three FastAPI dependencies, each building on the last. The ladder is why route
protection is one parameter and not a middleware.

```mermaid
flowchart TD
    h(["Authorization header"]) --> opt["get_current_user_optional"]
    opt --> d1{"authorization"}
    d1 -->|"None"| n1(["None"])
    d1 -->|"present"| sp["split()"]
    sp --> d2{"len(parts) == 2<br/>AND parts[0].lower() == 'bearer'"}
    d2 -->|"False"| n2(["None"])
    d2 -->|"True"| vt["verify_auth_token(parts[1])<br/>loads(max_age=86400)"]
    vt --> d3{"result"}
    d3 -->|"raises, any Exception"| n3(["None"])
    d3 -->|"payload"| p(["dict email, user_id"])

    n1 --> req
    n2 --> req
    n3 --> req
    p --> req
    req["get_current_user_required<br/>calls the optional one"] --> d4{"user"}
    d4 -->|"None"| e401(["HTTP 401<br/>Authentication required or token expired"])
    d4 -->|"dict"| ok(["dict"])

    ok --> adm["get_admin_user<br/>calls the required one"]
    adm --> env["ADMIN_EMAILS split ',' lower strip"]
    env --> d5{"user['email'] in admin_emails"}
    d5 -->|"False"| e403(["HTTP 403<br/>Forbidden. Admin access required."])
    d5 -->|"True"| okadm(["dict"])

    classDef deny fill:#fdecea,stroke:#d93025,stroke-width:2px
    class e401,e403 deny
```

**Which route uses which**

| Dependency | Routes | Why |
|---|---|---|
| `get_current_user_optional` | `POST /ask` | The tool must work with no account (**P6**). `user_id` is `None` and the session is anonymous. |
| `get_current_user_required` | `/auth/me`, all `/sessions*` | Chat history is per-user; there is nothing to return without an identity. |
| `get_admin_user` | `GET /admin/logs` | Env-var allow-list, not a DB role — cannot be escalated by writing to the database (**P9**). |

**Why a ladder rather than middleware:** `/ask` needs to *know* whether a caller is
authenticated without *requiring* it. Middleware would have to either reject or
ignore; a dependency returns `None` and lets the handler decide. That single
distinction is what makes anonymous-then-adopt possible
([05-state-machines.md](05-state-machines.md) §2b).

**⚠** `verify_auth_token` catches bare `Exception`, so a malformed token, an expired
one and a tampered one are indistinguishable — good for attackers, bad for
debugging, and nothing is logged.
