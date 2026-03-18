import { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import MessageList from './MessageList'
import { getUserId, getUserName, setUserName, hasUserName } from '../utils/userId'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'
const GATEWAY_WS_URL = import.meta.env.VITE_GATEWAY_WS || 'ws://localhost:18789/ws'
const USE_GATEWAY_CHAT = (import.meta.env.VITE_USE_GATEWAY_CHAT || 'false') === 'true'
const CONVERSATION_ID_KEY = 'sonarbot_conversation_id'

const SLASH_COMMANDS = [
  { command: '/new', description: 'Start a new conversation', icon: '✨' },
  { command: '/status', description: 'Show system status', icon: '📊' },
  { command: '/compact', description: 'Compress conversation history', icon: '📦' },
  { command: '/help', description: 'Show available commands', icon: '❓' },
  { command: '/reminders', description: 'List active reminders', icon: '⏰' },
  { command: '/history', description: 'Show conversation stats', icon: '📈' },
  { command: '/dashboard', description: 'Open your web dashboard', icon: '🌐' },
  { command: '/permissions', description: 'View your permissions', icon: '🔑' },
]

function ChatInterface() {
  const [messages, setMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  const [userId] = useState(getUserId())
  const [showNamePrompt, setShowNamePrompt] = useState(!hasUserName())
  const [googleConnected, setGoogleConnected] = useState(false)
  const [slashSuggestions, setSlashSuggestions] = useState([])
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [conversations, setConversations] = useState([])
  const [showProfile, setShowProfile] = useState(false)

  const [conversationId, setConversationId] = useState(() => {
    return localStorage.getItem(CONVERSATION_ID_KEY) || null
  })

  const [gatewaySessionId, setGatewaySessionId] = useState(() => {
    return localStorage.getItem('gateway_session_id') || null
  })

  const [webPermissionPending, setWebPermissionPending] = useState(null)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const profileRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => { scrollToBottom() }, [messages, progress])

  useEffect(() => {
    if (conversationId) loadConversationHistory(conversationId)
    loadConversationList()
  }, [])

  useEffect(() => {
    if (conversationId) localStorage.setItem(CONVERSATION_ID_KEY, conversationId)
  }, [conversationId])

  useEffect(() => {
    if (gatewaySessionId) localStorage.setItem('gateway_session_id', gatewaySessionId)
  }, [gatewaySessionId])

  // Close profile dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) setShowProfile(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const loadConversationList = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/multi-agent/conversations?user_id=${userId}`)
      if (response.data) setConversations(response.data)
    } catch { /* silent */ }
  }

  const loadConversationHistory = async (convId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/multi-agent/conversation/${convId}`)
      if (response.data?.messages) setMessages(response.data.messages)
    } catch (err) {
      if (err.response?.status === 404) {
        localStorage.removeItem(CONVERSATION_ID_KEY)
        setConversationId(null)
      }
    }
  }

  const switchConversation = async (convId) => {
    setConversationId(convId)
    localStorage.setItem(CONVERSATION_ID_KEY, convId)
    await loadConversationHistory(convId)
  }

  const checkGoogleStatus = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/auth/google/status?user_id=${userId}`)
      setGoogleConnected(response.data.connected)
    } catch { /* ignore */ }
  }

  useEffect(() => {
    checkGoogleStatus()
    const params = new URLSearchParams(window.location.search)
    if (params.get('google_connected') === 'true') {
      setGoogleConnected(true)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  const connectGoogle = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/auth/google/connect?user_id=${userId}`)
      if (response.data.auth_url) window.location.href = response.data.auth_url
    } catch { setError('Failed to start Google connection.') }
  }

  const disconnectGoogle = async () => {
    try {
      await axios.post(`${API_BASE_URL}/auth/google/disconnect`, { user_id: userId })
      setGoogleConnected(false)
    } catch { setError('Failed to disconnect Google account.') }
  }

  const handleSetName = (name) => {
    if (name.trim()) { setUserName(name.trim()); setShowNamePrompt(false) }
  }

  const sendMessage = async (e) => {
    e.preventDefault()
    if (!inputMessage.trim() || isLoading) return

    const userMessage = { role: 'user', content: inputMessage, timestamp: new Date().toISOString() }
    setMessages(prev => [...prev, userMessage])
    setInputMessage('')
    setIsLoading(true)
    setError(null)
    setProgress(null)
    setSlashSuggestions([])

    try {
      if (USE_GATEWAY_CHAT) {
        const gw = await sendViaGateway(inputMessage)
        const assistantMessage = {
          role: 'assistant',
          content: gw.response,
          timestamp: new Date().toISOString(),
          metadata: { model: 'GatewayRouterV0' }
        }
        setMessages(prev => [...prev, assistantMessage])
      } else {
        const response = await sendWithSmartAgent(inputMessage)
        const assistantMessage = {
          role: 'assistant',
          content: response.data.response,
          timestamp: response.data.timestamp || new Date().toISOString(),
          metadata: {
            model: response.data.model_used,
            tokens: response.data.tokens_used,
            task_type: response.data.task_type,
            agent_path: response.data.agent_path,
            iterations: response.data.metadata?.total_iterations,
            code: response.data.code,
            files: response.data.files,
            file_path: response.data.file_path,
            project_structure: response.data.project_structure,
            main_file: response.data.main_file,
            server_running: response.data.server_running,
            server_url: response.data.server_url,
            language: response.data.language,
            web_screenshots: response.data.web_screenshots || response.data.metadata?.web_screenshots || [],
            web_current_url: response.data.web_current_url || response.data.metadata?.web_current_url || '',
            web_autonomous: response.data.web_autonomous || response.data.metadata?.web_autonomous || false,
            web_actions_count: response.data.metadata?.web_actions_count || 0
          }
        }
        setMessages(prev => [...prev, assistantMessage])
        if (!conversationId && response.data.conversation_id) {
          setConversationId(response.data.conversation_id)
        }
        loadConversationList()
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to send message.')
      setMessages(prev => prev.slice(0, -1))
    } finally {
      setIsLoading(false)
      setProgress(null)
    }
  }

  const sendWithSmartAgent = async (message) => {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://localhost:8000/api/v1/multi-agent/stream`)
      let finalResult = null

      ws.onopen = () => {
        ws.send(JSON.stringify({
          message, user_id: userId, conversation_id: conversationId, max_iterations: 5
        }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'router') setProgress('🎯 ' + data.message)
        else if (data.type === 'classification') setProgress(`📍 Detected: ${data.task_type} task`)
        else if (data.type === 'generating') setProgress('🎨 ' + data.message)
        else if (data.type === 'iteration') setProgress(`🔄 Iteration ${data.iteration}/${data.total}`)
        else if (data.type === 'fixing') setProgress('🔧 ' + data.message)
        else if (data.type === 'success') setProgress('✅ ' + data.message)
        else if (data.type === 'web_agent_plan') setProgress('🌐 ' + data.message)
        else if (data.type === 'web_agent_step') setProgress('🌐 ' + data.message)
        else if (data.type === 'web_agent_action') setProgress(data.success ? '✅ ' + data.message : '❌ ' + data.message)
        else if (data.type === 'web_agent_done') setProgress('🌐 ' + data.message)
        else if (data.type === 'web_agent_permission') {
          setProgress('⚠️ Permission needed...')
          handleWebAgentPermission(data)
        }
        else if (data.type === 'complete') { finalResult = data.result; ws.close() }
        else if (data.type === 'error') { reject(new Error(data.message)); ws.close() }
      }

      ws.onerror = (err) => { reject(err); ws.close() }

      ws.onclose = () => {
        if (finalResult) {
          if (finalResult.action === 'new_conversation') {
            setTimeout(() => { setMessages([]); localStorage.removeItem(CONVERSATION_ID_KEY); setConversationId(null) }, 100)
          }
          resolve({
            data: {
              response: finalResult.response,
              conversation_id: conversationId || finalResult.conversation_id || 'new_conv',
              timestamp: new Date().toISOString(),
              model_used: 'Multi-Agent',
              task_type: finalResult.task_type,
              agent_path: finalResult.agent_path,
              code: finalResult.code,
              files: finalResult.files,
              file_path: finalResult.file_path,
              project_structure: finalResult.project_structure,
              main_file: finalResult.main_file,
              server_running: finalResult.server_running,
              server_url: finalResult.server_url,
              language: finalResult.language,
              metadata: finalResult.metadata,
              web_screenshots: finalResult.web_screenshots,
              web_current_url: finalResult.web_current_url,
              web_autonomous: finalResult.web_autonomous,
            }
          })
        } else { reject(new Error('Connection closed unexpectedly')) }
      }
    })
  }

  const sendViaGateway = async (text) => {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(GATEWAY_WS_URL)
      let assistantText = null
      let sid = gatewaySessionId

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'session.message', session_id: sid || undefined, text }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'session_created' && data.session_id) {
          sid = data.session_id
          setGatewaySessionId(data.session_id)
        }
        if (data.type === 'tool_call') setProgress('🛠️ ' + (data.data?.tool || 'tool'))
        if (data.type === 'tool_result') setProgress('✅ tool result')
        if (data.type === 'message' && data.data?.role === 'assistant') {
          assistantText = data.data.content
        }
        if (data.type === 'complete') ws.close()
        if (data.type === 'error') { reject(new Error(data.data?.error || 'Gateway error')); ws.close() }
      }

      ws.onerror = (err) => { reject(err); ws.close() }
      ws.onclose = () => {
        if (assistantText != null) resolve({ response: assistantText, session_id: sid })
        else reject(new Error('Gateway connection closed unexpectedly'))
      }
    })
  }

  const clearConversation = () => {
    setMessages([])
    localStorage.removeItem(CONVERSATION_ID_KEY)
    setConversationId(null)
    localStorage.removeItem('gateway_session_id')
    setGatewaySessionId(null)
    setError(null)
    setProgress(null)
  }

  const handleWebAgentPermission = (data) => {
    setWebPermissionPending({
      message: data.message,
      action: data.action
    })
  }

  const respondToWebPermission = async (approved) => {
    try {
      await axios.post(`${API_BASE_URL}/multi-agent/web-agent/permission`, {
        user_id: userId,
        approved
      })
    } catch (err) {
      console.error('Permission response failed:', err)
    }
    setWebPermissionPending(null)
  }

  const handleInputChange = (e) => {
    const val = e.target.value
    setInputMessage(val)
    if (val.startsWith('/') && val.length <= 12) {
      setSlashSuggestions(SLASH_COMMANDS.filter(c => c.command.startsWith(val.toLowerCase())))
    } else {
      setSlashSuggestions([])
    }
  }

  const selectSlashCommand = (cmd) => { setInputMessage(cmd); setSlashSuggestions([]); inputRef.current?.focus() }

  const handleKeyDown = (e) => {
    if (e.key === 'Tab' && slashSuggestions.length > 0) {
      e.preventDefault()
      selectSlashCommand(slashSuggestions[0].command)
    }
  }

  /* ── Name Prompt ── */
  if (showNamePrompt) {
    return (
      <div className="onboarding-overlay">
        <div className="onboarding-card">
          <div className="onboarding-icon">🤖</div>
          <h2>Welcome to SonarBot</h2>
          <p className="onboarding-sub">Your personal AI assistant</p>
          <form onSubmit={(e) => { e.preventDefault(); handleSetName(e.target.name.value || 'User') }}>
            <input type="text" name="name" placeholder="Enter your name" autoFocus className="onboarding-input" />
            <div className="onboarding-actions">
              <button type="submit" className="btn-primary">Get Started</button>
              <button type="button" onClick={() => handleSetName('User')} className="btn-ghost">Skip</button>
            </div>
          </form>
        </div>
      </div>
    )
  }

  /* ── Main Layout ── */
  return (
    <div className="app-layout">
      {/* ── Sidebar ── */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <span className="brand-icon">🤖</span>
            {sidebarOpen && <span className="brand-name">SonarBot</span>}
          </div>
          <button className="btn-icon sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)} title={sidebarOpen ? 'Collapse' : 'Expand'}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d={sidebarOpen ? 'M15 18l-6-6 6-6' : 'M9 18l6-6-6-6'}/></svg>
          </button>
        </div>

        <button className="btn-new-chat" onClick={clearConversation}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          {sidebarOpen && <span>New Chat</span>}
        </button>

        {sidebarOpen && (
          <div className="sidebar-conversations">
            <div className="sidebar-section-label">Recent</div>
            {conversations.length === 0 ? (
              <div className="sidebar-empty">No conversations yet</div>
            ) : (
              conversations.slice(0, 30).map((conv) => (
                <button
                  key={conv.conversation_id}
                  className={`sidebar-conv-item ${conv.conversation_id === conversationId ? 'active' : ''}`}
                  onClick={() => switchConversation(conv.conversation_id)}
                  title={conv.title || conv.conversation_id}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  <span className="conv-title">{conv.title || conv.conversation_id?.substring(0, 24)}</span>
                </button>
              ))
            )}
          </div>
        )}

        {/* ── Profile Footer ── */}
        <div className="sidebar-footer" ref={profileRef}>
          {showProfile && sidebarOpen && (
            <div className="profile-dropdown">
              <div className="profile-dropdown-header">
                <div className="avatar lg">{(getUserName() || 'U')[0].toUpperCase()}</div>
                <div>
                  <div className="profile-name">{getUserName() || 'User'}</div>
                  <div className="profile-id">{userId.substring(0, 16)}...</div>
                </div>
              </div>
              <div className="profile-dropdown-divider" />
              {googleConnected ? (
                <button className="profile-dropdown-item" onClick={disconnectGoogle}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                  Disconnect Google
                </button>
              ) : (
                <button className="profile-dropdown-item" onClick={connectGoogle}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                  Connect Google
                </button>
              )}
              <div className="profile-dropdown-item version">
                SonarBot v0.4.0
              </div>
            </div>
          )}
          <button className="profile-trigger" onClick={() => setShowProfile(!showProfile)}>
            <div className="avatar">{(getUserName() || 'U')[0].toUpperCase()}</div>
            {sidebarOpen && (
              <div className="profile-info">
                <span className="profile-name">{getUserName() || 'User'}</span>
                <span className="profile-status">{googleConnected ? 'Google connected' : 'Free tier'}</span>
              </div>
            )}
            {sidebarOpen && (
              <svg className="profile-dots" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
            )}
          </button>
        </div>
      </aside>

      {/* ── Main Chat Area ── */}
      <main className="chat-main">
        {/* Top bar */}
        <header className="chat-topbar">
          {!sidebarOpen && (
            <button className="btn-icon" onClick={() => setSidebarOpen(true)} title="Open sidebar">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
            </button>
          )}
          <div className="topbar-title">{conversationId ? 'Chat' : 'New Chat'}</div>
          <div className="topbar-actions">
            {progress && <div className="topbar-progress">{progress}</div>}
          </div>
        </header>

        {/* Error banner */}
        {error && (
          <div className="error-banner">
            <span>⚠️ {error}</span>
            <button onClick={() => setError(null)} className="btn-icon-sm">✕</button>
          </div>
        )}

        {/* Web Agent Permission Dialog */}
        {webPermissionPending && (
          <div className="permission-banner">
            <div className="permission-icon">⚠️</div>
            <div className="permission-content">
              <div className="permission-title">Web Agent — Permission Required</div>
              <div className="permission-desc">{webPermissionPending.message}</div>
            </div>
            <div className="permission-actions">
              <button className="btn-permission approve" onClick={() => respondToWebPermission(true)}>✅ Approve</button>
              <button className="btn-permission deny" onClick={() => respondToWebPermission(false)}>❌ Deny</button>
            </div>
          </div>
        )}

        {/* Messages */}
        <div className="chat-messages">
          <MessageList messages={messages} isLoading={isLoading} />
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="chat-input-wrapper">
          {slashSuggestions.length > 0 && (
            <div className="slash-popup">
              {slashSuggestions.map(s => (
                <button key={s.command} className="slash-item" onClick={() => selectSlashCommand(s.command)}>
                  <span className="slash-icon">{s.icon}</span>
                  <div className="slash-text">
                    <span className="slash-cmd">{s.command}</span>
                    <span className="slash-desc">{s.description}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
          <form onSubmit={sendMessage} className="chat-form">
            <input
              ref={inputRef}
              type="text"
              value={inputMessage}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Message SonarBot..."
              className="chat-input"
              disabled={isLoading}
              autoFocus
            />
            <button type="submit" className="btn-send" disabled={!inputMessage.trim() || isLoading}>
              {isLoading ? (
                <span className="send-spinner" />
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              )}
            </button>
          </form>
          <div className="input-hint">SonarBot can make mistakes. Type <kbd>/</kbd> for commands.</div>
        </div>
      </main>
    </div>
  )
}

export default ChatInterface