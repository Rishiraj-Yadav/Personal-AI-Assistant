import { useState } from 'react'
import TitleBar from './components/TitleBar'
import ChatInterface from './components/ChatInterface'
import './styles/App.css'

function App() {
  const [conversationId, setConversationId] = useState(null)

  return (
    <>
      <TitleBar />
      <div className="app">
        <header className="app-header">
          <div className="header-content">
            <div className="header-logo">✦</div>
            <h1>SoNAR</h1>
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
          <p>SoNAR may display inaccurate info. Please double-check important responses.</p>
        </footer>
      </div>
    </>
  )
}

export default App