# Implementation Plan — Step 8: Logging & Bare Admin Page

## Goal
Implement anonymized query logging to track what citizens are asking and how the system is performing (cache hits vs. misses, response times). Build a bare-bones Admin dashboard so the content team can view these metrics and monitor the application.

---

## Proposed Architecture & Changes

### 1. Database Schema (`src/db.py`)
Add a new table `query_logs` to store anonymized analytics (we do not store the user ID here to preserve privacy, just the query and performance metrics):
- `id` (INTEGER PRIMARY KEY)
- `timestamp` (TEXT)
- `question` (TEXT) — The raw question asked by the citizen.
- `intent` (TEXT) — E.g., `NEW_QUERY`, `FOLLOW_UP`, `CHITCHAT`.
- `was_cached` (INTEGER) — 1 for Cache Hit, 0 for Cache Miss.
- `response_time_ms` (INTEGER) — Total time taken to serve the answer.

### 2. Pipeline Integration (`src/pipeline.py`)
- Wrap the execution in `answer_question` with a timer (`time.perf_counter()`).
- At the end of the function, before returning, call a new helper `log_query(question, intent, was_cached, duration_ms)` to asynchronously or synchronously insert the record into `query_logs`.

### 3. Admin API (`src/api.py`)
- Introduce a new endpoint: `GET /admin/logs`.
- **Security**: Protected by a new dependency `get_admin_user`. This will verify the JWT token AND check if the user's email is in an `ADMIN_EMAILS` environment variable list (defaulting to a safe dummy value if not set, or allowing local dev access).
- Returns:
  - Aggregate metrics: Total queries, overall cache hit rate, average response time.
  - Recent logs: The last 100 rows from `query_logs` ordered by newest first.

### 4. Frontend Admin Dashboard (`frontend/src/pages/Admin.jsx` & `frontend/src/App.jsx`)
- **API Client**: Add `getAdminLogs()` to `frontend/src/api/client.js`.
- **Admin Component**: Create a sleek, minimalist dashboard page matching the new UI tokens:
  - Top row: 3 stat cards (Total Queries, Cache Hit %, Avg Latency).
  - Main area: A clean data table displaying the recent queries, intent tags, cache status (with green/gray badges), and timestamp.
- **Routing**: Register the `/admin` route in `App.jsx`.
- **Navbar**: Add a subtle "Admin" navigation link that only appears if the logged-in user is an admin.

### 5. Automated Tests (`tests/test_logging.py` & `tests/test_api.py`)
- Test that queries are successfully logged to the DB with correct timings.
- Test that the `/admin/logs` endpoint correctly blocks non-admins (403 Forbidden) and returns data for admins (200 OK).

---

## User Review Required
> [!IMPORTANT]
> **Admin Authentication**: To keep the "bare admin page" simple, I plan to restrict access to users whose email addresses match a comma-separated list in the `.env` file (e.g., `ADMIN_EMAILS=admin@example.com`). If you log in with that email via the standard OTP flow, you get admin access. Is this approach acceptable to you?

Please review this plan. If you approve, I will begin execution.
