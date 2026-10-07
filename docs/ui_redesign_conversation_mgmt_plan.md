# Implementation Plan — ChatGPT-Quality UI/UX Redesign & Conversation Management

Redesign the application interface to modern, production-grade ChatGPT standards. Fix the dark-mode contrast bug where headings and text were unreadable, implement light/dark theme switching, full conversation management (rename, delete, search), message action toolbars (copy, regenerate, thumbs up/down), clean markdown rendering, and animated typing indicators.

---

## Visual & UX Issues Identified in Screenshot

1. **Dark Mode Text Invisibility**: macOS dark mode (`prefers-color-scheme: dark`) turned `:root` background to `#16171d`, while hardcoded `#1a1a1a` in `App.css` caused "Legal Help", "Ask a question", "About", and headings to appear nearly black-on-black (unreadable).
2. **Jarring Bubble Contrast**: AI bubble was an unstyled stark white rectangle while user bubble was pitch black on dark navy background.
3. **No Theme Toggle**: The user had no way to switch between crisp light mode and sleek dark mode.
4. **Lack of Chat Controls**: Missing conversation rename, delete, search history, message copy, regeneration, and feedback buttons.

---

## Changes Implemented

### 1. Backend: Conversation Management API

- **[src/session.py](file:///Users/piyushdokania/legal/src/session.py)**:
  - `rename_session(session_id: str, new_title: str, user_id: str) -> bool`
  - `delete_session(session_id: str, user_id: str) -> bool`
- **[src/api.py](file:///Users/piyushdokania/legal/src/api.py)**:
  - `PATCH /sessions/{session_id}`: Rename conversation title (authenticated, owner only).
  - `DELETE /sessions/{session_id}`: Delete a conversation and its messages (authenticated, owner only).

---

### 2. Frontend: Design System & Theming

- **[frontend/src/index.css](file:///Users/piyushdokania/legal/frontend/src/index.css)**:
  - Replaced fragmented variables with a unified design token system.
  - Supports `data-theme="light"` and `data-theme="dark"` with accessible, high-contrast zinc/slate palettes.
  - Modern typography with Google Font `Inter`.
  - Harmonious colors: crisp cards, subtle borders, warm accents, accessible text contrast.
- **[frontend/src/App.css](file:///Users/piyushdokania/legal/frontend/src/App.css)**:
  - Complete rewrite using CSS design tokens for all components:
  - App shell, sidebar, chat feed, message bubbles, action toolbars, inputs, modals.
  - Smooth transitions and hover animations.

---

### 3. Frontend: Components & Layout

- **[frontend/src/context/ThemeContext.jsx](file:///Users/piyushdokania/legal/frontend/src/context/ThemeContext.jsx)**:
  - Manages `theme` ('light' | 'dark') persisted in `localStorage`.
  - Toggles `data-theme` attribute on `document.documentElement`.
- **[frontend/src/components/MessageItem.jsx](file:///Users/piyushdokania/legal/frontend/src/components/MessageItem.jsx)**:
  - Renders User and Assistant messages with:
    - Avatars ("You" and "Legal AI" badge with scales of justice icon).
    - Clean markdown rendering (bold, italics, lists, source citations styled as card links, legal disclaimers styled as subtle warning blocks).
    - Action toolbar on hover/touch:
      - **Copy**: copies message text to clipboard with animated "Copied!" checkmark.
      - **Regenerate**: re-submits the last question to get a fresh response.
      - **Like / Dislike**: feedback state with active toggle.
- **[frontend/src/components/Sidebar.jsx](file:///Users/piyushdokania/legal/frontend/src/components/Sidebar.jsx)**:
  - ChatGPT-inspired collapsible sidebar:
    - "+ New Chat" button.
    - **Search Bar**: Real-time filtering of conversation history.
    - **Conversation List**:
      - Active conversation indicator.
      - **Rename (inline editing)**: Pencil button allowing users to edit conversation title.
      - **Delete (with confirmation)**: Trash icon to remove old chats.
    - Sidebar bottom:
      - User profile card with email, logout, and Theme Toggle button (☀️ / 🌙).
    - Collapse / Expand toggle button for focused reading.
- **[frontend/src/pages/Chat.jsx](file:///Users/piyushdokania/legal/frontend/src/pages/Chat.jsx)**:
  - Integrated `Sidebar`, `MessageItem`, and typing indicator.
  - Empty state: Clean hero welcoming citizens, explaining data privacy, and offering one-click sample legal questions.
  - Typing indicator: Three pulsing dots with *"Consulting Indian statutes & court judgments..."*.
- **[frontend/src/App.jsx](file:///Users/piyushdokania/legal/frontend/src/App.jsx)**:
  - Wrap application with `ThemeProvider`.
  - Polished top navigation bar with clean theme toggle and auth state.

---

### 4. Tests

- **[tests/test_conversation_mgmt.py](file:///Users/piyushdokania/legal/tests/test_conversation_mgmt.py)**:
  - Test renaming conversations in DB.
  - Test deleting conversations in DB.
  - Test `PATCH /sessions/{session_id}` and `DELETE /sessions/{session_id}` API endpoints with permissions check.
