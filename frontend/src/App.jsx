import { Link, Route, Routes } from 'react-router-dom'
import Home from './pages/Home'
import Chat from './pages/Chat'
import About from './pages/About'
import './App.css'

function App() {
  return (
    <div className="app">
      <nav className="nav">
        <Link to="/" className="nav-brand">
          Legal Help
        </Link>
        <div className="nav-links">
          <Link to="/chat">Ask a question</Link>
          <Link to="/about">About</Link>
        </div>
      </nav>

      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/about" element={<About />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
