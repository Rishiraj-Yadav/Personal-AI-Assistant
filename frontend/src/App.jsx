import { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import './styles/App.css'

function App() {
  const [conversationId, setConversationId] = useState(null)

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <h1>🤖 OpenClaw Agent</h1>
          <p className="subtitle">AI-Powered Task Automation Assistant</p>
        </div>
        <div className="header-info">
          {conversationId && (
            <span className="conversation-id">
              Session: {conversationId.substring(0, 12)}...
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
        <p>OpenClaw Agent v0.1.0 | Powered by Groq</p>
      </footer>
    </div>
  )
}

export default App