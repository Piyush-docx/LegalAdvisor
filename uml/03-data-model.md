# 03 — Data Model

Every table in `legal.db`, then every shape that crosses the wire. Schema source:
[db.py](../src/db.py) `init_db()`. See [README.md](README.md) for problem IDs.

---

## §1 ER — all six tables

```mermaid
erDiagram
    users {
        TEXT id PK "uuid4"
        TEXT email UK "normalised lower, stripped"
        TEXT created_at "ISO-8601 UTC"
    }
    otps {
        INTEGER id PK "autoincrement"
        TEXT email "idx_otps_email, NOT a FK"
        TEXT otp_code "6 digits, PLAINTEXT"
        TEXT expires_at "now + 10 min"
        INTEGER used "0 or 1, default 0"
    }
    sessions {
        TEXT session_id PK "uuid4"
        TEXT user_id FK "NULL = anonymous, idx_sessions_user"
        TEXT title "auto from 1st user message"
        TEXT created_at
        TEXT last_active_at "drives 24h TTL"
        TEXT last_context_text "retrieved law, reused on FOLLOW_UP"
        TEXT last_citations "JSON array of Citation"
        TEXT last_query
    }
    messages {
        INTEGER id PK "autoincrement"
        TEXT session_id FK "idx_messages_session"
        TEXT role "user or assistant"
        TEXT content
        TEXT timestamp
    }
    query_cache {
        TEXT search_query PK "the REWRITTEN query, not the question"
        TEXT context_text "extracted law"
        TEXT citations "JSON array of Citation"
        TEXT llm_answer "pre-safety-layer text"
        TEXT created_at "written, never read"
    }
    query_logs {
        INTEGER id PK "autoincrement"
        TEXT timestamp
        TEXT question "RAW citizen text"
        TEXT intent "RouteIntent.name"
        INTEGER was_cached "0 or 1"
        INTEGER response_time_ms "perf_counter delta"
    }

    users ||--o{ sessions : "owns, or NULL"
    sessions ||--o{ messages : "contains"
```

`otps`, `query_cache` and `query_logs` are intentionally unlinked — each for a
different reason, below.

**Why the schema looks like this**

- **`query_cache.search_query` is the primary key, and it is the *rewritten*
  query** (**P7**). "my landlord kept my deposit" and "landlord won't return
  security deposit" both normalise through `rewrite_query` to the same
  `"security deposit" ANDD tenancy ANDD refund doctypes: laws`, so they share one
  row. The LLM is doing the work an embedding model would otherwise do.
  ⚠ This is **exact string matching**, not semantic caching — the docs call it
  semantic; the code is `WHERE search_query = ?`. Do not overclaim it.
- **`query_cache` stores `llm_answer` pre-safety-layer.** The disclaimer and
  attribution are re-attached on every hit by `attach_disclaimer_and_attribution`,
  so a change to the disclaimer text takes effect immediately for cached answers
  too (**P8**). Caching the finished string would have frozen the legal text.
- **`query_logs` has no `user_id` column, by design** (**P9**). The admin
  dashboard answers "what is this costing and how fast is it" without building a
  per-citizen surveillance log.
  ⚠ But `question` is stored **raw**, and legal questions are exactly where people
  disclose their circumstances. Anonymous ≠ non-identifying. Truncating, or storing
  only the rewritten query, would keep the metrics and drop the exposure.
- **`otps.email` is a plain column, not a FK**, because an OTP is issued *before*
  the user exists — `verify_otp` creates the `users` row on first successful
  verification (**P6**). A FK would make first-time signup impossible.
- **`last_citations` is JSON in a TEXT column**, not a `citations` table. It is
  always read and written as a whole list alongside its session, never queried by
  field, so normalising it would buy nothing.
- **`created_at` on `query_cache` is written and never read.** It exists so a TTL
  can be added without a migration — see [05-state-machines.md](05-state-machines.md) §5.

### ⚠ Schema-level defects, drawn where they live

```mermaid
flowchart LR
    subgraph d1["Declared FKs are NOT enforced"]
        a1["init_db declares<br/>FOREIGN KEY clauses"] --> a2["but SQLite needs<br/>PRAGMA foreign_keys = ON<br/>and nothing sets it"]
        a2 --> a3["no ON DELETE CASCADE either, so<br/>delete_session deletes messages<br/>manually, in the right order"]
    end
    subgraph d2["Rows that are never reclaimed"]
        b1["cleanup_expired() only<br/>evicts _memory_sessions"] --> b2["returns the MEMORY count"]
        b1 --> b3["sessions and messages rows<br/>past the 24h TTL stay forever;<br/>get() hides them, DELETE never runs"]
        b4["used and expired otps rows<br/>are never purged"]
    end
    subgraph d3["OTPs at rest"]
        c1["otp_code stored as plaintext"] --> c2["DB read = account takeover<br/>for any pending code"]
        c1 --> c3["should be a hash;<br/>verify compares hashes"]
    end
    classDef bad fill:#fdecea,stroke:#d93025,stroke-width:2px
    class a2,a3,b3,b4,c2 bad
```

---

## §2 Wire contracts — what crosses the HTTP boundary

Pydantic models in [api.py](../src/api.py). Validation is the point: a bad body
fails at the edge with a 422 before any paid API call is made.

**Request bodies** — validated at the edge, so a bad body 422s before any paid
API call is made.

```mermaid
classDiagram
    class AskRequest {
        +str question "min_length=1"
        +Optional~str~ session_id "absent on first turn"
    }
    class SendOtpRequest {
        +str email "min_length=3"
    }
    class VerifyOtpRequest {
        +str email "min_length=3"
        +str otp "min_length=4, codes are always 6"
    }
    class RenameSessionRequest {
        +str title "min_length=1, max_length=120"
    }
```

**Response bodies**

```mermaid
classDiagram
    class AskResponse {
        +str answer "answer + sources + disclaimer + attribution"
        +str session_id "always returned, even if none was sent"
    }
    class SendOtpResponse {
        +str message "never reveals the code"
    }
    class VerifyOtpResponse {
        +str token "itsdangerous signed"
        +UserInfo user
        +int expires_in "86400"
    }
    class UserInfo {
        +str id
        +str email
    }
    VerifyOtpResponse "1" *-- "1" UserInfo
```

**Why these shapes**

- **`AskResponse.session_id` is always returned, even when the client sent none.**
  That is how an anonymous first turn becomes a continuable conversation: the
  server mints the id, the client stores it and echoes it back. It is the entire
  session-continuity protocol.
- **`SendOtpResponse` carries only a message.** It deliberately does not say
  whether the email belongs to an existing user, so the endpoint is not an account
  enumeration oracle.
  ⚠ It also returns success on a delivery failure path (SMTP errors are caught and
  logged inside `send_otp`), which is good for enumeration and bad for debugging.
- **`VerifyOtpRequest.otp` is `min_length=4` while codes are always 6 digits.**
  Loose validation; harmless, but it means a 4-char guess reaches the DB lookup.
- **`expires_in` is sent so the client can pre-empt expiry.** `AuthContext` stores
  `legal_auth_expires_at` and logs out locally rather than waiting for a 401.

### Endpoints without a response model

```mermaid
flowchart TB
    subgraph typed["Typed — appear in OpenAPI with a schema"]
        t1["POST /auth/send-otp"]
        t2["POST /auth/verify-otp"]
        t3["POST /ask"]
    end
    subgraph untyped["Untyped — return bare dicts, no response_model"]
        u1["GET /auth/me"]
        u2["GET /sessions"]
        u3["GET /sessions/{id}"]
        u4["PATCH /sessions/{id}"]
        u5["DELETE /sessions/{id}"]
        u6["GET /admin/logs"]
    end
    untyped --> note["/docs shows no shape for these,<br/>and nothing stops a field being<br/>renamed out from under client.js"]
    classDef warn fill:#fef7e0,stroke:#f9ab00,stroke-width:2px
    class untyped,u1,u2,u3,u4,u5,u6,note warn
```

The un-modelled shapes, as `client.js` actually consumes them:

| Endpoint | Returned keys |
|---|---|
| `GET /auth/me` | `user` → the token payload `{email, user_id}` |
| `GET /sessions` | `sessions[]` → `{session_id, title, created_at, last_active_at}`, plus `limit`, `offset` |
| `GET /sessions/{id}` | `session_id`, `title`, `messages[]` → `{role, content, timestamp}`, `citations[]` |
| `PATCH /sessions/{id}` | `message`, `title` |
| `DELETE /sessions/{id}` | `message` |
| `GET /admin/logs` | `metrics` → `{total_queries, cache_hit_rate, avg_response_time_ms}`, `logs[]` → full `query_logs` rows |

⚠ Note the asymmetry: `GET /auth/me` returns `{email, user_id}` from the token,
while `VerifyOtpResponse.user` returns `{id, email}`. Same concept, two key names.
