# 04 — Sequences

What happens in order, for the flows that matter. Each diagram is annotated with
its **cost**, because cost is the reason the branches exist (**P3**, **P7**).

Source of truth: [pipeline.py](../src/pipeline.py) `answer_question`,
[api.py](../src/api.py), [auth.py](../src/auth.py).

Reference prices from [p.md](../p.md) §10: one IKanoon search plus document
fetches is **₹0.50–0.90** per question.

---

## §1 NEW_QUERY, cache miss — the full-cost path

Every external call the system can make, in one request.

```mermaid
sequenceDiagram
    autonumber
    participant U as Citizen
    participant C as client.js
    participant A as api.py POST /ask
    participant P as pipeline.answer_question
    participant S as SessionStore
    participant R as router
    participant W as rewrite
    participant D as db query_cache
    participant X as context.build_context
    participant IK as Indian Kanoon API
    participant G as Gemini API
    participant F as safety

    U->>C: types question
    C->>A: POST /ask {question, session_id?} + Bearer?
    A->>A: get_current_user_optional
    A->>P: answer_question(question, session_id, user_id)
    P->>P: start_time = perf_counter()
    P->>S: get_or_create(session_id, user_id)
    S-->>P: Session

    P->>R: classify_intent(question, session)
    R->>R: is_fast_chitchat -> False
    R->>G: ROUTER_PROMPT, max_output_tokens=16, thinking_budget=0
    G-->>R: "NEW_QUERY"
    R-->>P: RouteIntent.NEW_QUERY

    P->>W: rewrite_query(question)
    W->>G: REWRITE_PROMPT, max_output_tokens=64, thinking_budget=0
    G-->>W: quoted phrase ANDD area ANDD term doctypes laws
    W-->>P: search_query

    P->>D: get_cached_query(search_query)
    D-->>P: None
    Note over P,D: miss, so was_cached stays False

    P->>X: build_context(search_query, max_docs=5)
    X->>IK: POST /search/ formInput, pagenum=0
    IK-->>X: SearchResult docs
    X->>X: select_top_docs(n=5) raw rank order
    par ThreadPoolExecutor, P4
        X->>IK: POST /doc/{tid}/ x5
        IK-->>X: DocumentText x5, 100K+ chars each
    end
    X->>X: extract_substantive_text, keep Issue Facts Conclusion, P2
    X-->>P: context_text, list of Citation

    P->>G: explain_with_llm, prompt + last 4 turns, max_output_tokens=1024
    G-->>P: LLMAnswer text stop_reason usage
    P->>F: attach_disclaimer_and_attribution(text, citations)
    F-->>P: answer + Sources + DISCLAIMER + ATTRIBUTION

    P->>D: cache_query(search_query, context, citations_json, llm_answer)
    P->>P: session.last_context_text and last_citations set
    P->>S: add_message user, add_message assistant, save
    S->>S: write-through to SQLite, P5
    P->>D: log_query(question, "NEW_QUERY", False, duration_ms)
    P-->>A: AnswerWithSession
    A-->>C: {answer, session_id}
    C-->>U: renders answer + citations
```

**Cost: 3 Gemini calls + 6 IKanoon calls (1 search + 5 docs) ≈ ₹0.50–0.90.**

**Why this order**

- **The cache check sits *after* the rewrite, not before it.** That is what makes
  the cache work across phrasings (**P7**) — the rewritten query is the
  normalisation key. ⚠ The price is that a cache *hit* still costs one Gemini call;
  the cache can never make a request free, only cheap. A cheap exact-match lookup
  on the raw question, tried first, would shortcut the repeat-verbatim case.
- **`select_top_docs` then fan-out, in that order.** Narrowing to 5 before fetching
  is the only thing keeping the paid document calls bounded.
- **Extraction happens before the prompt is built**, so the 100K-char bodies never
  reach Gemini (**P2**).
- **`log_query` is last and unconditional**, so latency includes everything above
  it. That is what makes `avg_response_time_ms` on the admin page honest.
- ⚠ **`cache_query` runs before the session is saved.** If persistence then fails,
  the answer is cached but the conversation is lost.

---

## §2 NEW_QUERY, cache hit — the cheap path

```mermaid
sequenceDiagram
    autonumber
    participant P as pipeline
    participant R as router
    participant W as rewrite
    participant D as db query_cache
    participant G as Gemini API
    participant F as safety

    P->>R: classify_intent
    R->>G: router call
    G-->>R: "NEW_QUERY"
    P->>W: rewrite_query(question)
    W->>G: rewrite call
    G-->>W: search_query
    P->>D: get_cached_query(search_query)
    D-->>P: dict with context_text, citations, llm_answer
    Note over P: was_cached = True
    P->>P: json.loads citations, rebuild Citation objects
    P->>F: attach_disclaimer_and_attribution(llm_answer, citations)
    F-->>P: final_answer
    Note over P,D: no IKanoon call, no generation call
    P->>D: log_query(question, "NEW_QUERY", True, duration_ms)
```

**Cost: 2 Gemini calls, 0 IKanoon calls, ₹0 in IKanoon fees.**

**Why**

The cached row deliberately stores the **pre-safety** answer, so the disclaimer and
attribution are re-attached live (**P8**). Cached answers therefore always carry the
current legal text.

⚠ **No TTL and no invalidation.** `created_at` is stored but never compared, so a
cached answer about an amended Act is served indefinitely. For a tool whose entire
justification is "the law stays current", this is the most consequential open
defect in the system. See [05-state-machines.md](05-state-machines.md) §5.

---

## §3 FOLLOW_UP — context reuse

The branch that exists purely to avoid paying twice for the same law.

```mermaid
sequenceDiagram
    autonumber
    participant P as pipeline
    participant S as Session
    participant R as router
    participant G as Gemini API
    participant X as build_context
    participant IK as Indian Kanoon API
    participant F as safety

    P->>R: classify_intent(question, session)
    R->>R: format_conversation_summary, last 4 turns, 200 chars each
    R->>G: ROUTER_PROMPT with summary
    G-->>R: "FOLLOW_UP"
    Note over R: only honoured if session.last_context_text is set
    R-->>P: RouteIntent.FOLLOW_UP

    P->>R: can_context_answer_followup(question, last_context_text)
    R->>G: CONTEXT_CHECK_PROMPT, first 3000 chars, max_output_tokens=10
    G-->>R: "YES" or "NO"

    alt returns True
        P->>G: explain_with_llm on session.last_context_text
        G-->>P: answer
        P->>F: attach with session.last_citations
        Note over P,IK: 0 IKanoon calls, same citations reused
    else returns False
        P->>R: format_conversation_summary(session)
        P->>G: rewrite_query(question, conversation_context)
        G-->>P: search_query blending prior topic
        P->>X: build_context(search_query)
        X->>IK: 1 search + 5 doc fetches
        IK-->>X: docs
        X-->>P: new context_text, new citations
        P->>G: explain_with_llm
        G-->>P: answer
        P->>F: attach with new citations
        Note over P: session context REPLACED
    end
    P->>P: log_query(question, "FOLLOW_UP", False, duration_ms)
```

**Cost: `True` → 3 Gemini, 0 IKanoon. `False` → 4 Gemini, 6 IKanoon.**

**Why**

- **The context-check is a separate one-word LLM call** (10 output tokens) guarding
  a ₹0.50–0.90 decision. Cheap gate, expensive thing gated.
- **Only the first 3000 chars are checked.** A gamble: the answer may live deeper in
  the context. It bounds the gate's own cost, and being wrong just means an
  unnecessary retrieval, never a wrong answer.
- **`FOLLOW_UP` is only honoured when `last_context_text` exists** — both in
  `classify_intent` and in `pipeline`'s branch condition. A model that says
  `FOLLOW_UP` with no context falls through to `NEW_QUERY`. Two independent guards
  for the same invariant, because the failure mode is answering from nothing.
- **On the `False` path the query is rewritten *with* conversation context**, which
  is how "what about the deadline?" becomes a query that still mentions tenancy.
- ⚠ **`was_cached` is always `False` on this branch**, and `query_cache` is never
  consulted — a follow-up that happens to match a cached query re-pays IKanoon.
- ⚠ **`log_query` records `was_cached=False` even when the `True` path made zero
  IKanoon calls**, so the admin hit-rate understates how much the router saves.
  The metric measures the cache, not the savings.

---

## §4 CHITCHAT — the zero-cost path

```mermaid
sequenceDiagram
    autonumber
    participant U as Citizen
    participant P as pipeline
    participant R as router
    participant G as Gemini API

    U->>P: "thanks" or "hi" or "who are you"
    P->>R: classify_intent
    R->>R: is_fast_chitchat, strip punctuation, lower, set membership
    Note over R,G: matched, Gemini is never called
    R-->>P: RouteIntent.CHITCHAT
    P->>R: generate_chitchat_response(message)
    R-->>P: hardcoded string, thanks or bye or capability menu
    P->>P: add_message x2, save
    P->>P: log_query(question, "CHITCHAT", False, duration_ms)
```

**Cost: 0 Gemini, 0 IKanoon, ₹0. No network I/O at all.**

**Why**

- **A 18-entry `set` beats a model call** for the highest-frequency inputs a chat
  UI receives. `FAST_CHITCHAT_PATTERNS` is checked before anything else in
  `classify_intent` (**P3**).
- **Responses are hardcoded, not generated.** The capability menu doubles as
  onboarding — it lists the four supported areas of law, so a greeting teaches the
  user what to ask. A generated reply would vary and could over-promise.
- **No disclaimer is attached on this branch**, correctly: `attach_disclaimer_and_attribution`
  is never called, because "hello" is not legal information.
- An unmatched greeting still falls through to the Gemini router, which classifies
  it `CHITCHAT` — so the fast path is an optimisation, not the only guard.

---

## §5 OTP login — passwordless (P6)

```mermaid
sequenceDiagram
    autonumber
    participant U as Citizen
    participant L as LoginModal
    participant AC as AuthContext
    participant A as api.py
    participant AU as auth.py
    participant DB as SQLite
    participant M as SMTP

    U->>L: enters email
    L->>A: POST /auth/send-otp {email}
    A->>AU: generate_otp(email)
    AU->>AU: secrets.randbelow(900000)+100000
    AU->>DB: INSERT otps email, code, expires_at now+10min, used=0
    AU->>M: send_otp, MIMEText over starttls
    alt SMTP configured
        M-->>U: email with 6-digit code
    else not configured or send fails
        AU->>AU: logger.info masked email and code
        Note over AU: dev fallback, no credentials needed
    end
    A-->>L: {message} never contains the code

    U->>L: enters 6-digit code
    L->>A: POST /auth/verify-otp {email, otp}
    A->>AU: verify_otp(email, code)
    AU->>DB: SELECT otps WHERE email AND otp_code AND used=0 ORDER BY id DESC LIMIT 1
    alt no row
        AU-->>A: None
        A-->>L: 400 Invalid or expired OTP
    else expires_at < now
        AU-->>A: None
        A-->>L: 400 Invalid or expired OTP
    else valid
        AU->>DB: UPDATE otps SET used=1
        AU->>DB: SELECT users WHERE email
        opt no user row
            AU->>DB: INSERT users uuid4, email, created_at
            Note over AU,DB: signup and login are the same flow
        end
        AU->>AU: create_auth_token, URLSafeTimedSerializer dumps
        AU-->>A: {token, user, expires_in 86400}
        A-->>L: VerifyOtpResponse
        L->>AC: login(token, user, expiresAt)
        AC->>AC: localStorage set token, user, expires_at
    end
```

**Why**

- **`ORDER BY id DESC LIMIT 1`** means requesting a new code supersedes the old one
  in practice, without deleting rows — the newest matching unused code wins.
- **The same 400 message for "no row" and "expired"** so the endpoint does not
  distinguish a wrong code from a stale one.
- **`used=1` before the user lookup**, inside one `with conn:` transaction, so a
  code cannot be replayed even if user creation fails.
- **Signup has no separate flow.** First successful verification creates the user.
  There is no password column, no reset path, no email-confirmation step — the OTP
  *is* the confirmation (**P6**).
- **Emails are masked in logs** (`_mask_email` → `pi***@gmail.com`), but the dev
  fallback logs the **code in cleartext** — acceptable locally, catastrophic if a
  production host ever runs without SMTP configured.
- ⚠ **No rate limit and no attempt counter, on either endpoint.** `send-otp` can be
  used to mail-bomb an address, and `verify-otp` accepts unlimited guesses against a
  6-digit code for 10 minutes. This is the highest-severity gap in the system. The
  fix is an attempt column plus per-email throttling.

---

## §6 Conversation management

Requires auth on every call — `get_current_user_required`.

```mermaid
sequenceDiagram
    autonumber
    participant CH as Chat.jsx
    participant SB as Sidebar.jsx
    participant A as api.py
    participant ST as SessionStore
    participant DB as SQLite

    Note over CH: useEffect on isLoggedIn
    CH->>A: GET /sessions?limit=50&offset=0
    A->>A: clamp limit to 100
    A->>ST: list_user_sessions(user_id, limit, offset)
    ST->>DB: SELECT WHERE user_id ORDER BY last_active_at DESC
    A-->>CH: {sessions, limit, offset}
    CH->>SB: sessions prop

    SB->>CH: onSelectSession(id)
    CH->>A: GET /sessions/{id}
    A->>ST: get(session_id)
    ST->>ST: memory hit? else SELECT + load messages
    A->>A: 404 if missing OR session.user_id set and != caller
    A-->>CH: {session_id, title, messages, citations}
    CH->>CH: replace messages state, set sessionId

    SB->>CH: onRenameSession(id, title) inline edit
    CH->>CH: optimistic setSessions, updates UI first
    CH->>A: PATCH /sessions/{id} {title max 120}
    A->>ST: rename_session(id, title, user_id)
    ST->>DB: UPDATE WHERE session_id AND user_id
    ST-->>A: rowcount > 0
    A-->>CH: 200 or 404 not found or permission denied

    SB->>CH: onDeleteSession(id)
    CH->>CH: optimistic filter out of list
    CH->>A: DELETE /sessions/{id}
    A->>ST: delete_session(id, user_id)
    ST->>DB: DELETE messages via subquery on user_id
    ST->>DB: DELETE sessions WHERE session_id AND user_id
    ST-->>A: rowcount > 0
```

**Why**

- **Ownership is enforced in the SQL `WHERE`, not in a Python `if`.** `rename_session`
  and `delete_session` both filter on `user_id` inside the statement and return
  `rowcount > 0`, so a mismatched owner is indistinguishable from a missing row —
  one code path, no IDOR gap, and the 404 leaks nothing.
- **Messages are deleted before sessions**, via a subquery that re-checks ownership,
  because declared FKs are not enforced and there is no `ON DELETE CASCADE`
  (see [03-data-model.md](03-data-model.md) §1).
- **Rename and delete are optimistic in the UI**, which is why they feel instant.
  ⚠ Neither rolls back the local state if the request fails.
- ⚠ **`GET /sessions/{id}` allows an anonymous session to be read by any
  authenticated user**: the guard is `session.user_id and session.user_id != caller`,
  so when `user_id` is `NULL` the check short-circuits and access is granted. Guessing
  a uuid4 is impractical, but the rule should be "owner, or nobody".
- ⚠ **`rename_session` updates the in-memory copy before the DB**, and does not
  revert it if `rowcount` is 0.

---

## §7 Admin metrics (P9)

```mermaid
sequenceDiagram
    autonumber
    participant AD as Admin.jsx
    participant A as api.py GET /admin/logs
    participant AU as get_admin_user
    participant DB as query_logs

    AD->>A: GET /admin/logs + Bearer
    A->>AU: get_current_user_required then email check
    AU->>AU: split ADMIN_EMAILS env on comma, lower, strip
    alt token invalid or absent
        AU-->>AD: 401 Authentication required or token expired
    else email not in allow-list
        AU-->>AD: 403 Forbidden. Admin access required.
    else authorised
        A->>DB: COUNT(*)
        A->>DB: COUNT(*) WHERE was_cached = 1
        A->>DB: AVG(response_time_ms)
        A->>DB: SELECT * ORDER BY timestamp DESC LIMIT 100
        A-->>AD: {metrics, logs}
        AD->>AD: render hit rate, avg latency, recent questions
    end
```

**Why**

- **Admin is an env-var allow-list, not a DB role.** No `is_admin` column, no role
  table — for a two-person non-profit tool, `ADMIN_EMAILS` is the whole
  authorisation model, and it cannot be escalated by writing to the database.
- **Three aggregates computed in SQLite, not in Python**, so the 100-row log slice
  and the metrics are independent — metrics stay correct as the table grows.
- ⚠ The dependency ladder means a **non-admin gets 403 while a stranger gets 401**,
  which confirms to an authenticated user that the endpoint exists. Acceptable here.
- ⚠ `metrics` are computed over **all time**, with no date filter, so the hit rate
  drifts toward a lifetime average and stops reflecting recent behaviour.
