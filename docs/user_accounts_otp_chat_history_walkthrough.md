# Walkthrough — User Accounts, Email OTP Login, 24h Session & Chat History

We implemented passwordless **Email OTP Authentication**, **24-hour persistent user sessions**, and a **Chat History sidebar** allowing citizens to view and resume previous legal conversations.

---

## What Was Implemented

### 1. SQLite Database Persistence ([src/db.py](file:///Users/piyushdokania/legal/src/db.py))
- Stores all data locally in `legal.db` without requiring external database services.
- Tables:
  - `users`: User identity (`id`, `email`, `created_at`).
  - `otps`: 6-digit one-time passwords (`email`, `otp_code`, `expires_at`, `used`).
  - `sessions`: Chat sessions linked to `user_id` with titles, context, and citations.
  - `messages`: Chronological conversation turns (`session_id`, `role`, `content`, `timestamp`).

### 2. Passwordless Email OTP & 24h Timed Tokens ([src/auth.py](file:///Users/piyushdokania/legal/src/auth.py))
- **`generate_otp(email)`**:
  - Creates a cryptographically secure 6-digit numeric OTP valid for 10 minutes.
  - Logs clearly to the terminal in development mode (`[AUTH DEV] OTP for user@example.com is: 123456`) and supports standard SMTP when credentials are provided in `.env`.
- **`verify_otp(email, code)`**:
  - Validates code, creates user if first login, and marks code used.
  - Issues signed auth token using `itsdangerous.URLSafeTimedSerializer` with **`max_age = 86400` (exactly 24 hours / 1 day)**.
- **FastAPI Dependencies**:
  - `get_current_user_optional`: Extracts user from `Authorization: Bearer <token>` if present.
  - `get_current_user_required`: Enforces valid 24h token for protected routes.

### 3. Persistent Session Store with History ([src/session.py](file:///Users/piyushdokania/legal/src/session.py))
- Links sessions to `user_id`.
- Automatically titles sessions from the citizen's first substantive question (e.g. *"My landlord won't return my security deposit"*).
- `list_user_sessions(user_id)`: Retrieves all past chats for the user sorted newest first.

### 4. API Endpoints ([src/api.py](file:///Users/piyushdokania/legal/src/api.py))
- `POST /auth/send-otp`: Sends 6-digit code.
- `POST /auth/verify-otp`: Verifies code and returns `{ token, user, expires_in: 86400 }`.
- `GET /auth/me`: Returns current user info if token is valid and unexpired.
- `GET /sessions`: Returns list of previous sessions for authenticated user.
- `GET /sessions/{session_id}`: Returns messages and citations for a specific past chat.
- `POST /ask`: Associates asked questions with authenticated user's account.

### 5. Frontend Authentication & State ([frontend/src/context/](file:///Users/piyushdokania/legal/frontend/src/context))
- **`AuthContext`** & **`useAuth`**:
  - Tracks `isLoggedIn`, `user`, `token`.
  - Persists token and expiration timestamp in `localStorage`.
  - Automatically cleans up and logs out after 24 hours.
- **`LoginModal` ([frontend/src/components/LoginModal.jsx](file:///Users/piyushdokania/legal/frontend/src/components/LoginModal.jsx))**:
  - Two-step flow: Enter Email $\rightarrow$ Enter 6-digit OTP.
  - Displays convenient dev OTP badge for frictionless testing.
- **Navbar ([frontend/src/App.jsx](file:///Users/piyushdokania/legal/frontend/src/App.jsx))**:
  - Displays user email badge and "Sign Out" button when logged in.
  - Displays "Sign In" button when guest.

### 6. Chat History Sidebar ([frontend/src/pages/Chat.jsx](file:///Users/piyushdokania/legal/frontend/src/pages/Chat.jsx))
- Sidebar lists all past conversations by title and date.
- Clicking any conversation restores its message history and citations into the active chat.
- "+ New Chat" button starts a fresh conversation.
- Guest users see an invitation to sign in to save their chats.
- Styled with modern, accessible CSS in [frontend/src/App.css](file:///Users/piyushdokania/legal/frontend/src/App.css).

---

## Verification & Test Results

### 1. Backend Test Suite (59 tests passed)
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest -v
```
- `tests/test_auth.py`: 3 passed (OTP generation, expiration, 24-hour token expiry)
- `tests/test_db.py`: 1 passed (SQLite persistence, session & message reloading)
- `tests/test_api.py`: 7 passed (OTP flow, Bearer token, session security)
- `tests/test_router.py`: 8 passed
- `tests/test_session.py`: 4 passed
- `tests/test_pipeline.py`: 4 passed
- Plus all 32 existing retrieval and prompt tests.
- **Total: 59 passed in 2.71s**

### 2. Frontend Build & Linter
```bash
cd frontend && npm run lint && npm run build
```
- **oxlint**: **0 warnings, 0 errors** across all 11 files.
- **Vite Build**: Production bundle generated in 123ms.
