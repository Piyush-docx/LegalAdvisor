const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export async function askQuestion(question) {
  const response = await fetch(`${API_BASE}/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Something went wrong. Please try again.')
  }

  const data = await response.json()
  return data.answer
}
