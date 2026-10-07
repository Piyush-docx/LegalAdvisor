import { useState } from 'react'
import { sendOtp, verifyOtp } from '../api/client'
import { useAuth } from '../context/useAuth'

export default function LoginModal({ isOpen, onClose, onSuccess }) {
  const { login } = useAuth()
  const [step, setStep] = useState('email') // 'email' | 'otp'
  const [email, setEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  if (!isOpen) return null

  function resetState() {
    setStep('email')
    setEmail('')
    setOtp('')
    setError(null)
    setIsLoading(false)
  }

  function handleClose() {
    resetState()
    onClose()
  }

  async function handleSendOtp(e) {
    e.preventDefault()
    const trimmed = email.trim()
    if (!trimmed) return

    setIsLoading(true)
    setError(null)
    try {
      await sendOtp(trimmed)
      setStep('otp')
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  async function handleVerifyOtp(e) {
    e.preventDefault()
    const trimmedOtp = otp.trim()
    if (!trimmedOtp) return

    setIsLoading(true)
    setError(null)
    try {
      const res = await verifyOtp(email.trim(), trimmedOtp)
      login(res.token, res.user, res.expires_in)
      handleClose()
      if (onSuccess) onSuccess()
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-header">
          <h2 id="modal-title">
            {step === 'email' ? 'Sign in to Legal Help' : 'Enter Verification Code'}
          </h2>
          <button
            type="button"
            className="modal-close-btn"
            onClick={handleClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {error && <div className="modal-error">{error}</div>}

        {step === 'email' ? (
          <form onSubmit={handleSendOtp} className="modal-form">
            <p className="modal-desc">
              Enter your email address to receive a one-time login code. No password required. Your session will stay active for 24 hours.
            </p>
            <div className="form-group">
              <label htmlFor="email-input">Email address</label>
              <input
                id="email-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                required
                autoFocus
                disabled={isLoading}
              />
            </div>
            <button
              type="submit"
              className="modal-submit-btn"
              disabled={isLoading || !email.trim()}
            >
              {isLoading ? 'Sending Code...' : 'Send Verification Code'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerifyOtp} className="modal-form">
            <p className="modal-desc">
              We sent a 6-digit code to <strong>{email}</strong>. The code expires in 10 minutes.
            </p>

            <div className="form-group">
              <label htmlFor="otp-input">6-digit code</label>
              <input
                id="otp-input"
                type="text"
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                placeholder="123456"
                maxLength={6}
                required
                autoFocus
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              className="modal-submit-btn"
              disabled={isLoading || otp.trim().length < 4}
            >
              {isLoading ? 'Verifying...' : 'Verify & Sign In'}
            </button>

            <div className="modal-footer-actions">
              <button
                type="button"
                className="text-btn"
                onClick={() => setStep('email')}
                disabled={isLoading}
              >
                Change Email
              </button>
              <button
                type="button"
                className="text-btn"
                onClick={handleSendOtp}
                disabled={isLoading}
              >
                Resend Code
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
