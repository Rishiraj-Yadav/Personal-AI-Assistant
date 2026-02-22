import { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import './styles/App.css'

function App() {
  const [conversationId, setConversationId] = useState(null)

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <div className="header-logo">⚡</div>
          <h1>OpenClaw</h1>
        </div>
        <div className="header-info">
          {conversationId && (
            <span className="conversation-id">
              {conversationId.substring(0, 12)}
            </span>
          )}
        </div>
      </header>

      <main className="app-main">
        <ChatInterface
          conversationId={conversationId}
          setConversationId={setConversationId}
        />
      </main>

      <footer className="app-footer">
        <p>OpenClaw Agent · Powered by Gemini</p>
      </footer>
    </div>
  )
}

export default App