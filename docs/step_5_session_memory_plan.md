# Implementation Plan — Step 5: Session Memory & Query Router

Add multi-turn conversation memory and an intelligent router to differentiate between chit-chat, follow-up legal questions, and new legal questions. This optimizes API billing by preventing unnecessary Indian Kanoon queries for casual conversation and reusing retrieved legal context on follow-up questions.

---

## Proposed Architecture

```
User Message (+ optional session_id)
        │
        ▼
Session Store (get or create session)
        │
        ▼
Router / Intent Classifier (Gemini 2.5 Flash)
 ├── CHITCHAT
 │     └── Direct conversational response (polite guide to Indian law help)
 │         [0 Indian Kanoon calls]
 │
 ├── FOLLOW_UP (Session has existing context)
 │     ├── Can existing context answer?
 │     │     ├── YES: Generate answer directly using session context & citations
 │     │     │   [0 Indian Kanoon calls]
 │     │     └── NO: Rewrite query blending previous question + new follow-up
 │     │         └── Search IKanoon & update session context
 │
 └── NEW_QUERY (Fresh legal question or topic shift)
       └── Rewrite query for Indian Kanoon
       └── Search & fetch documents
       └── Update session context & citations
       └── Generate answer
        │
        ▼
Update Session History & Return { answer, session_id }
```

---

## User Review Required

> [!IMPORTANT]
> **API Cost & Latency Optimization**:
> Indian Kanoon queries are prepaid with strict rate limits and per-request costs (~₹0.50–0.90 per search + doc fetches). The router ensures that greetings, thanks, clarifications, and context-covered follow-ups cost **₹0 in IKanoon API fees**.

> [!NOTE]
> **Session Persistence**:
> For Step 5, sessions are managed via an in-memory session store with automatic TTL (time-to-live) expiration. In Step 6, this will be persisted in PostgreSQL as specified in [p.md](file:///Users/piyushdokania/legal/p.md).

---

## Proposed Changes

### 1. Session Storage Layer

#### [NEW] [src/session.py](file:///Users/piyushdokania/legal/src/session.py)
- `Session` data model:
  - `session_id: str` (UUID4)
  - `created_at: datetime`
  - `last_active_at: datetime`
  - `messages: list[dict]` (role: "user" | "assistant", content: str)
  - `last_context_text: str | None` (the substantive legal text of retrieved docs)
  - `last_citations: list[Citation]`
  - `last_query: str | None`
- `SessionStore`:
  - `get(session_id: str) -> Session | None`
  - `create() -> Session`
  - `get_or_create(session_id: str | None) -> Session`
  - `save(session: Session) -> None`
  - `cleanup_expired(ttl_seconds: int = 3600) -> int`

---

### 2. Intent Routing Layer

#### [NEW] [src/router.py](file:///Users/piyushdokania/legal/src/router.py)
- `RouteIntent` enum: `CHITCHAT`, `FOLLOW_UP`, `NEW_QUERY`.
- `classify_intent(message: str, session: Session) -> RouteIntent`:
  - If session has no prior context, fast-check if it's a greeting/meta query (`CHITCHAT`) or a legal question (`NEW_QUERY`).
  - If session has prior context and message refers to the ongoing topic (e.g. "what if the agreement was oral?", "how much time do they have?"), classify as `FOLLOW_UP`.
- `generate_chitchat_response(message: str, session: Session) -> str`:
  - Generates a warm, professional response clarifying what legal topics the assistant covers, inviting the user to ask a specific Indian legal question.

---

### 3. Pipeline Refactoring

#### [MODIFY] [src/pipeline.py](file:///Users/piyushdokania/legal/src/pipeline.py)
- Refactor `answer_question` to accept optional `session_id: str | None`:
  ```python
  def answer_question(question: str, session_id: str | None = None) -> tuple[str, str]:
      # Returns (answer_text, session_id)
  ```
- Workflow:
  1. Retrieve or create `session`.
  2. Run `classify_intent`.
  3. If `CHITCHAT`: return friendly explanation without retrieval.
  4. If `FOLLOW_UP`:
     - Test if `session.last_context_text` can answer the follow-up.
     - If so, generate answer from existing context.
     - If not, rewrite query blending prior turn context and fetch new documents.
  5. If `NEW_QUERY`:
     - Run standard search and retrieval, update `session.last_context_text` and `session.last_citations`.
  6. Append turn to `session.messages` and update session store.
  7. Attach safety disclaimer and attribution.

#### [MODIFY] [src/retrieval/rewrite.py](file:///Users/piyushdokania/legal/src/retrieval/rewrite.py)
- Extend `rewrite_query` to support optional `conversation_context: str | None` so follow-up queries carry over the relevant legal domain and terms.

---

### 4. API Endpoints

#### [MODIFY] [src/api.py](file:///Users/piyushdokania/legal/src/api.py)
- Update `AskRequest`:
  ```python
  class AskRequest(BaseModel):
      question: str = Field(min_length=1)
      session_id: str | None = None
  ```
- Update `AskResponse`:
  ```python
  class AskResponse(BaseModel):
      answer: str
      session_id: str
  ```
- Backwards compatible: if client doesn't supply `session_id`, a new session is created automatically.

---

### 5. Frontend Chat UI

#### [MODIFY] [frontend/src/api/client.js](file:///Users/piyushdokania/legal/frontend/src/api/client.js)
- Update `askQuestion(question, sessionId)` to send `session_id` and return `{ answer, sessionId }`.

#### [MODIFY] [frontend/src/pages/Chat.jsx](file:///Users/piyushdokania/legal/frontend/src/pages/Chat.jsx)
- Track `sessionId` in React state across conversation turns.
- Add a **"New Chat"** / "Clear Conversation" button in the chat header allowing citizens to start a fresh session at any time.
- Display visual indicators for follow-up turns if applicable.

---

### 6. Tests

#### [NEW] [tests/test_session.py](file:///Users/piyushdokania/legal/tests/test_session.py)
- Test session creation, retrieval, context storage, message history, and TTL cleanup.

#### [NEW] [tests/test_router.py](file:///Users/piyushdokania/legal/tests/test_router.py)
- Test intent classification (`CHITCHAT`, `FOLLOW_UP`, `NEW_QUERY`).
- Test chit-chat response generator.

#### [MODIFY] [tests/test_pipeline.py](file:///Users/piyushdokania/legal/tests/test_pipeline.py)
- Test pipeline handling of chit-chat (verifying 0 IKanoon calls).
- Test pipeline handling of follow-up (verifying context reuse and 0 IKanoon calls when context suffices).
- Test pipeline handling of fresh legal queries.

#### [MODIFY] [tests/test_api.py](file:///Users/piyushdokania/legal/tests/test_api.py)
- Verify `session_id` is accepted, propagated, and returned in `POST /ask`.
- Verify backward compatibility for requests without `session_id`.

---

## Verification Plan

### Automated Tests
1. Run pytest using the configured Python 3.13 interpreter:
   ```bash
   /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest
   ```
   Ensure all existing 37 tests + new tests pass.
2. Run frontend build and linter:
   ```bash
   cd frontend && npm run lint && npm run build
   ```

### Manual / Integration Verification
1. Launch backend and frontend using [run.sh](file:///Users/piyushdokania/legal/run.sh).
2. Test Chit-chat: Type "Hello, who are you?" $\rightarrow$ confirm instant friendly response without calling IKanoon search.
3. Test Legal Question: Type "My landlord won't return my security deposit" $\rightarrow$ confirm full RAG response with citations.
4. Test Follow-up: Type "What if I didn't have a written agreement?" $\rightarrow$ confirm follow-up handled within session.
5. Test "New Chat" button: resets `sessionId` and clears conversation.
