# Implementation Plan — User Accounts, Email OTP Login & 24h Chat History

Implement user accounts allowing citizens to log in via Email OTP (One-Time Password), receive a 24-hour authentication session, and browse/resume their previous chat conversations.

---

## Architecture Overview

```
Citizen Flow:
1. Citizen clicks "Sign In"
      │
      ▼
2. Enters Email → Backend sends 6-digit OTP (stored in DB with 10m expiry)
   • In dev: OTP is logged in console and returned in dev response
   • In prod: sent via SMTP if configured
      │
      ▼
3. Enters OTP → Backend verifies OTP & issues 24-hour signed Auth Token
      │
      ▼
4. Frontend stores Token in localStorage (expires in 24h)
      │
      ▼
5. User asks questions or views "My Chats":
   • Every question asked while logged in is tied to their account in the database
   • Chat History sidebar displays previous sessions (e.g. "Security deposit refund")
   • Clicking a past chat loads full message history and legal citations
   • Citizen can continue asking follow-ups in that chat or start a fresh one
```

---

## User Review Required

> [!IMPORTANT]
> **Email Delivery for Local Dev vs Production**:
> For local development, when an OTP is generated, it will be logged to the server terminal (`[AUTH] OTP for user@example.com is: 123456`) and returned in the API response in dev mode for immediate testing. If SMTP credentials (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`) are placed in `.env`, it will automatically send genuine emails via Python's built-in `smtplib`.

> [!NOTE]
> **Database Persistence**:
> To ensure user accounts, OTPs, and past chat sessions survive server restarts, we will use a self-contained SQLite database (`legal.db`) managed via Python's built-in `sqlite3`. This requires zero external server setup (no Postgres daemon needed locally), while adhering to clean relational tables that can easily point to Postgres later.

---

## Proposed Changes

### 1. Database Layer (Persistence)

#### [NEW] [src/db.py](file:///Users/piyushdokania/legal/src/db.py)
- SQLite database connection manager and schema initializer:
  - `users` table: `id` (UUID/text), `email` (unique), `created_at`
  - `otps` table: `id`, `email`, `otp_code`, `expires_at`, `used`
  - `sessions` table: `session_id`, `user_id` (nullable for guest sessions), `title`, `created_at`, `last_active_at`, `last_context_text`, `last_citations`, `last_query`
  - `messages` table: `id`, `session_id`, `role`, `content`, `timestamp`
- Helper queries to save, retrieve, and list sessions and messages.

---

### 2. Authentication Layer (OTP & 24h Tokens)

#### [NEW] [src/auth.py](file:///Users/piyushdokania/legal/src/auth.py)
- **OTP Generation & Verification**:
  - `generate_otp(email: str) -> str`: Generates secure 6-digit numeric OTP, stores in DB with 10-minute validity.
  - `verify_otp(email: str, code: str) -> bool`: Validates OTP against DB, marks as used.
  - `send_otp_email(email: str, code: str)`: Sends email if SMTP configured, otherwise logs to terminal.
- **24-Hour Token Management**:
  - `create_auth_token(email: str, user_id: str) -> str`: Generates signed timed token (`itsdangerous.URLSafeTimedSerializer`) containing `user_id` and `email` with `max_age=86400` (24 hours).
  - `verify_auth_token(token: str) -> dict | None`: Validates token and checks that it has not expired (> 24 hours).
- **FastAPI Dependency**:
  - `get_current_user_optional`: Extracts user from `Authorization: Bearer <token>` if present.
  - `get_current_user_required`: Enforces valid 24h auth token.

---

### 3. Session Store Upgrade

#### [MODIFY] [src/session.py](file:///Users/piyushdokania/legal/src/session.py)
- Connect `Session` and `SessionStore` to `src/db.py`:
  - `get_or_create(session_id: str | None, user_id: str | None = None) -> Session`
  - When a logged-in user starts a chat, link `user_id` to the session.
  - When `add_message` is called, persist message to database.
  - Automatically title sessions using the first substantive question (e.g., "Security deposit refund").
  - `list_user_sessions(user_id: str) -> list[dict]`: Fetch past sessions for the logged-in user.

---

### 4. API Endpoints

#### [MODIFY] [src/api.py](file:///Users/piyushdokania/legal/src/api.py)
- New Endpoints:
  - `POST /auth/send-otp`: Request OTP for given email.
  - `POST /auth/verify-otp`: Submit email + 6-digit OTP $\rightarrow$ returns `{ token, user, expires_in: 86400 }`.
  - `GET /auth/me`: Validate token and return current user info.
  - `GET /sessions`: List past chat sessions for authenticated user.
  - `GET /sessions/{session_id}`: Get full message history and citations of a specific session.
- Updated Endpoint:
  - `POST /ask`: Accepts optional `Authorization: Bearer <token>`, associating the session with the user.

---

### 5. Frontend Client & Auth Context

#### [MODIFY] [frontend/src/api/client.js](file:///Users/piyushdokania/legal/frontend/src/api/client.js)
- Add auth header support for all requests.
- Add API helper functions: `sendOtp`, `verifyOtp`, `fetchCurrentUser`, `fetchUserSessions`, `fetchSessionDetails`.

#### [NEW] [frontend/src/context/AuthContext.jsx](file:///Users/piyushdokania/legal/frontend/src/context/AuthContext.jsx)
- Manage `user`, `token`, `isLoggedIn`, `login(token, user)`, `logout()`.
- Automatically prune expired tokens (> 24 hours) from `localStorage`.

#### [NEW] [frontend/src/components/LoginModal.jsx](file:///Users/piyushdokania/legal/frontend/src/components/LoginModal.jsx)
- Polished, accessible modal:
  - Step 1: Enter email $\rightarrow$ "Send OTP"
  - Step 2: Enter 6-digit OTP $\rightarrow$ "Verify & Sign In" (with Resend OTP countdown)

---

### 6. Frontend Chat & Navbar UI

#### [MODIFY] [frontend/src/App.jsx](file:///Users/piyushdokania/legal/frontend/src/App.jsx)
- Wrap application with `AuthProvider`.
- Add user profile status and "Sign In" / "Sign Out" button to the top navigation.

#### [MODIFY] [frontend/src/pages/Chat.jsx](file:///Users/piyushdokania/legal/frontend/src/pages/Chat.jsx)
- Integrate with `AuthContext`.
- Add a collapsible **Chat History sidebar**:
  - Lists past conversations (showing title and date).
  - Clicking any past conversation loads its messages into the active chat.
  - "New Chat" button creates a fresh session.
  - If not logged in, shows a friendly prompt: *"Sign in to save and view your chat history across devices."*

#### [MODIFY] [frontend/src/App.css](file:///Users/piyushdokania/legal/frontend/src/App.css)
- Add styles for:
  - Login modal & OTP digit input fields
  - Chat layout with history sidebar (responsive drawer on mobile)
  - User badge and logout button in header

---

### 7. Automated Tests

#### [NEW] [tests/test_auth.py](file:///Users/piyushdokania/legal/tests/test_auth.py)
- Test OTP creation, expiration, and verification.
- Test 24-hour token creation and expiration check (`max_age=86400`).
- Test rejecting expired or forged tokens.

#### [NEW] [tests/test_db.py](file:///Users/piyushdokania/legal/tests/test_db.py)
- Test user creation, session persistence, message retrieval, and listing user sessions.

#### [MODIFY] [tests/test_api.py](file:///Users/piyushdokania/legal/tests/test_api.py)
- Test `POST /auth/send-otp`, `POST /auth/verify-otp`, `GET /auth/me`, `GET /sessions`.
- Test `POST /ask` with authentication token.

---

## Verification Plan

### Automated Tests
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -v
cd frontend && npm run lint && npm run build
```

### Manual Verification Flow
1. Start app with `./run.sh`.
2. Open `http://localhost:5173`.
3. Click "Sign In", enter email `citizen@example.com` $\rightarrow$ copy OTP from modal/console $\rightarrow$ verify.
4. Verify user badge appears in navbar with 24-hour session.
5. Ask question: "My landlord won't refund my security deposit" $\rightarrow$ response generated with citations.
6. Click "+ New Chat", ask: "What is the notice period for employee resignation?"
7. Check Chat History sidebar $\rightarrow$ both conversations appear.
8. Click the first conversation $\rightarrow$ previous messages and citations reload instantly.
9. Refresh browser $\rightarrow$ session remains logged in.
