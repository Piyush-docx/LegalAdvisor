# UML — Citizen Legal Help RAG

Diagrams as text, in Mermaid, so they diff and review like code. No toolchain
needed to change them: edit the fenced block, push, GitHub renders it.

---

## The one fact to read first

> **The system owns no legal corpus.** Every answer's law is fetched from the
> **Indian Kanoon API at request time**, and that API is **prepaid keyword
> search with no grace period** — when the balance hits zero it simply stops
> returning results ([p.md](../p.md) §7 Step 2, §10).

Almost every shape in these diagrams exists because of that one sentence. The
intent router, the LLM query rewriter, the structural text extractor and the
query cache are all consequences of it. Read a diagram without that fact and
the design looks over-engineered; read it with the fact and each box is a cost
or a correctness defence.

---

## Which diagram answers which question

| Question | Diagram |
|---|---|
| Who uses this, and what does it depend on that we don't own? | [01-hld.md](01-hld.md) §1 Context |
| What processes run, and what talks to what? | [01-hld.md](01-hld.md) §2 Containers |
| Where does it run today, and what would production need? | [01-hld.md](01-hld.md) §3 Deployment |
| Which Python module owns which responsibility? | [02-lld.md](02-lld.md) §1 Backend components |
| Which React component owns which state? | [02-lld.md](02-lld.md) §2 Frontend components |
| What are the objects that carry the design? | [02-lld.md](02-lld.md) §3 Classes |
| What tables exist, and how do they relate? | [03-data-model.md](03-data-model.md) §1 ER |
| What shapes cross the wire? | [03-data-model.md](03-data-model.md) §2 Wire contracts |
| What actually happens on a question, in order? | [04-sequences.md](04-sequences.md) §1–§4 |
| How does login work? | [04-sequences.md](04-sequences.md) §5 OTP |
| How does chat history work? | [04-sequences.md](04-sequences.md) §6 Conversation management |
| When does an OTP stop working? | [05-state-machines.md](05-state-machines.md) §1 |
| When does a session disappear? | [05-state-machines.md](05-state-machines.md) §2 |
| When does a cached answer go stale? | [05-state-machines.md](05-state-machines.md) §5 — it doesn't, and that's a defect |
| Why did this request cost ₹0 / ₹0.90? | [06-activity.md](06-activity.md) §1 |
| Which paragraphs of a judgment reach the LLM? | [06-activity.md](06-activity.md) §3 |

---

## Problem IDs

Where a shape exists because a simpler alternative failed or was priced out,
the diagram names the problem ID instead of restating the mechanism. Each ID
below cites the code or doc that records it.

| ID | Problem | What it forced | Evidence |
|---|---|---|---|
| **P1** | Indian Kanoon is a **keyword** engine with its own boolean syntax (`ANDD`), and citizens write everyday prose. Passing the raw question returns off-topic law. | LLM query-rewrite stage. Its prompt forces an area-of-law term because `"security deposit" ANDD refund` alone also matches contractor and government deposits. | [rewrite.py](../src/retrieval/rewrite.py) prompt rules |
| **P2** | Full judgments run **100K+ characters**, most of it judicial reasoning and precedent citations that a plain-language answer never uses. | Keep only `Issue` / `Facts` / `Conclusion` paragraphs. Cuts token cost ~90%. | [document.py](../src/retrieval/document.py) `SUBSTANTIVE_TAGS` comment |
| **P3** | Every IKanoon search + doc fetch costs **₹0.50–0.90**. Greetings and answerable follow-ups were paying it. | Three-way intent router, plus a regex fast path that answers 18 common greetings with **zero** LLM and zero IKanoon calls. | [step_5 plan](../docs/step_5_session_memory_plan.md) "API Cost & Latency Optimization" |
| **P4** | 5 document fetches at up to 30 s timeout each, run in series, dominate latency. | `ThreadPoolExecutor` fan-out; 5 I/O-bound calls collapse to ~1 round trip. | [context.py](../src/retrieval/context.py) comment |
| **P5** | A pure in-memory session store loses every conversation on restart, and Step 5 shipped with one. | Write-through: in-memory dict for speed, SQLite as the record. 200-session memory cap with LRU eviction. | [step_5 plan](../docs/step_5_session_memory_plan.md) "Session Persistence" note |
| **P6** | Passwords mean hashing, reset flows, breach exposure — for a non-profit tool where the account only holds chat history. | Passwordless 6-digit email OTP, then a stateless signed token. No password column exists. | [user_accounts plan](../docs/user_accounts_otp_chat_history_plan.md) |
| **P7** | Repeat questions across users re-paid IKanoon for identical law. | `query_cache` keyed on the **rewritten** query, so different phrasings that normalise to the same query share one row. Pre-seeded from `data/common_questions.json`. | [step_6 plan](../docs/step_6_query_caching_plan.md) |
| **P8** | A generation can omit the disclaimer or the attribution. Attribution is a **licence condition**, not a nicety. | Disclaimer, citations and "Powered by Indian Kanoon" are appended in code, after the LLM, on every path. | [safety.py](../src/generation/safety.py); [p.md](../p.md) §9 |
| **P9** | Nobody could see cache-hit rate, latency or spend. | `query_logs` row per request + `/admin/logs` + React Admin page. Logs record question, intent, cached flag and latency — **no user id**. | [step_8 plan](../docs/step_8_admin_logs_plan.md) |
| **P10** | Dark mode shipped with unreadable contrast. | CSS custom-property token system, one palette per theme, rather than per-component overrides. | [ui_redesign walkthrough](../docs/ui_redesign_conversation_mgmt_walkthrough.md) §1 |

---

## Conventions

- **Branch labels are the real return values in the code.** `CHITCHAT`,
  `FOLLOW_UP`, `NEW_QUERY` are `RouteIntent` members. `dict` / `None` is what
  `get_cached_query` actually returns. `True` / `False` is what
  `can_context_answer_followup` returns. No paraphrases — a diagram that renames
  things is a second vocabulary to maintain.
- **Dashed shapes and `PLANNED` labels are not built.** They appear because a
  diagram showing only what exists gets read as showing everything.
- **`⚠` marks a known defect**, not a future feature. Defects are drawn where
  they live so a reviewer meets them in context.

---

## Maintenance

- [`docs/architecture-v1.html`](../docs/architecture-v1.html) is generated **from**
  these files, never instead of them. A fix belongs in both, in the same commit.
  If they drift, `uml/` is right — it is the one under review.
- Render before committing. A block that does not parse is invisible on GitHub,
  and one that parses can still overlap into illegibility.
