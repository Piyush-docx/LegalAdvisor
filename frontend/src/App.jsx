import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import About from './pages/About'
import Chat from './pages/Chat'
import Admin from './pages/Admin'
import LoginModal from './components/LoginModal'
import { useAuth } from './context/useAuth'
import { useTheme } from './context/useTheme'
import './App.css'

function App() {
  const { user, isLoggedIn, logout } = useAuth()
  const { isDark, toggleTheme } = useTheme()
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false)

  return (
    <div className="app-root">
      <header className="site-navbar">
        <div className="navbar-left">
          <Link to="/" className="navbar-brand">
            <span className="brand-badge">⚖️</span>
            <span className="brand-title">Legal Help India</span>
          </Link>
          <nav className="navbar-nav-links">
            <Link to="/chat" className="nav-link">
              Assistant
            </Link>
            <Link to="/about" className="nav-link">
              About & Data Sources
            </Link>
            {isLoggedIn && (
              <Link to="/admin" className="nav-link">
                Admin
              </Link>
            )}
          </nav>
        </div>

        <div className="navbar-right">
          <button
            type="button"
            className="navbar-theme-btn"
            onClick={toggleTheme}
            title={`Switch to ${isDark ? 'Light' : 'Dark'} mode`}
          >
            {isDark ? '☀️ Light' : '🌙 Dark'}
          </button>

          {isLoggedIn ? (
            <div className="navbar-user-chip">
              <span className="navbar-user-email" title={user.email}>
                {user.email}
              </span>
              <button
                type="button"
                className="navbar-auth-btn logout"
                onClick={logout}
              >
                Sign Out
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="navbar-auth-btn login"
              onClick={() => setIsLoginModalOpen(true)}
            >
              Sign In
            </button>
          )}
        </div>
      </header>

      <div className="site-content">
        <Routes>
          <Route
            path="/"
            element={<Chat onOpenLogin={() => setIsLoginModalOpen(true)} />}
          />
          <Route
            path="/chat"
            element={<Chat onOpenLogin={() => setIsLoginModalOpen(true)} />}
          />
          <Route path="/about" element={<About />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </div>

      <LoginModal
        isOpen={isLoginModalOpen}
        onClose={() => setIsLoginModalOpen(false)}
      />
    </div>
  )
}

export default App
