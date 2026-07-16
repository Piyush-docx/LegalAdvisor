import { Link } from 'react-router-dom'

export default function Home() {
  return (
    <section className="page page-home">
      <h1>Know your rights, in plain language</h1>
      <p>
        Ask a question about tenancy, employment, consumer rights, or other everyday
        legal issues. We'll explain what the law says, with citations to the
        actual judgments and statutes — not personalised legal advice.
      </p>
      <Link className="cta" to="/chat">
        Ask a question
      </Link>
    </section>
  )
}
