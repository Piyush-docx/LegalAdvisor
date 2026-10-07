# Project Documentation Index

This directory contains technical specifications, implementation plans, and walkthroughs for the **Citizen Legal Help RAG** project.

---

## Documentation Files

| Document | Description |
|---|---|
| [Step 6: Query Caching Plan](file:///Users/piyushdokania/legal/docs/step_6_query_caching_plan.md) | Database schema and architecture for semantic caching of LLM-generated search queries to reduce IKanoon API costs. |
| [Step 6: Query Caching Walkthrough](file:///Users/piyushdokania/legal/docs/step_6_query_caching_walkthrough.md) | Implementation details for SQLite `query_cache`, pipeline refactoring, cache hit/miss logic, and test results. |
| [Step 8: Logging & Admin Plan](file:///Users/piyushdokania/legal/docs/step_8_admin_logs_plan.md) | Architectural plan for anonymized query logging and building a React-based Admin Dashboard. |
| [Step 8: Logging & Admin Walkthrough](file:///Users/piyushdokania/legal/docs/step_8_admin_logs_walkthrough.md) | Implementation details for `query_logs` SQLite table, pipeline latency timing, and secure Admin API. |
| [UI Redesign & Conversation Mgmt Plan](file:///Users/piyushdokania/legal/docs/ui_redesign_conversation_mgmt_plan.md) | Architectural overhaul for ChatGPT-quality UI, Light/Dark theme token system, and conversation lifecycle API. |
| [UI Redesign & Conversation Mgmt Walkthrough](file:///Users/piyushdokania/legal/docs/ui_redesign_conversation_mgmt_walkthrough.md) | Fix for dark-mode contrast bug, collapsible sidebar, search, inline rename/delete, message toolbar, and test results. |
| [User Accounts & Chat History Plan](file:///Users/piyushdokania/legal/docs/user_accounts_otp_chat_history_plan.md) | Technical architecture & design for Email OTP passwordless login, 24h auth token lifetime, SQLite persistence, and chat history. |
| [User Accounts & Chat History Walkthrough](file:///Users/piyushdokania/legal/docs/user_accounts_otp_chat_history_walkthrough.md) | Implementation details, database schema, auth endpoints, React AuthContext, LoginModal, and test results. |
| [Step 5: Session Memory & Query Router Plan](file:///Users/piyushdokania/legal/docs/step_5_session_memory_plan.md) | Multi-turn conversational context design, fast chit-chat detection, follow-up query rewriting, and context reuse. |
| [Step 5: Session Memory & Query Router Walkthrough](file:///Users/piyushdokania/legal/docs/step_5_session_memory_walkthrough.md) | Step-by-step walkthrough of router logic, token cost optimizations, and test suite validations. |
| [Phase 1: Guardrails Walkthrough](file:///Users/piyushdokania/legal/docs/phase_1_guardrails_walkthrough.md) | PII redaction, harm and prompt-attack checks, router guardrail intents, rate limits, budget, output notes, feedback endpoint. |
| [Phase 2: LLM Layer Walkthrough](file:///Users/piyushdokania/legal/docs/phase_2_llm_layer_walkthrough.md) | `src/llm.py`: task-based model chains, Groq/Gemini fallback, cooldowns, reasoning-model headroom. |
| [Phase 3: Postgres Walkthrough](file:///Users/piyushdokania/legal/docs/phase_3_postgres_walkthrough.md) | Neon PostgreSQL + pgvector, two-backend `src/db.py`, `src/store.py`, DB-backed budget, cache expiry. |
| [Switching the embedding model](file:///Users/piyushdokania/legal/docs/embedding_model_switch.md) | Settings, per-vector model tracking, and the resumable `scripts/reembed.py` procedure. |
| [Phase 4 Step D: Chunking Walkthrough](file:///Users/piyushdokania/legal/docs/phase_4_chunking_walkthrough.md) | Section-aware chunker for Acts and judgments, BM25 keyword ranking, real-data checks. |
| [Phase 4 Step E1: Cold Path Walkthrough](file:///Users/piyushdokania/legal/docs/phase_4_e1_walkthrough.md) | Query repair, relaxation ladder, document reranking, numbered chunk context, citation checks. |
| [Phase 4 Step E1b: Relevance Fixes Walkthrough](file:///Users/piyushdokania/legal/docs/phase_4_e1b_walkthrough.md) | Act-name search (tested first), central-Act preference, citation repair, figure check, fast failover, stricter evals. |
| [Phase 4 Step E2: Stored Tiers Walkthrough](file:///Users/piyushdokania/legal/docs/phase_4_e2_walkthrough.md) | Answer cache (reviewed only), stored-chunk answers, background indexing, admin review endpoints. |
| [Deployment Guide](file:///Users/piyushdokania/legal/docs/deployment_guide.md) | Render + Vercel + Neon step by step: concepts, config, smoke test, common problems. |
| [System Architecture & API Key Spec (p.md)](file:///Users/piyushdokania/legal/p.md) | Core foundational documentation covering RAG retrieval pipeline, Indian Kanoon API integration, Gemini LLM prompts, and compliance rules. |

---

## Quick Reference Commands

### Running Locally
To launch both the FastAPI backend (`http://localhost:8000`) and the Vite React frontend (`http://localhost:5173`):
```bash
./run.sh
```

### Running Backend Tests
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -v
```

### Running Frontend Linter & Build
```bash
cd frontend && npm run lint && npm run build
```
