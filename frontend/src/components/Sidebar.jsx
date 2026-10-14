import { useState } from 'react'
import {
  CheckIcon,
  CloseIcon,
  LockIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  ScaleIcon,
  SidebarIcon,
  SunIcon,
  TrashIcon,
} from './Icons'
import { useAuth } from '../context/useAuth'
import { useTheme } from '../context/useTheme'

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onRenameSession,
  onDeleteSession,
  isLoading,
  isOpen,
  onToggleOpen,
  onOpenLogin,
}) {
  const { user, isLoggedIn, logout } = useAuth()
  const { isDark, toggleTheme } = useTheme()

  const [searchQuery, setSearchQuery] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [isDeletingId, setIsDeletingId] = useState(null)

  const filteredSessions = sessions.filter((sess) =>
    sess.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  function startEditing(e, sess) {
    e.stopPropagation()
    setEditingId(sess.session_id)
    setEditTitle(sess.title)
  }

  async function handleSaveRename(e, sessionId) {
    e.preventDefault()
    e.stopPropagation()
    const trimmed = editTitle.trim()
    if (!trimmed) return
    try {
      await onRenameSession(sessionId, trimmed)
      setEditingId(null)
    } catch {
      // ignore
    }
  }

  function handleCancelRename(e) {
    e.stopPropagation()
    setEditingId(null)
    setEditTitle('')
  }

  async function handleDelete(e, sessionId) {
    e.stopPropagation()
    if (!window.confirm('Delete this legal conversation?')) return
    setIsDeletingId(sessionId)
    try {
      await onDeleteSession(sessionId)
    } finally {
      setIsDeletingId(null)
    }
  }

  return (
    <>
      {/* Mobile Backdrop when sidebar is open */}
      <div
        className={`sidebar-backdrop ${isOpen ? 'show' : ''}`}
        onClick={onToggleOpen}
      />

      <aside className={`app-sidebar ${isOpen ? 'open' : 'collapsed'}`}>
        <div className="sidebar-top">
          <div className="sidebar-header-row">
            <div className="sidebar-brand">
              <span className="brand-icon">
                <ScaleIcon size={18} />
              </span>
              <span className="brand-text">Legal Help</span>
            </div>
            <button
              type="button"
              className="icon-btn collapse-toggle-btn"
              onClick={onToggleOpen}
              title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
              aria-label="Toggle sidebar"
            >
              <SidebarIcon size={17} />
            </button>
          </div>

          <button
            type="button"
            className="new-chat-button"
            onClick={onNewChat}
            disabled={isLoading}
          >
            <PlusIcon size={16} />
            <span>New conversation</span>
          </button>

          {isLoggedIn && sessions.length > 0 && (
            <div className="sidebar-search">
              <input
                type="text"
                placeholder="Search chats..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  className="clear-search-btn"
                  onClick={() => setSearchQuery('')}
                >
                  <CloseIcon size={12} />
                </button>
              )}
            </div>
          )}
        </div>

        {/* Conversation List */}
        <div className="sidebar-scrollable">
          {isLoggedIn ? (
            <div className="sidebar-history-group">
              <div className="history-heading">Recent Conversations</div>
              {filteredSessions.length === 0 ? (
                <div className="history-empty">
                  {searchQuery ? 'No matching conversations.' : 'No conversations yet.'}
                </div>
              ) : (
                filteredSessions.map((sess) => {
                  const isActive = sess.session_id === activeSessionId
                  const isEditing = editingId === sess.session_id

                  return (
                    <div
                      key={sess.session_id}
                      className={`history-item ${isActive ? 'active' : ''}`}
                      onClick={() => !isEditing && onSelectSession(sess.session_id)}
                      role="button"
                      tabIndex={0}
                    >
                      {isEditing ? (
                        <form
                          className="history-rename-form"
                          onSubmit={(e) => handleSaveRename(e, sess.session_id)}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="text"
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            autoFocus
                          />
                          <button type="submit" className="rename-save-btn" title="Save" aria-label="Save">
                            <CheckIcon size={14} />
                          </button>
                          <button
                            type="button"
                            className="rename-cancel-btn"
                            onClick={handleCancelRename}
                            title="Cancel"
                            aria-label="Cancel"
                          >
                            <CloseIcon size={14} />
                          </button>
                        </form>
                      ) : (
                        <>
                          <div className="history-item-content">
                            <span className="history-item-title" title={sess.title}>
                              {sess.title}
                            </span>
                          </div>

                          <div className="history-item-actions">
                            <button
                              type="button"
                              className="action-icon-btn"
                              onClick={(e) => startEditing(e, sess)}
                              title="Rename"
                              aria-label="Rename"
                            >
                              <PencilIcon size={14} />
                            </button>
                            <button
                              type="button"
                              className="action-icon-btn danger"
                              onClick={(e) => handleDelete(e, sess.session_id)}
                              disabled={isDeletingId === sess.session_id}
                              title="Delete"
                              aria-label="Delete"
                            >
                              <TrashIcon size={14} />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          ) : (
            <div className="sidebar-guest-card">
              <div className="guest-icon">
                <LockIcon size={22} />
              </div>
              <h4>Sign in for History</h4>
              <p>Sign in with your email to access and search all your previous legal discussions.</p>
              <button
                type="button"
                className="guest-signin-btn"
                onClick={onOpenLogin}
              >
                Sign In with Email
              </button>
            </div>
          )}
        </div>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <div className="theme-toggle-row">
            <span className="theme-label">Theme</span>
            <button
              type="button"
              className="theme-toggle-btn"
              onClick={toggleTheme}
              title={`Switch to ${isDark ? 'Light' : 'Dark'} mode`}
            >
              {isDark ? <SunIcon size={14} /> : <MoonIcon size={14} />}
              <span>{isDark ? 'Light' : 'Dark'}</span>
            </button>
          </div>

          {isLoggedIn ? (
            <div className="user-profile-row">
              <div className="user-avatar" title={user?.email}>
                {(user?.email?.[0] || 'U').toUpperCase()}
              </div>
              <div className="user-info">
                <span className="user-email-text" title={user?.email}>
                  {user?.email}
                </span>
                <span className="user-status-pill">Active (24h)</span>
              </div>
              <button
                type="button"
                className="user-logout-btn"
                onClick={logout}
                title="Sign Out"
              >
                Sign Out
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="footer-signin-btn"
              onClick={onOpenLogin}
            >
              Sign In
            </button>
          )}
        </div>
      </aside>
    </>
  )
}
