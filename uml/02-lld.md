# 02 — Low-Level Design

Components per service, then the classes that actually carry the design. See
[README.md](README.md) for problem IDs (P1–P10).

---

## §1 Backend components — who owns what

One box per module in `src/`. Arrows are real imports.

### §1a Edge and orchestration

```mermaid
flowchart TB
    api["<b>api.py</b><br/>FastAPI app, 10 routes<br/>Pydantic request/response models<br/>CORS, exception to HTTP 500"]
    auth["<b>auth.py</b><br/>generate_otp · verify_otp<br/>create/verify_auth_token<br/>3 FastAPI dependencies<br/>send_otp via SMTP or log"]
    pipe["<b>pipeline.py</b><br/>answer_question — the only<br/>place the 3 branches meet"]
    router["<b>router.py</b><br/>is_fast_chitchat regex<br/>classify_intent LLM<br/>can_context_answer_followup<br/>generate_chitchat_response"]
    sess["<b>session.py</b><br/>Session · Message · SessionStore<br/>AnswerWithSession"]
    dbm["<b>db.py</b><br/>init_db on import · get_db<br/>query_cache · query_logs<br/>get_admin_logs"]
    rag["<i>retrieval + generation</i><br/>see the next diagram"]

    api -->|"Depends"| auth
    api -->|"POST /ask"| pipe
    api -->|"GET/PATCH/DELETE /sessions"| sess
    api -->|"GET /admin/logs"| dbm
    pipe --> router
    pipe --> sess
    pipe -->|"cache + log"| dbm
    pipe --> rag
    router -->|"reads last_context_text"| sess
    auth --> dbm
    sess --> dbm

    classDef hot fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
    classDef data fill:#f3e8fd,stroke:#8b5cf6,stroke-width:2px
    classDef ref fill:#fafafa,stroke:#9aa0a6,stroke-width:1.5px,stroke-dasharray: 6 4
    class pipe hot
    class dbm data
    class rag ref
```

### §1b The RAG subsystems

Numbered edges are `answer_question`'s call order on the full-cost path.

```mermaid
flowchart TB
    pipe["<b>pipeline.py</b><br/>answer_question"]

    subgraph retr["Retrieval — src/retrieval/"]
        rew["<b>rewrite.py</b><br/>prose to IKanoon syntax<br/>P1"]
        ctx["<b>context.py</b><br/>build_context, thread fan-out<br/>Citation model<br/>P4"]
        sel["<b>selection.py</b><br/>select_top_docs — top 5, no rerank"]
        sea["<b>search.py</b><br/>POST /search/"]
        doc["<b>document.py</b><br/>POST /doc/{tid}/<br/>extract_substantive_text<br/>P2"]
    end

    subgraph gen["Generation — src/generation/"]
        prompt["<b>prompt.py</b><br/>build_prompt, last 4 turns"]
        llm["<b>generate.py</b><br/>explain_with_llm, 1024 tokens"]
        safe["<b>safety.py</b><br/>attach_disclaimer_and_attribution<br/>P8"]
    end

    pipe -->|"1 · normalise the question"| rew
    pipe -->|"2 · retrieve the law"| ctx
    pipe -->|"3 · explain it"| llm
    pipe -->|"4 · make it compliant"| safe
    ctx --> sea
    ctx --> sel
    ctx --> doc
    llm --> prompt

    classDef hot fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
    class pipe hot
```

**Why it is split this way**

- **`pipeline.py` is the only module that knows all three branches exist.**
  `router.py` classifies but never retrieves; `context.py` retrieves but never
  decides. That is what makes the cost story auditable: one function, one place
  where "did this request cost money?" is decided (**P3**).
- **`selection.py` is six lines and still its own module.** It is the designated
  seam for reranking by court tier or recency. `scripts/test_ranking_comparison.py`
  exists, so the experiment was run; the shipped behaviour is raw rank order.
  ⚠ Verify what that script concluded before claiming the no-rerank choice was
  measured.
- **`safety.py` sits after `generate.py`, never inside it** (**P8**). Attribution
  is a licence condition, so it cannot depend on the model complying.
- **`db.py` calls `init_db()` at import time.** Convenient — no migration step —
  but it means importing anything transitively creates `legal.db`. Tests work
  around this via `DATABASE_PATH`.
- ⚠ **`db.py` helpers ignore `db_path`.** `get_cached_query`, `cache_query`,
  `log_query` and `get_admin_logs` all call `get_db()` with no argument, so they
  always hit the module-level `DB_PATH`. `SessionStore` and `auth` accept an
  injected path; the cache and log layer does not.

---

## §2 Frontend components — who owns what state

```mermaid
flowchart TB
    main["<b>main.jsx</b><br/>BrowserRouter > ThemeProvider > AuthProvider"]

    subgraph ctxs["Global state — Context only, no Redux"]
        actx["<b>AuthContext</b><br/>user · token · isLoading<br/>rehydrates from localStorage<br/>then GET /auth/me"]
        tctx["<b>ThemeContext</b><br/>light or dark<br/>writes data-theme on root<br/>P10 token system"]
    end

    app["<b>App.jsx</b><br/>navbar · Routes · isLoginModalOpen"]

    subgraph pages["Pages"]
        chat["<b>Chat.jsx</b> — owns nearly all state:<br/>question · messages · sessionId<br/>sessions · isLoading · error · sidebarOpen"]
        about["About.jsx<br/>IKanoon attribution surface"]
        admin["<b>Admin.jsx</b><br/>P9 metrics + log table"]
    end

    subgraph comps["Components"]
        side["<b>Sidebar.jsx</b><br/>list · search · inline rename<br/>delete · collapse"]
        msg["<b>MessageItem.jsx</b><br/>render + copy/regenerate toolbar"]
        login["<b>LoginModal.jsx</b><br/>two-step: email then 6-digit code"]
    end

    client["<b>api/client.js</b><br/>single fetch layer<br/>getAuthHeaders reads localStorage<br/>VITE_API_BASE_URL"]

    main --> actx
    main --> tctx
    actx --> app
    tctx --> app
    app --> chat
    app --> about
    app --> admin
    app --> login
    chat --> side
    chat --> msg
    chat --> client
    admin --> client
    login --> actx
    actx --> client

    classDef hot fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px
    class chat,client hot
```

**Why it is split this way**

- **Context, no state library.** Only two things are genuinely global — who you
  are and which theme — and both are read-mostly. Everything else is one page's
  concern, so `Chat.jsx` holds it locally.
- **`client.js` is the only module that calls `fetch`.** `getAuthHeaders()` reads
  the token from `localStorage` on every call rather than taking it from
  `AuthContext`, which is why a stale React state can never send a stale header.
- ⚠ **`Sidebar`, `Chat` and `AuthContext` all read `localStorage` directly** in
  places, so the storage keys are a fourth implicit contract alongside the three
  Context values.
- `Admin.jsx` is routed but **not route-guarded**: `App.jsx` shows the link when
  `isLoggedIn`, and authorisation is enforced server-side by `get_admin_user`.
  A non-admin can navigate to `/admin` and will see the 403 error text.

---

## §3 Classes — the objects that carry the design

Three clusters: conversation state, retrieval shapes, generation shapes.

```mermaid
classDiagram
    class Session {
        +str session_id "uuid4"
        +Optional~str~ user_id "None = anonymous"
        +str title "auto-titled from 1st msg"
        +datetime created_at
        +datetime last_active_at
        +list~Message~ messages
        +Optional~str~ last_context_text
        +list~Citation~ last_citations
        +Optional~str~ last_query
        +add_message(role, content)
    }
    class Message {
        +Optional~int~ id "None = not yet persisted"
        +str role "user | assistant"
        +str content
        +datetime timestamp
    }
    class SessionStore {
        +int MAX_MEMORY_SESSIONS = 200
        +int ttl_seconds = 86400
        -dict _memory_sessions
        +get(session_id) Optional~Session~
        +get_or_create(session_id, user_id) Session
        +save(session)
        +list_user_sessions(user_id, limit, offset)
        +rename_session(id, title, user_id) bool
        +delete_session(id, user_id) bool
        -_evict_if_needed()
        +cleanup_expired() int
    }
    class AnswerWithSession {
        <<str subclass>>
        +str session_id
    }
    class RouteIntent {
        <<enum, str>>
        CHITCHAT
        FOLLOW_UP
        NEW_QUERY
    }

    SessionStore "1" o-- "*" Session : _memory_sessions + SQLite
    Session "1" *-- "*" Message
    Session ..> AnswerWithSession : returned as
```

**Why these shapes**

- **`Message.id` is `Optional[int]` and that is load-bearing.** `SessionStore.save`
  inserts only messages where `id is None`, then back-fills `lastrowid`. That is
  the whole append-only persistence strategy — no diffing, no full rewrite.
- **`AnswerWithSession` subclasses `str`.** `answer_question` must return both the
  answer and the session id, but older call sites and tests treat the result as a
  plain string. Subclassing `str` carries the id without breaking them.
  ⚠ It is a compatibility shim, not a design goal: `api.py` still reaches for it
  with `getattr(result, "session_id", ...)` and a `uuid4()` fallback, and
  `return_session=True` returns a plain tuple instead — three return shapes from
  one function.
- **`RouteIntent` subclasses `str`** so `intent.name` logs cleanly into
  `query_logs.intent` (**P9**) without a conversion layer.
- **`last_context_text` lives on the session, not in a cache.** That single field
  is what makes a `FOLLOW_UP` cost ₹0 in IKanoon fees (**P3**).

```mermaid
classDiagram
    class SearchDoc {
        +int tid "document id, used to fetch"
        +str title "contains HTML, stripped later"
        +int doctype
        +str docsource "court or Act"
        +str publishdate
        +str headline
        +int docsize
        +int numcites
        +int numcitedby
        +Optional catids, authorid, author, bench, fragment
    }
    class SearchResult {
        +list~SearchDoc~ docs
        +str found "count, as a string"
        +Optional categories, encodedformInput
    }
    class DocumentText {
        +int tid
        +str title
        +str docsource
        +str publishdate
        +str doc "raw HTML, 100K+ chars"
        +int numcites
        +int numcitedby
        +Optional~str~ divtype
    }
    class Citation {
        +str title "HTML stripped"
        +str docsource
        +str publishdate
        +str url "indiankanoon.org/doc/TID/"
    }

    SearchResult "1" *-- "*" SearchDoc
    SearchDoc ..> DocumentText : fetch_document(tid)
    SearchDoc ..> Citation : metadata kept
    DocumentText ..> Citation : text discarded after extract
```

**Why these shapes**

- **Every optional field on `SearchDoc` is optional because IKanoon omits it**
  sometimes. Pydantic validates the response, so a shape change fails loudly at
  the boundary instead of as a `KeyError` deep in `build_context`.
- **`Citation` is deliberately tiny.** Four fields, all safe to show a citizen.
  `tid`, `doctype` and `catids` stay internal ([p.md](../p.md) §5). It is the only
  retrieval object that survives into the session and the cache, which is why it
  is the only one needing `model_dump()` round-tripping through JSON.
- **`DocumentText.doc` is the 100K-char problem (P2).** It is consumed by
  `extract_substantive_text` and then dropped — it is never stored, and never the
  thing put in the prompt.

```mermaid
classDiagram
    class LLMAnswer {
        +str text
        +str stop_reason "finish_reason.name"
        +Usage usage
    }
    class Usage {
        +int input_tokens
        +int output_tokens
    }
    LLMAnswer "1" *-- "1" Usage
```

⚠ **`Usage` is captured and then thrown away.** `explain_with_llm` populates
token counts, but `pipeline.py` reads only `answer.text`, and `query_logs` has no
token columns. The most direct cost signal the system collects never reaches the
admin dashboard (**P9**) — the obvious next fix.
