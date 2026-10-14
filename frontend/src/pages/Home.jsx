import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRightIcon } from '../components/Icons'
import { SAMPLE_PROMPTS } from '../components/samplePrompts'

const STEPS = [
  {
    title: 'You describe the situation',
    body: 'Write it in your own words, in English, Hindi or Hinglish.',
  },
  {
    title: 'We retrieve the actual text',
    body: 'Current Indian statutes and High Court and Supreme Court judgments, via Indian Kanoon.',
  },
  {
    title: 'You get a cited explanation',
    body: 'Plain language, with each point linked to the source so you can read it yourself.',
  },
]

export default function Home() {
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')

  function ask(text) {
    const trimmed = text.trim()
    if (!trimmed) return
    navigate('/chat', { state: { question: trimmed } })
  }

  return (
    <div className="home-page">
      <div className="home-inner">
        <section className="home-hero">
          <div className="eyebrow">Plain-language legal information</div>
          <h1 className="home-title">Know your rights, in plain language.</h1>
          <p className="home-lede">
            Ask about tenancy, employment, consumer rights or other everyday legal issues.
            Every answer explains what the law says and cites the judgments and statutes
            behind it. It is general information, not personalised legal advice.
          </p>

          <form
            className="home-ask"
            onSubmit={(e) => {
              e.preventDefault()
              ask(question)
            }}
          >
            <label htmlFor="home-question" className="visually-hidden">
              Your legal question
            </label>
            <input
              id="home-question"
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Describe your situation in a sentence or two"
              autoComplete="off"
            />
            <button type="submit" className="home-ask-btn" disabled={!question.trim()}>
              <span>Ask</span>
              <ArrowRightIcon size={16} />
            </button>
          </form>
        </section>

        <section className="home-topics" aria-labelledby="home-topics-label">
          <h2 id="home-topics-label" className="section-label">
            Common questions
          </h2>
          <ul className="topic-list">
            {SAMPLE_PROMPTS.map((sample) => (
              <li key={sample.category}>
                <button type="button" className="topic-row" onClick={() => ask(sample.text)}>
                  <span className="topic-cat">{sample.category}</span>
                  <span className="topic-q">{sample.text}</span>
                  <span className="topic-go">
                    <ArrowRightIcon size={16} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="home-how" aria-labelledby="home-how-label">
          <h2 id="home-how-label" className="section-label">
            How it works
          </h2>
          <ol className="how-steps">
            {STEPS.map((step) => (
              <li key={step.title}>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <footer className="home-foot">
          Legal data from{' '}
          <a href="https://indiankanoon.org" target="_blank" rel="noreferrer">
            Indian Kanoon
          </a>
          . <Link to="/about">About this tool and its data sources</Link>
        </footer>
      </div>
    </div>
  )
}
