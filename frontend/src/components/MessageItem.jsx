import { useState } from 'react'

export default function MessageItem({ message, isLast, onRegenerate }) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const [reaction, setReaction] = useState(null) // 'like' | 'dislike' | null

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(message.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  function toggleReaction(type) {
    setReaction((prev) => (prev === type ? null : type))
  }

  // Parse structured blocks if Assistant message
  function renderAssistantContent(text) {
    const parts = text.split('\n\n')
    const normalParagraphs = []
    let sources = []
    let disclaimer = null
    let attribution = null

    for (const part of parts) {
      const trimmed = part.trim()
      if (trimmed.startsWith('Sources:')) {
        const lines = trimmed.split('\n').slice(1)
        sources = lines
          .map((line) => {
            const match = line.match(/^-\s*(.*?):\s*(https?:\/\/[^\s]+)$/)
            if (match) {
              return { title: match[1], url: match[2] }
            }
            return null
          })
          .filter(Boolean)
      } else if (trimmed.includes('This is general legal information, not personalised legal advice')) {
        disclaimer = trimmed
      } else if (trimmed.includes('Powered by Indian Kanoon')) {
        attribution = trimmed
      } else if (trimmed) {
        normalParagraphs.push(trimmed)
      }
    }

    return (
      <div className="assistant-content">
        <div className="main-explanation">
          {normalParagraphs.map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>

        {sources.length > 0 && (
          <div className="message-sources-box">
            <div className="sources-title">
              <span>📚</span> Verified Legal Sources:
            </div>
            <div className="sources-list">
              {sources.map((s, idx) => (
                <a
                  key={idx}
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="source-card-link"
                >
                  <span className="source-link-icon">🔗</span>
                  <span className="source-link-title">{s.title}</span>
                  <span className="source-link-external">↗</span>
                </a>
              ))}
            </div>
          </div>
        )}

        {disclaimer && (
          <div className="message-disclaimer-callout">
            <span className="disclaimer-icon">ℹ️</span>
            <span className="disclaimer-text">{disclaimer}</span>
          </div>
        )}

        {attribution && (
          <div className="message-attribution-footer">
            <span>{attribution}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={`chat-row ${isUser ? 'chat-row-user' : 'chat-row-assistant'}`}>
      <div className="chat-avatar">
        {isUser ? (
          <div className="avatar-circle user-avatar-badge">You</div>
        ) : (
          <div className="avatar-circle ai-avatar-badge" title="Legal Help Assistant">
            ⚖️
          </div>
        )}
      </div>

      <div className="chat-bubble-container">
        <div className="chat-bubble-header">
          <span className="chat-bubble-author">{isUser ? 'You' : 'Legal AI Advisor'}</span>
        </div>

        <div className="chat-bubble-body">
          {isUser ? (
            <p style={{ whiteSpace: 'pre-wrap' }}>{message.text}</p>
          ) : (
            renderAssistantContent(message.text)
          )}
        </div>

        {!isUser && (
          <div className="message-actions-toolbar">
            <button
              type="button"
              className={`toolbar-btn ${copied ? 'active' : ''}`}
              onClick={handleCopy}
              title="Copy message to clipboard"
            >
              {copied ? '✓ Copied' : '📋 Copy'}
            </button>

            <button
              type="button"
              className={`toolbar-btn ${reaction === 'like' ? 'active-like' : ''}`}
              onClick={() => toggleReaction('like')}
              title="Helpful explanation"
            >
              👍
            </button>

            <button
              type="button"
              className={`toolbar-btn ${reaction === 'dislike' ? 'active-dislike' : ''}`}
              onClick={() => toggleReaction('dislike')}
              title="Not helpful"
            >
              👎
            </button>

            {isLast && onRegenerate && (
              <button
                type="button"
                className="toolbar-btn"
                onClick={onRegenerate}
                title="Regenerate response"
              >
                🔄 Regenerate
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
