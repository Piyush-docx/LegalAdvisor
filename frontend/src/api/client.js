const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function getAuthHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('legal_auth_token')
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

export async function askQuestion(question, sessionId = null) {
  const payload = { question }
  if (sessionId) {
    payload.session_id = sessionId
  }

  const response = await fetch(`${API_BASE}/ask`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Something went wrong. Please try again.')
  }

  const data = await response.json()
  return {
    answer: data.answer,
    sessionId: data.session_id,
  }
}

export async function sendOtp(email) {
  const response = await fetch(`${API_BASE}/auth/send-otp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to send OTP.')
  }

  return response.json()
}

export async function verifyOtp(email, otp) {
  const response = await fetch(`${API_BASE}/auth/verify-otp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, otp }),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Invalid or expired OTP.')
  }

  return response.json()
}

export async function fetchCurrentUser() {
  const token = localStorage.getItem('legal_auth_token')
  if (!token) return null

  const response = await fetch(`${API_BASE}/auth/me`, {
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('Session expired')
  }

  const data = await response.json()
  return data.user
}

export async function fetchUserSessions() {
  const response = await fetch(`${API_BASE}/sessions`, {
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('Failed to load previous sessions.')
  }

  const data = await response.json()
  return data.sessions || []
}

export async function fetchSessionDetails(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    throw new Error('Failed to load session details.')
  }

  return response.json()
}

export async function renameSession(sessionId, title) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify({ title }),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to rename conversation.')
  }

  return response.json()
}

export async function deleteSession(sessionId) {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to delete conversation.')
  }

  return response.json()
}

export async function fetchAdminLogs() {
  const response = await fetch(`${API_BASE}/admin/logs`, {
    headers: getAuthHeaders(),
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Failed to fetch admin logs. Are you an admin?')
  }

  return response.json()
}

export async function sendFeedback({ rating, question, answerExcerpt, sessionId }) {
  const response = await fetch(`${API_BASE}/feedback`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      rating,
      question: question.slice(0, 2000),
      answer_excerpt: answerExcerpt.slice(0, 1000),
      session_id: sessionId || null,
    }),
  })

  if (!response.ok) {
    throw new Error('Could not save feedback.')
  }

  return response.json()
}
