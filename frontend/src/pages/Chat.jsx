import { useEffect, useRef, useState, useCallback } from 'react'
import {
  askQuestion,
  deleteSession,
  fetchSessionDetails,
  fetchUserSessions,
  renameSession,
} from '../api/client'
import MessageItem from '../components/MessageItem'
import Sidebar from '../components/Sidebar'
import { useAuth } from '../context/useAuth'

const SAMPLE_PROMPTS = [
  {
    category: 'Tenancy & Rent',
    icon: '🏠',
    text: "My landlord won't refund my security deposit after moving out.",
  },
  {
    category: 'Employment Rights',
    icon: '💼',
    text: 'Can an employer terminate me without notice period or severance pay?',
  },
  {
    category: 'Consumer Protection',
    icon: '🛒',
    text: 'A defective phone was delivered and the seller is refusing refund or replacement.',
  },
  {
    category: 'Property & Family',
    icon: '📜',
    text: "What are daughters' legal rights in ancestral property in India?",
  },
]

export default function Chat({ onOpenLogin }) {
  const { isLoggedIn, user } = useAuth()
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [sessions, setSessions] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const messagesEndRef = useRef(null)

  useEffect(() => {
    if (isLoggedIn) {
      loadSessions()
    } else {
      setSessions([])
    }
  }, [isLoggedIn, user])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  async function loadSessions() {
    try {
      const userSessions = await fetchUserSessions()
      setSessions(userSessions)
    } catch {
      // ignore failure
    }
  }

  async function handleSelectSession(selectedId) {
    if (selectedId === sessionId || isLoading) return
    setError(null)
    setIsLoading(true)
    try {
      const details = await fetchSessionDetails(selectedId)
      setSessionId(details.session_id)
      setMessages(
        details.messages.map((m) => ({
          id: crypto.randomUUID(),
          role: m.role,
          text: m.content,
        }))
      )
    } catch (err) {
      setError(err.message || 'Failed to load conversation.')
    } finally {
      setIsLoading(false)
    }
  }

  function handleNewChat() {
    setMessages([])
    setSessionId(null)
    setError(null)
    setQuestion('')
  }

  async function handleRenameSession(idToRename, newTitle) {
    await renameSession(idToRename, newTitle)
    setSessions((prev) =>
      prev.map((s) => (s.session_id === idToRename ? { ...s, title: newTitle } : s))
    )
  }

  async function handleDeleteSession(idToDelete) {
    await deleteSession(idToDelete)
    setSessions((prev) => prev.filter((s) => s.session_id !== idToDelete))
    if (sessionId === idToDelete) {
      handleNewChat()
    }
  }

  async function handleSend(textToSend) {
    const trimmed = (textToSend || question).trim()
    if (!trimmed || isLoading) return

    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', text: trimmed }])
    setQuestion('')
    setIsLoading(true)
    setError(null)

    try {
      const { answer, sessionId: newSessionId } = await askQuestion(trimmed, sessionId)
      if (newSessionId) {
        setSessionId(newSessionId)
      }
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: answer }])
      if (isLoggedIn) {
        loadSessions()
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  async function handleRegenerate() {
    if (isLoading || messages.length === 0) return
    // Find last user question
    const userMessages = messages.filter((m) => m.role === 'user')
    if (userMessages.length === 0) return
    const lastUserQuestion = userMessages[userMessages.length - 1].text

    // Remove last assistant message
    setMessages((prev) => {
      const copy = [...prev]
      if (copy.length > 0 && copy[copy.length - 1].role === 'assistant') {
        copy.pop()
      }
      return copy
    })

    setIsLoading(true)
    setError(null)
    try {
      const { answer } = await askQuestion(lastUserQuestion, sessionId)
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', text: answer }])
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="chat-layout-wrapper">
      <Sidebar
        sessions={sessions}
        activeSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
        isLoading={isLoading}
        isOpen={sidebarOpen}
        onToggleOpen={() => setSidebarOpen((prev) => !prev)}
        onOpenLogin={onOpenLogin}
      />

      <main className="chat-viewport">
        {/* Top Floating Bar for Mobile or when sidebar collapsed */}
        <div className="chat-topbar">
          {!sidebarOpen && (
            <button
              type="button"
              className="open-sidebar-btn"
              onClick={() => setSidebarOpen(true)}
              title="Open sidebar"
            >
              ☰ History
            </button>
          )}
          <div className="chat-current-title">
          {(() => {
            const activeTitle = sessions.find((s) => s.session_id === sessionId)?.title
            return <span>{activeTitle || 'New Conversation'}</span>
          })()}
          </div>
          <button
            type="button"
            className="topbar-new-chat-btn"
            onClick={handleNewChat}
            disabled={isLoading}
            title="Start new conversation"
          >
            + New
          </button>
        </div>

        {/* Message Feed / Empty State */}
        <div className="chat-feed">
          {messages.length === 0 ? (
            <div className="chat-empty-hero">
              <div className="hero-badge">Citizen Legal Assistant</div>
              <h1 className="hero-title">How can I help with Indian law today?</h1>
              <p className="hero-subtitle">
                Ask your everyday legal questions in plain words. All answers are grounded
                in current Indian statutes and High Court / Supreme Court judgments.
              </p>

              <div className="sample-prompts-grid">
                {SAMPLE_PROMPTS.map((sample, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="prompt-card"
                    onClick={() => handleSend(sample.text)}
                  >
                    <span className="prompt-icon">{sample.icon}</span>
                    <span className="prompt-category">{sample.category}</span>
                    <span className="prompt-text">"{sample.text}"</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-messages-container">
              {messages.map((msg, index) => (
                <MessageItem
                  key={msg.id}
                  message={msg}
                  isLast={index === messages.length - 1}
                  onRegenerate={handleRegenerate}
                />
              ))}

              {isLoading && (
                <div className="chat-row chat-row-assistant chat-loading-row">
                  <div className="chat-avatar">
                    <div className="avatar-circle ai-avatar-badge">⚖️</div>
                  </div>
                  <div className="chat-bubble-container">
                    <div className="chat-bubble-author">Legal AI Advisor</div>
                    <div className="chat-typing-indicator">
                      <div className="typing-dots">
                        <span className="dot" />
                        <span className="dot" />
                        <span className="dot" />
                      </div>
                      <span className="typing-label">
                        Retrieving relevant statutes & Indian Kanoon judgments...
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {error && (
                <div className="chat-error-banner">
                  <span className="error-icon">⚠️</span>
                  <span className="error-text">{error}</span>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="chat-input-area">
          <form
            className="chat-input-box"
            onSubmit={(e) => {
              e.preventDefault()
              handleSend()
            }}
          >
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="Ask a legal question (e.g. Can my landlord deduct my deposit?)..."
              rows={1}
              disabled={isLoading}
            />
            <button
              type="submit"
              className="send-button"
              disabled={isLoading || !question.trim()}
              title="Send question (Enter)"
            >
              <span>▲</span>
            </button>
          </form>
          <div className="chat-input-disclaimer">
            Provides general legal information for Indian jurisdiction, not formal legal advice.
          </div>
        </div>
      </main>
    </div>
  )
}
