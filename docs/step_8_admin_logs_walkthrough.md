# Walkthrough — Step 8: Logging & Admin Dashboard

We have implemented an anonymized query logging system to track what citizens are asking and how the backend is performing. We also built a minimalist Admin Dashboard to view these metrics securely.

---

## What Was Implemented

### 1. Database Schema & Logging (`src/db.py`)
- Created a `query_logs` SQLite table to track queries without storing personally identifiable user IDs.
- Tracks `timestamp`, `question`, `intent` (NEW_QUERY, FOLLOW_UP, CHITCHAT), `was_cached` (Hit/Miss), and `response_time_ms`.
- Added `log_query` and `get_admin_logs` helpers to easily insert logs and extract top-level metrics (Total Queries, Avg Response Time, Cache Hit Rate).

### 2. Pipeline Integration (`src/pipeline.py`)
- Wrapped the entire execution of `answer_question` in `time.perf_counter()` to get precise latency tracking.
- Unified the exit path to invoke `log_query` synchronously at the end, guaranteeing all queries (even fast cache hits or chitchat) are logged.

### 3. Secure Admin API (`src/auth.py` & `src/api.py`)
- Added a new dependency `get_admin_user` which verifies the user's standard 24h JWT token AND ensures their email is listed in the `ADMIN_EMAILS` environment variable.
- Added `GET /admin/logs` endpoint, protected by `get_admin_user`, which returns the aggregate metrics and the 100 most recent query logs.
- Wrote API tests (`test_logging_api.py`) to confirm that standard users get a `403 Forbidden` response, while authenticated admins get a `200 OK`.

### 4. React Admin Dashboard (`frontend/src/pages/Admin.jsx`)
- Built a sleek, minimalist dashboard inside the existing frontend.
- Added three metric cards: **Total Queries**, **Cache Hit Rate (%)**, and **Avg Response Time**.
- Added a full-width data table showing the chronological query logs, complete with colored badges for Intent and Cache Hit status.
- Conditionally render an "Admin" link in the navigation bar if a user is logged in.
- All styles consume the global CSS custom properties defined in our design tokens to seamlessly support Light and Dark themes.

---

## Verification

- **Tests**: Ran all 63 unit and integration tests successfully (`pytest -v`), plus the 2 new logging tests.
- **Frontend Build**: Verified the frontend builds perfectly for production (`npm run build`).

The content team can now easily monitor the types of legal questions being asked, while the engineering team can monitor cache performance and response latencies!
