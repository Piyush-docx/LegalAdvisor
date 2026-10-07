# 05 — State Machines

Every entity in the system whose status has **more than two values**. Two-valued
flags are omitted; they are documented by the schema in
[03-data-model.md](03-data-model.md).

---

## §1 OTP lifecycle

Backed by `otps.used` plus `otps.expires_at` — two columns encoding four states.

```mermaid
stateDiagram-v2
    [*] --> Issued : generate_otp<br/>secrets.randbelow(900000)+100000
    Issued --> Pending : INSERT used=0<br/>expires_at = now + 10 min
    Pending --> Consumed : verify_otp matched<br/>UPDATE used=1
    Pending --> Expired : expires_at < now<br/>checked in Python, not SQL
    Pending --> Superseded : a newer row for the same email<br/>ORDER BY id DESC LIMIT 1 picks the new one
    Consumed --> [*] : row stays forever
    Expired --> [*] : row stays forever
    Superseded --> Expired : still selectable until<br/>its own 10 min elapses

    note right of Pending
        UNBOUNDED GUESSES. No attempt
        counter, no rate limit. 10 minutes
        against 900k codes.
    end note
    note right of Superseded
        Not a real transition: nothing marks
        the old row. It is only shadowed by
        ORDER BY id DESC, and remains
        independently verifiable.
    end note
```

**Why it looks like this**

- **`used=1` is set inside the same `with conn:` block as the user lookup**, so a
  code is burned atomically and cannot be replayed even if signup then fails.
- **Expiry is compared in Python** (`row["expires_at"] < now_iso`) rather than in the
  `WHERE` clause. ISO-8601 UTC strings sort lexicographically, so either works;
  doing it in Python is what lets the code return the same `None` for both wrong and
  expired, keeping the two indistinguishable to a caller (**P6**).
- **Nothing reaps `Consumed` or `Expired` rows.** `otps` grows forever.

**⚠ Defects visible in this machine**

1. `Pending` has no attempt ceiling — the single most exploitable gap in the system.
2. `Superseded` is not a real state. Requesting a new code does **not** invalidate
   the previous one; both stay verifiable until each expires. Widening the attack
   window is the opposite of what a resend should do.
3. `otp_code` is plaintext at rest, so any DB read hands over every `Pending` code.

**Fix:** add `attempts INTEGER DEFAULT 0`, cap it, throttle `send-otp` per email,
`UPDATE otps SET used=1 WHERE email=? AND used=0` before inserting a new code, and
store a hash instead of the code.

---

## §2 Session lifecycle

Two storage tiers and a TTL, so "does this session exist?" has four answers.

```mermaid
stateDiagram-v2
    [*] --> Created : SessionStore.create<br/>uuid4, title "New Chat"

    state Live {
        [*] --> Hot
        Hot : In _memory_sessions AND SQLite<br/>reads never touch disk
        Warm : SQLite only<br/>next get() rehydrates into memory
        Hot --> Warm : _evict_if_needed<br/>over 200 sessions, oldest last_active_at
        Warm --> Hot : get() SELECT + rebuild Messages and Citations
    }

    Created --> Hot : save() write-through, P5
    Hot --> Hot : save() on every turn<br/>last_active_at refreshed

    Live --> Stale : now - last_active_at > 86400s
    Stale --> [*] : get() returns None.<br/>ROWS ARE NEVER DELETED
    Live --> Deleted : delete_session(id, user_id)<br/>messages first, then session
    Deleted --> [*] : rowcount > 0

    note right of Stale
        TTL is read-time only. cleanup_expired()
        clears the memory dict and returns that
        count. No DELETE ever runs.
    end note
```

**Why it looks like this**

- **Write-through, not write-back** (**P5**). Step 5 shipped memory-only and lost
  everything on restart; SQLite became the record while the dict stayed as the read
  path. `save()` writes both, every turn.
- **Eviction is LRU by `last_active_at`, capped at 200.** Bounds memory without a
  background thread — eviction happens inline on `save()`.
- **Demotion `Hot → Warm` is lossless**, which is the whole point of the tier: an
  evicted session rehydrates on next `get()`, including its `last_context_text`, so
  a follow-up after eviction still costs ₹0 in IKanoon fees (**P3**).
- **TTL is checked in `get()` in both tiers**, so an expired session is invisible
  even though its row is intact.

**⚠** `Stale` is a leak, not a state: rows accumulate forever, holding
`last_context_text` — retrieved legal text — for conversations nobody can reach.
`cleanup_expired()` reads as a reaper and is not one. And because the TTL is
read-time, a session stale for a year is unreachable but never purged.

### §2b Anonymous-to-owned transition

```mermaid
stateDiagram-v2
    [*] --> Anonymous : POST /ask with no Bearer<br/>user_id = NULL
    Anonymous --> Owned : get_or_create sees session_id + user_id<br/>and session.user_id is falsy
    Owned --> Owned : subsequent turns
    Anonymous --> Orphaned : user never logs in
    note right of Anonymous
        Readable by ANY authenticated caller:
        GET /sessions/{id} guard is
        "session.user_id and != caller",
        which short-circuits on NULL.
    end note
    note right of Orphaned
        Never listed by /sessions
        (filters on user_id), never
        deleted. Permanently unreachable.
    end note
```

**Why:** a citizen can ask a question without an account, then sign in and keep the
conversation — the adoption happens in `get_or_create`, which back-fills `user_id`
and saves. That is a real product decision: the tool must work for someone who will
not create an account (**P6**).

**⚠** Adoption is one-way and unguarded: whoever presents the session id first
claims it. Combined with the `NULL` short-circuit above, an anonymous session id is
a bearer token with no expiry beyond the 24 h TTL.

---

## §3 Auth token

```mermaid
stateDiagram-v2
    [*] --> Signed : create_auth_token<br/>URLSafeTimedSerializer.dumps<br/>payload email + user_id, salt auth-token
    Signed --> Valid : client stores it
    Valid --> Expired : loads(max_age=86400) raises<br/>SignatureExpired
    Valid --> Rejected : bad signature or tampering<br/>BadSignature
    Valid --> Orphaned : server restart WITHOUT AUTH_SECRET_KEY<br/>new random key, every token fails
    Expired --> [*] : verify_auth_token returns None -> 401
    Rejected --> [*] : returns None -> 401
    Orphaned --> [*] : returns None -> 401

    note right of Valid
        STATELESS. No server-side row,
        so there is nothing to revoke.
        Logout is client-side only.
    end note
```

**Why it looks like this**

- **Stateless signed tokens, not session rows** (**P6**). No lookup per request, and
  expiry is enforced by `max_age` at verification. That is what lets three FastAPI
  dependencies (`optional`, `required`, `admin`) layer with zero DB cost.
- **All failure modes collapse to `None`.** `verify_auth_token` catches bare
  `Exception`, so expired, tampered and orphaned are one 401 — no oracle telling an
  attacker which it was.
- **`salt="auth-token"`** scopes the signature, so a token could never be replayed
  against a different serializer purpose added later.

**⚠** Two consequences of statelessness worth naming out loud:

1. **No revocation.** A stolen token is valid for its full 24 h. Logout clears
   `localStorage` and nothing else.
2. **`Orphaned` is reachable by accident.** Without `AUTH_SECRET_KEY`, `auth.py`
   generates an ephemeral key and logs a warning. Every restart logs everyone out,
   and multiple workers would each sign with a different key.

---

## §4 Frontend auth state (AuthContext)

Three fields — `user`, `token`, `isLoading` — encoding four states.

```mermaid
stateDiagram-v2
    [*] --> Rehydrating : mount, isLoading = true<br/>read legal_auth_token, _user, _expires_at
    Rehydrating --> LoggedOut : no token, or expires_at in the past
    Rehydrating --> Verifying : token present and not locally expired
    Verifying --> LoggedIn : GET /auth/me 200<br/>refresh cached user
    Verifying --> LoggedOut : 401 -> clear all three keys
    LoggedOut --> LoggedIn : login(token, user, expiresAt) from LoginModal
    LoggedIn --> LoggedOut : logout() removes all three keys
    LoggedIn --> LoggedOut : any 401 from client.js

    note right of Rehydrating
        isLoading exists so the UI does not
        flash "Sign In" for a user who is
        in fact logged in.
    end note
```

**Why:** `legal_auth_expires_at` is stored specifically so the client can decide it
is logged out **without** a network round trip — the local check runs first, and
`/auth/me` only confirms a token that still looks live. Server truth still wins.

**⚠** The token lives in `localStorage`, so any XSS reads it; and `/admin` is not
route-guarded, so a non-admin reaching it sees the 403 error text rather than a
redirect.

---

## §5 Cache entry — the machine that is missing states

Drawn to show the **absence**. Solid = built. Dashed = `PLANNED`, not implemented.

```mermaid
stateDiagram-v2
    [*] --> Absent
    Absent --> Fresh : cache_query, INSERT OR REPLACE<br/>created_at stamped
    Fresh --> Fresh : served on every matching rewritten query,<br/>forever, P7
    Fresh --> Fresh : INSERT OR REPLACE overwrites<br/>only if the same query is recomputed

    Fresh --> Stale : PLANNED, now - created_at > TTL
    Stale --> Absent : PLANNED, DELETE or recompute
    Fresh --> Absent : PLANNED, manual invalidation on amendment

    note right of Fresh
        THE ONLY REAL STATE.
        created_at is written and never read.
        Nothing expires. Nothing invalidates.
    end note
```

**Why this is the most consequential gap in the system**

The project's entire justification for RAG over fine-tuning is that *the law stays
current* ([p.md](../p.md) §1) — statutes get amended, BNS/BNSS/BSA replaced older
codes. An unbounded cache **reintroduces exactly the staleness that RAG was chosen
to avoid**. It is not an optimisation with a minor cost; it contradicts the premise.

`created_at` already exists, so the smallest honest fix is one clause:

```sql
SELECT ... FROM query_cache
WHERE search_query = ? AND created_at > ?   -- now - TTL
```

**⚠** Note also that a `Fresh` row is only refreshed when the same query is
recomputed — and it never will be, because the lookup succeeds first. Without a TTL
the row is not just long-lived, it is **immortal by construction**.

---

## §6 Chat send state (Chat.jsx)

```mermaid
stateDiagram-v2
    [*] --> Idle : empty composer, SAMPLE_PROMPTS shown
    Idle --> Sending : handleSend, trimmed non-empty<br/>isLoading = true, user message appended optimistically
    Sending --> Answered : askQuestion resolves<br/>append assistant message, store session_id
    Sending --> Failed : throw, setError with body.detail
    Failed --> Sending : retry
    Answered --> Idle : composer cleared
    Answered --> Regenerating : handleRegenerate<br/>drop last assistant, resend last user message
    Regenerating --> Answered : new assistant message
    Regenerating --> Failed : throw

    note right of Sending
        The user message is rendered before
        the server confirms, so the thread
        feels immediate.
    end note
```

**Why:** the optimistic append is what makes the UI feel like a chat rather than a
form. `session_id` from the **first** response is what turns a one-shot answer into a
conversation (see [04-sequences.md](04-sequences.md) §1).

**⚠** `Regenerate` re-sends the same question on the **same session**, so
`classify_intent` now sees the prior turns and may route it `FOLLOW_UP` — a
regenerated answer can come from reused context rather than a fresh retrieval. And
because the dropped assistant message was already persisted by `SessionStore.save`,
the `messages` table keeps both the discarded and the regenerated reply, while the
UI shows only the new one.
