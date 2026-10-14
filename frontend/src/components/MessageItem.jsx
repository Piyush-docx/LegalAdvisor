import { useState } from 'react'
import { sendFeedback } from '../api/client'
import {
  CheckIcon,
  CopyIcon,
  ExternalIcon,
  RedoIcon,
  ThumbDownIcon,
  ThumbUpIcon,
} from './Icons'

const SOURCE_LINE = /^-\s*(?:\[(\d+)\]\s*)?(.*?):\s*(https?:\/\/\S+)$/
const CITATION = /(\[\d+(?:\s*,\s*\d+)*\])/
const BULLET = /^\s*[•-]\s+/
const BACKGROUND_LABEL = 'General background (not from the retrieved sources):'
// Plain-text labels the model starts a paragraph with (see src/generation/prompt.py).
const SECTION_LABELS = [
  { key: 'bottom', label: 'Bottom line:', heading: 'Bottom line' },
  { key: 'law', label: 'What the law says:', heading: 'What the law says' },
  { key: 'applied', label: 'What this means for you:', heading: 'What this means for you' },
  { key: 'steps', label: 'What you can do next:', heading: 'What you can do next' },
]
const DISCLAIMER_MARK = 'This is general legal information, not personalised legal advice'
const ATTRIBUTION_MARK = 'Powered by Indian Kanoon'

// Split the plain-text answer the backend sends into its parts. The answer is
// prose with [n] markers, then "Sources:", the disclaimer and the attribution.
function parseAnswer(text) {
  const paragraphs = []
  const sections = { bottom: [], law: [], applied: [], steps: [] }
  let current = null
  const sources = []
  let background = null
  let disclaimer = null
  let attribution = null

  for (const part of text.split('\n\n')) {
    const trimmed = part.trim()
    if (!trimmed) continue

    if (trimmed.startsWith('Sources:')) {
      trimmed
        .split('\n')
        .slice(1)
        .forEach((line, idx) => {
          const match = line.trim().match(SOURCE_LINE)
          if (match) {
            sources.push({
              n: match[1] ? Number(match[1]) : idx + 1,
              title: match[2],
              url: match[3],
            })
          }
        })
    } else if (trimmed.includes(DISCLAIMER_MARK)) {
      disclaimer = trimmed
    } else if (trimmed.includes(ATTRIBUTION_MARK)) {
      attribution = trimmed
    } else if (trimmed.startsWith(BACKGROUND_LABEL)) {
      background = trimmed.slice(BACKGROUND_LABEL.length).trim()
      current = null
    } else {
      const section = SECTION_LABELS.find((s) => trimmed.startsWith(s.label))
      if (section) {
        current = section.key
        const rest = trimmed.slice(section.label.length).trim()
        if (rest) sections[current].push(rest)
      } else if (current) {
        sections[current].push(trimmed)
      } else {
        paragraphs.push(trimmed)
      }
    }
  }

  return { paragraphs, sections, sources, background, disclaimer, attribution }
}

// Turn "[1]" or "[1, 2]" markers into links to the matching source.
function withCitations(text, sourceByNumber) {
  return text.split(CITATION).map((chunk, i) => {
    if (!CITATION.test(chunk)) return chunk
    const numbers = chunk.slice(1, -1).split(',').map((n) => Number(n.trim()))
    return (
      <sup key={i} className="cite">
        {numbers.map((n, j) => {
          const source = sourceByNumber.get(n)
          return (
            <span key={n}>
              {j > 0 && ', '}
              {source ? (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={source.title}
                  aria-label={`Source ${n}: ${source.title}`}
                >
                  {n}
                </a>
              ) : (
                n
              )}
            </span>
          )
        })}
      </sup>
    )
  })
}

// A paragraph may carry bullet lines (greetings and capability lists do).
function Block({ text, sourceByNumber, className }) {
  const lines = text.split('\n')
  const out = []
  let bullets = []
  let prose = []

  const flushProse = () => {
    if (prose.length) {
      out.push(
        <p key={`p${out.length}`} className={className}>
          {withCitations(prose.join(' '), sourceByNumber)}
        </p>
      )
      prose = []
    }
  }
  const flushBullets = () => {
    if (bullets.length) {
      out.push(
        <ul key={`u${out.length}`} className="memo-list">
          {bullets.map((b, i) => (
            <li key={i}>{withCitations(b, sourceByNumber)}</li>
          ))}
        </ul>
      )
      bullets = []
    }
  }

  for (const line of lines) {
    if (BULLET.test(line)) {
      flushProse()
      bullets.push(line.replace(BULLET, ''))
    } else {
      flushBullets()
      if (line.trim()) prose.push(line.trim())
    }
  }
  flushProse()
  flushBullets()
  return out
}

function AssistantContent({ text }) {
  const { paragraphs, sections, sources, background, disclaimer, attribution } = parseAnswer(text)
  const sourceByNumber = new Map(sources.map((s) => [s.n, s]))
  // Answers carry labelled paragraphs. Older cached answers do not: for those the first
  // paragraph is the bottom line and the rest is what the law says.
  const labelled = sections.bottom.length > 0 || sections.law.length > 0
  const bottomParas = labelled ? [...paragraphs, ...sections.bottom] : paragraphs.slice(0, 1)
  const lawParas = labelled ? sections.law : paragraphs.slice(1)
  const isMemo = sources.length > 0 && bottomParas.length > 0

  const renderSection = (s) => (
    <section className="memo-section" key={s.key}>
      <h3 className="memo-label">{s.heading}</h3>
      {sections[s.key].map((para, i) => (
        <Block key={i} text={para} sourceByNumber={sourceByNumber} className="memo-text" />
      ))}
    </section>
  )
  const guidance = SECTION_LABELS.filter((s) => ['applied', 'steps'].includes(s.key) && sections[s.key].length > 0).map(
    renderSection
  )

  return (
    <div className="memo">
      {isMemo ? (
        <>
          <section className="memo-section">
            <h3 className="memo-label">Bottom line</h3>
            {bottomParas.map((para, i) => (
              <Block key={i} text={para} sourceByNumber={sourceByNumber} className="memo-bottom" />
            ))}
          </section>

          {lawParas.length > 0 && (
            <section className="memo-section">
              <h3 className="memo-label">What the law says</h3>
              {lawParas.map((para, i) => (
                <Block key={i} text={para} sourceByNumber={sourceByNumber} className="memo-text" />
              ))}
            </section>
          )}

          {guidance}

          {background && (
            <section className="memo-section">
              <h3 className="memo-label">General background</h3>
              <p className="memo-text memo-background">{background}</p>
              <p className="memo-note">Not drawn from the retrieved sources.</p>
            </section>
          )}

          <section className="memo-section memo-sources">
            <h3 className="memo-label">Sources</h3>
            <ol>
              {sources.map((s) => (
                <li key={s.n}>
                  <span className="source-n">{s.n}</span>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="source-title">
                    {s.title}
                  </a>
                  <ExternalIcon size={13} className="source-ext" />
                </li>
              ))}
            </ol>
          </section>
        </>
      ) : (
        <section className="memo-section">
          {paragraphs.map((para, i) => (
            <Block key={i} text={para} sourceByNumber={sourceByNumber} className="memo-text" />
          ))}
          {SECTION_LABELS.filter((s) => sections[s.key].length > 0).map(renderSection)}
          {background && <p className="memo-text memo-background">{background}</p>}
        </section>
      )}

      {(disclaimer || attribution) && (
        <footer className="memo-footer">
          {disclaimer && <p>{disclaimer}</p>}
          {attribution && <p>{attribution}</p>}
        </footer>
      )}
    </div>
  )
}

export default function MessageItem({ message, isLast, onRegenerate, question = '', sessionId = null }) {
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

  async function toggleReaction(type) {
    const previous = reaction
    const next = previous === type ? null : type
    setReaction(next)
    if (!next) return
    try {
      await sendFeedback({
        rating: next === 'like' ? 'up' : 'down',
        question,
        answerExcerpt: message.text,
        sessionId,
      })
    } catch {
      setReaction(previous) // not saved: do not show a reaction the server never received
    }
  }

  if (isUser) {
    return (
      <div className="chat-turn chat-turn-user">
        <div className="asked-label">Your question</div>
        <p className="asked-text">{message.text}</p>
      </div>
    )
  }

  return (
    <div className="chat-turn chat-turn-assistant">
      <AssistantContent text={message.text} />

      <div className="message-actions-toolbar">
        <button
          type="button"
          className={`toolbar-btn ${copied ? 'active' : ''}`}
          onClick={handleCopy}
          title="Copy answer to clipboard"
        >
          {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>

        <button
          type="button"
          className={`toolbar-btn ${reaction === 'like' ? 'active-like' : ''}`}
          onClick={() => toggleReaction('like')}
          aria-pressed={reaction === 'like'}
          title="Helpful explanation"
        >
          <ThumbUpIcon size={14} />
          <span>Helpful</span>
        </button>

        <button
          type="button"
          className={`toolbar-btn ${reaction === 'dislike' ? 'active-dislike' : ''}`}
          onClick={() => toggleReaction('dislike')}
          aria-pressed={reaction === 'dislike'}
          title="Not helpful"
        >
          <ThumbDownIcon size={14} />
          <span>Not helpful</span>
        </button>

        {isLast && onRegenerate && (
          <button
            type="button"
            className="toolbar-btn"
            onClick={onRegenerate}
            title="Regenerate response"
          >
            <RedoIcon size={14} />
            <span>Regenerate</span>
          </button>
        )}
      </div>
    </div>
  )
}
