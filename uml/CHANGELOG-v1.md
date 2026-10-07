**This is v1 — there is no previous version of this page to sit beside.**

When v2 is generated it must be added *next to* this file, never over it. The old
page records what was believed at the time, which is evidence; overwriting it
destroys that.

That leaves one honest comparison to make now. The project already has a prior
design record: [p.md](../p.md), written before implementation. It describes a
system that was partly built as specified and partly not. Treating `p.md` as
"v-old" and the code as "built" is exactly the diff this section exists for — and
it is the most useful thing in this document, because **six items below are
specified, believed to exist, and absent from the code.**

### v-old (p.md, as designed) vs built (the code, today)

| # | p.md specified | Built | Verdict |
|---|---|---|---|
| 1 | Cache store in **PostgreSQL** | SQLite `query_cache` table | **Changed.** Zero-ops was the right prototype trade; Postgres remains the production target. |
| 2 | Session store holds context "**briefly**", in memory | In-memory dict *and* SQLite write-through, 24 h TTL, 200-session LRU | **Exceeded.** Memory-only lost every conversation on restart (**P5**). |
| 3 | LLM is **Claude or GPT** — `claude-sonnet-4-6`, `x-api-key`, `api.anthropic.com` | **Gemini 2.5 Flash** via `google-genai` | **Changed.** The swap cost nothing, which is the clearest proof the "no legal knowledge in the model" principle held. |
| 4 | Prompt: "**You may only answer using the RETRIEVED TEXT**… If the text doesn't answer the question, say so" | "Use **your general knowledge** of Indian law… use the RETRIEVED TEXT as **supportive references**" | ⚠ **Reversed.** The single most consequential drift. Groundedness was traded for completeness, presumably because retrieval quality was uneven. Nothing records the decision. |
| 5 | Query construction in **3 stages**: classify domain → extract keywords → assemble `formInput` | **1** LLM call, `rewrite_query`, that does all three | **Simplified.** One call is cheaper and the prompt still forces an area-of-law term (**P1**). |
| 6 | `build_context` fetches top **2–3** docs, sequentially | Top **5**, fetched in parallel | **Exceeded** (**P4**). |
| 7 | Context = "**cleaned full text** of top docs" | `Issue` / `Facts` / `Conclusion` paragraphs only | **Exceeded** (**P2**), ~90% fewer tokens. |
| 8 | Cache check placed **before** `ikanoon_search` | Cache check is before search, but **after** `rewrite_query` | **Changed.** Deliberate: the rewritten query is the normalisation key (**P7**). The cost is that a cache hit still makes one Gemini call. |
| 9 | "**Filter by relevance** — drop docs that don't match domain" | `select_top_docs` takes the top 5 in raw rank order, no filter, no rerank | ⚠ **Not built.** |
| 10 | "**Headline snippets** → used for quick preview / confidence check" | `SearchDoc.headline` is parsed and never read | ⚠ **Not built.** |
| 11 | Safety layer runs a "**citation check**" | `attach_disclaimer_and_attribution` appends citations; it verifies nothing | ⚠ **Not built.** |
| 12 | "**Harm-signal check** runs on every message, regardless of topic" (§9.4, listed as *do not skip*) | No such check exists anywhere in `src/` | ⚠ **Not built**, and it is the one item p.md marks as non-optional. |
| 13 | Production: "prefer a real **secrets manager** over a `.env` file" | `.env` via `--env-file`, plus an ephemeral-key fallback | ⚠ **Not built**, correctly deferred — but see [01-hld](01-hld.md) §3, the fallback silently invalidates every token on restart. |
| 14 | Attribution "**visible to users** somewhere prominent" (licence condition) | Appended to every answer **and** an About page | **Built** (**P8**). |
| 15 | Both API keys **backend-only**, never in frontend JS | Nothing in `frontend/` reads either key | **Built.** The one security invariant that held completely. |

### Built although p.md never specified it

These arrived across Steps 5, 6 and 8 and the accounts work. p.md predates all of
them, so their absence from it is not drift:

- The three-way **intent router** and the chit-chat fast path (**P3**) — the
  largest single cost saving in the system.
- **Email-OTP accounts**, chat history, and conversation rename/delete (**P6**).
- **`query_logs`** and the admin dashboard (**P9**).
- The light/dark **token system** (**P10**).

### What a v2 of this page should show

1. Whether #4 was a decision or an accident, recorded either way.
2. #12 built, or p.md amended to stop claiming it.
3. A TTL on `query_cache` — see [05-state-machines](05-state-machines.md) §5.
4. Rate limiting on the OTP endpoints — see [04-sequences](04-sequences.md) §5.
