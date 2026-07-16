export default function About() {
  return (
    <section className="page page-about">
      <h1>About this tool</h1>
      <p>
        This is a free, non-profit tool that helps citizens understand their
        legal rights in plain language. It is <strong>not</strong> a substitute
        for a lawyer — every answer is general legal information, not
        personalised advice.
      </p>

      <h2>How it works</h2>
      <p>
        When you ask a question, we retrieve the actual, current text of Indian
        case law and statutes relevant to your question, and use an AI model to
        explain that text in plain language — citing every claim so you can read
        the original source yourself.
      </p>

      <h2 id="attribution">Powered by Indian Kanoon</h2>
      <p>
        Legal search and case data is provided by{' '}
        <a href="https://indiankanoon.org" target="_blank" rel="noreferrer">
          Indian Kanoon
        </a>
        , a free legal search engine. Indian Kanoon provides this data "as is"
        from public government sources, without warranty of accuracy.
      </p>
    </section>
  )
}
