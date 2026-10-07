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
