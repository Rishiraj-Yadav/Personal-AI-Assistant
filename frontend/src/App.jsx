import { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import GatewayConsole from './components/GatewayConsole'
import './styles/App.css'

function App() {
  const [gwOpen, setGwOpen] = useState(false)

  return (
    <>
      <ChatInterface />
      <button
        className="gw-fab"
        onClick={() => setGwOpen(true)}
        title="Open Gateway Console"
        aria-label="Open Gateway Console"
      >
        GW
      </button>
      <GatewayConsole open={gwOpen} onClose={() => setGwOpen(false)} />
    </>
  )
}

export default App