import { useState } from 'react'
import { askQuestion } from '../api/client'

export default function Chat() {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || isLoading) return

    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setQuestion('')
    setIsLoading(true)
    setError(null)

    try {
      const answer = await askQuestion(trimmed)
      setMessages((prev) => [...prev, { role: 'assistant', text: answer }])
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <section className="page page-chat">
      <div className="chat-history">
        {messages.length === 0 && (
          <p className="chat-empty">Ask a question to get started.</p>
        )}
        {messages.map((message, index) => (
          <div key={index} className={`chat-message chat-message-${message.role}`}>
            <p style={{ whiteSpace: 'pre-wrap' }}>{message.text}</p>
          </div>
        ))}
        {isLoading && <p className="chat-loading">Thinking...</p>}
        {error && <p className="chat-error">{error}</p>}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. My landlord won't return my security deposit"
          disabled={isLoading}
        />
        <button type="submit" disabled={isLoading || !question.trim()}>
          Ask
        </button>
      </form>
    </section>
  )
}
