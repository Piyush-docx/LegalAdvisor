import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchAdminLogs } from '../api/client'
import './Admin.css'

export default function Admin() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function loadLogs() {
      try {
        const res = await fetchAdminLogs()
        setData(res)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    loadLogs()
  }, [])

  if (loading) {
    return <div className="admin-container">Loading admin logs...</div>
  }

  if (error) {
    return (
      <div className="admin-container admin-error">
        <h2>Access Denied</h2>
        <p>{error}</p>
        <Link to="/" className="admin-home-btn">Return to Chat</Link>
      </div>
    )
  }

  const { metrics, logs } = data

  return (
    <div className="admin-container">
      <header className="admin-header">
        <h1>Admin Dashboard</h1>
        <Link to="/" className="admin-home-btn">Back to Chat</Link>
      </header>

      <div className="admin-metrics">
        <div className="metric-card">
          <div className="metric-label">Total Queries</div>
          <div className="metric-value">{metrics.total_queries}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Cache Hit Rate</div>
          <div className="metric-value">{metrics.cache_hit_rate.toFixed(1)}%</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg Response Time</div>
          <div className="metric-value">{metrics.avg_response_time_ms} ms</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Feedback</div>
          <div className="metric-value">
            {metrics.feedback?.up ?? 0} helpful · {metrics.feedback?.down ?? 0} not helpful
          </div>
        </div>
      </div>

      <div className="admin-logs-section">
        <h2>Guardrail Triggers</h2>
        {Object.keys(metrics.guardrail_counts || {}).length === 0 ? (
          <p className="logs-empty">No guardrails triggered yet.</p>
        ) : (
          <div className="guardrail-chips">
            {Object.entries(metrics.guardrail_counts).map(([flag, count]) => (
              <span key={flag} className="badge guardrail-chip">
                {flag} · {count}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="admin-logs-section">
        <h2>Recent Queries</h2>
        <div className="table-container">
          <table className="logs-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Query</th>
                <th>Intent</th>
                <th>Cache</th>
                <th>Duration (ms)</th>
                <th>Guardrails</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>{new Date(log.timestamp).toLocaleString()}</td>
                  <td className="log-question" title={log.question}>{log.question}</td>
                  <td>
                    <span className={`badge intent-${log.intent.toLowerCase()}`}>
                      {log.intent}
                    </span>
                  </td>
                  <td>
                    <span className={`badge cache-${log.was_cached === 1 ? 'hit' : 'miss'}`}>
                      {log.was_cached === 1 ? 'Hit' : 'Miss'}
                    </span>
                  </td>
                  <td>{log.response_time_ms}</td>
                  <td>{log.guardrails || '—'}</td>
                </tr>
              ))}
              {logs.length === 0 && (
                <tr>
                  <td colSpan="6" className="logs-empty">No queries logged yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
