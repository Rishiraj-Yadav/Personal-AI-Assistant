import { useState, useRef, useEffect, useCallback } from 'react'
import axios from 'axios'
import MessageList from './MessageList'
import { getUserId, getUserName, setUserName, hasUserName } from '../utils/userId'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'
const CONVERSATION_ID_KEY = 'sonarbot_conversation_id'

const SLASH_COMMANDS = [
  { command: '/new',         description: 'Start a new conversation',    icon: '✨' },
  { command: '/status',      description: 'Show system status',          icon: '📊' },
  { command: '/compact',     description: 'Compress conversation history',icon: '📦' },
  { command: '/help',        description: 'Show available commands',     icon: '❓' },
  { command: '/reminders',   description: 'List active reminders',       icon: '⏰' },
  { command: '/history',     description: 'Show conversation stats',     icon: '📈' },
  { command: '/dashboard',   description: 'Open your web dashboard',     icon: '🌐' },
  { command: '/permissions', description: 'View your permissions',       icon: '🔑' },
]

// ─────────────────────────────────────────────────────────────────────────────
//  Main ChatInterface
// ─────────────────────────────────────────────────────────────────────────────
function ChatInterface() {
  const [messages,           setMessages]           = useState([])
  const [inputMessage,       setInputMessage]       = useState('')
  const [isLoading,          setIsLoading]          = useState(false)
  const [error,              setError]              = useState(null)
  const [progress,           setProgress]           = useState(null)
  const [userId]                                    = useState(getUserId())
  const [showNamePrompt,     setShowNamePrompt]     = useState(!hasUserName())
  const [googleConnected,    setGoogleConnected]    = useState(false)
  const [slashSuggestions,   setSlashSuggestions]   = useState([])
  const [sidebarOpen,        setSidebarOpen]        = useState(true)
  const [conversations,      setConversations]      = useState([])
  const [showProfile,        setShowProfile]        = useState(false)
  const [webPermissionPending,  setWebPermissionPending]  = useState(null)
  const [taskApprovalPending,   setTaskApprovalPending]   = useState(null)
  const [browserInputPending,   setBrowserInputPending]   = useState(null)
  const [browserInputValue,     setBrowserInputValue]     = useState('')

  const [conversationId, setConversationId] = useState(
    () => localStorage.getItem(CONVERSATION_ID_KEY) || null
  )

  const messagesEndRef = useRef(null)
  const inputRef       = useRef(null)
  const profileRef     = useRef(null)

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(() => { scrollToBottom() }, [messages, progress])

  useEffect(() => {
    if (conversationId) loadConversationHistory(conversationId)
    loadConversationList()
  }, [])

  useEffect(() => {
    const latestAssistant = [...messages].reverse().find((msg) => msg.role === 'assistant')
    const pending = latestAssistant?.metadata?.browser_input_state
    if (pending?.status === 'required') {
      setBrowserInputPending(pending)
    } else if (!isLoading) {
      setBrowserInputPending(null)
      setBrowserInputValue('')
    }
  }, [messages, isLoading])

  useEffect(() => {
    if (conversationId) localStorage.setItem(CONVERSATION_ID_KEY, conversationId)
  }, [conversationId])

  useEffect(() => {
    const handleClick = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) setShowProfile(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // ── Data loaders ──────────────────────────────────────────────────────────

  const loadConversationList = async () => {
    try {
      const res = await axios.get(`${API_BASE_URL}/multi-agent/conversations?user_id=${userId}`)
      if (res.data) setConversations(res.data)
    } catch { /* silent */ }
  }

  const loadConversationHistory = async (convId) => {
    try {
      const res = await axios.get(`${API_BASE_URL}/multi-agent/conversation/${convId}`)
      if (res.data?.messages) setMessages(res.data.messages)
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
      const res = await axios.get(`${API_BASE_URL}/auth/google/status?user_id=${userId}`)
      setGoogleConnected(res.data.connected)
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
      const res = await axios.get(`${API_BASE_URL}/auth/google/connect?user_id=${userId}`)
      if (res.data.auth_url) window.location.href = res.data.auth_url
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

  // ── WebSocket send ────────────────────────────────────────────────────────

  const sendWithSmartAgent = useCallback((message, options = {}) => {
    return new Promise((resolve, reject) => {
      const requestType = options.requestType || 'message'
      const wsUrl = API_BASE_URL
        .replace('http://', 'ws://')
        .replace('https://', 'wss://')
        .replace('/api/v1', '/api/v1/multi-agent/stream')

      const ws = new WebSocket(wsUrl)
      let finalResult = null

      ws.onopen = () => {
        const payload = {
          user_id: userId,
          conversation_id: conversationId,
          max_iterations: 5,
        }
        if (requestType === 'agent_answer') {
          payload.type = 'agent_answer'
          payload.value = message
        } else {
          payload.message = message
        }
        ws.send(JSON.stringify(payload))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)

        // ── Progress events ───────────────────────────────────────────────
        if (data.type === 'processing')        setProgress('⏳ Processing…')
        else if (data.type === 'context')      setProgress('🧠 ' + data.message)
        else if (data.type === 'router')       setProgress('🎯 ' + data.message)
        else if (data.type === 'classification') setProgress(`📍 Detected: ${data.task_type} task`)
        else if (data.type === 'generating')   setProgress('🎨 ' + data.message)
        else if (data.type === 'iteration')    setProgress(`🔄 Iteration ${data.iteration}/${data.total}`)
        else if (data.type === 'fixing')       setProgress('🔧 ' + data.message)
        else if (data.type === 'success')      setProgress('✅ ' + data.message)
        else if (data.type === 'web_agent_plan')   setProgress('🌐 ' + data.message)
        else if (data.type === 'web_agent_step')   setProgress('🌐 ' + data.message)
        else if (data.type === 'web_agent_action') setProgress(data.success ? '✅ ' + data.message : '❌ ' + data.message)
        else if (data.type === 'web_agent_done')   setProgress('🌐 ' + data.message)
        else if (data.type === 'web_agent_permission') {
          setProgress('⚠️ Permission needed…')
          handleWebAgentPermission(data)
        }
        else if (data.type === 'approval_required') setProgress('⚠️ Approval needed…')

        // ── Completion ────────────────────────────────────────────────────
        else if (data.type === 'question_for_user') {
          const nextBrowserInput = data.browser_input_state || {
            status: 'required',
            browser_input_id: data.browser_input_id,
            field_description: data.field_description || 'the requested input',
            input_type: data.input_type || 'text',
            reason: data.reason || data.message || '',
            channel: data.channel || 'web',
          }
          setBrowserInputPending(nextBrowserInput)
          setProgress('Browser input needed...')
        }
        else if (data.type === 'complete') {
          finalResult = data.result
          ws.close()
        }
        else if (data.type === 'error') {
          reject(new Error(data.message))
          ws.close()
        }
      }

      ws.onerror = (err) => { reject(err); ws.close() }

      ws.onclose = () => {
        setProgress(null)
        if (finalResult) {
          const desktopResult = finalResult.metadata?.desktop_result || finalResult.artifacts?.desktop_result || null
          let fileContent = null, fileContentPath = null
          if (desktopResult?.completed_steps) {
            for (const step of desktopResult.completed_steps) {
              if (step.tool_name === 'read_file' && step.success && step.response?.result?.content) {
                fileContent = step.response.result.content
                fileContentPath = step.response.result.path || ''
                break
              }
            }
          }

          const assistantMessage = {
            role: 'assistant',
            content: finalResult.output || finalResult.response,
            timestamp: new Date().toISOString(),
            metadata: {
              task_type:           finalResult.task_type,
              agent_path:          finalResult.agent_path,
              iterations:          finalResult.metadata?.total_iterations,
              code:                finalResult.code,
              files:               finalResult.files,
              file_path:           finalResult.file_path,
              project_structure:   finalResult.project_structure,
              main_file:           finalResult.main_file,
              server_running:      finalResult.server_running,
              server_url:          finalResult.server_url,
              language:            finalResult.language,
              web_screenshots:     finalResult.web_screenshots || finalResult.metadata?.web_screenshots || [],
              web_current_url:     finalResult.web_current_url || finalResult.metadata?.web_current_url || '',
              web_autonomous:      finalResult.web_autonomous || finalResult.metadata?.web_autonomous || false,
              web_actions_count:   finalResult.metadata?.web_actions_count || 0,
              plan:                finalResult.plan,
              execution_trace:     finalResult.execution_trace || [],
              approval_state:      finalResult.approval_state || null,
              clarification_state: finalResult.clarification_state || null,
              browser_input_state: finalResult.browser_input_state || null,
              browser_state:       finalResult.browser_state || {},
              artifacts:           finalResult.artifacts || null,
              file_content:        fileContent,
              file_content_path:   fileContentPath,
            },
          }
          setMessages(prev => [...prev, assistantMessage])

          if (finalResult.action === 'new_conversation') {
            setTimeout(() => {
              setMessages([])
              localStorage.removeItem(CONVERSATION_ID_KEY)
              setConversationId(null)
            }, 100)
          }

          if (finalResult.approval_state?.status === 'required') {
            setTaskApprovalPending({
              approvalId:    finalResult.approval_state.approval_id,
              reason:        finalResult.approval_state.reason || 'Approval required.',
              affectedSteps: finalResult.approval_state.affected_steps || [],
              taskType:      finalResult.task_type,
            })
          }

          if (finalResult.browser_input_state?.status === 'required') {
            setBrowserInputPending(finalResult.browser_input_state)
          } else {
            setBrowserInputPending(null)
            setBrowserInputValue('')
          }

          loadConversationList()
          resolve({ data: { ...finalResult, response: finalResult.output || finalResult.response } })
        } else if (!finalResult) {
          reject(new Error('Connection closed without result'))
        }
      }
    })
  }, [userId, conversationId])

  // ── Send message ─────────────────────────────────────────────────────────

  const sendMessage = async (e) => {
    e.preventDefault()
    const trimmed = inputMessage.trim()
    if (!trimmed) return

    const userMessage = { role: 'user', content: trimmed, timestamp: new Date().toISOString() }
    setMessages(prev => [...prev, userMessage])
    setInputMessage('')
    setSlashSuggestions([])
    setError(null)
    setIsLoading(true)

    try {
      await sendWithSmartAgent(trimmed)
    } catch (err) {
      setError(err.message || 'Failed to send message.')
    } finally {
      setIsLoading(false)
    }
  }

  // ── Clarification / approval callbacks ───────────────────────────────────

  const handleClarificationSelect = async (optionValue) => {
    const userMessage = { role: 'user', content: optionValue, timestamp: new Date().toISOString() }
    setMessages(prev => [...prev, userMessage])
    setIsLoading(true)
    setError(null)
    setProgress(null)
    try {
      await sendWithSmartAgent(optionValue)
    } catch (err) {
      setError(err.message || 'Failed to process selection.')
    } finally {
      setIsLoading(false)
      setProgress(null)
    }
  }

  const submitBrowserInput = async (e) => {
    e.preventDefault()
    if (!browserInputPending) return
    const trimmed = browserInputValue.trim()
    if (!trimmed) return

    const fieldDescription = browserInputPending.field_description || 'browser input'
    const safeLabel = `Provided ${fieldDescription}`
    setMessages(prev => [
      ...prev,
      {
        role: 'user',
        content: safeLabel,
        timestamp: new Date().toISOString(),
        metadata: { secret_input: true },
      },
    ])
    setBrowserInputValue('')
    setError(null)
    setIsLoading(true)

    try {
      await sendWithSmartAgent(trimmed, { requestType: 'agent_answer' })
    } catch (err) {
      setError(err.message || 'Failed to continue the browser task.')
      setBrowserInputPending(prev => prev || browserInputPending)
    } finally {
      setIsLoading(false)
    }
  }

  const respondToWebPermission = async (approved) => {
    try {
      await axios.post(`${API_BASE_URL}/multi-agent/web-agent/permission`, {
        user_id: userId, approved,
      })
    } catch { /* ignore */ }
    setWebPermissionPending(null)
  }

  const respondToTaskApproval = async (approved) => {
    if (!taskApprovalPending) return
    try {
      const res = await axios.post(`${API_BASE_URL}/multi-agent/approval/respond`, {
        approval_id: taskApprovalPending.approvalId,
        user_id:     userId,
        approved,
      })
      const data = res.data
      const assistantMessage = {
        role:      'assistant',
        content:   data.response,
        timestamp: new Date().toISOString(),
        metadata: {
          task_type:       data.task_type,
          agent_path:      data.agent_path,
          execution_trace: data.execution_trace || [],
          approval_state:  data.approval_state || null,
          clarification_state: data.clarification_state || null,
          browser_input_state: data.browser_input_state || null,
          browser_state: data.browser_state || {},
          artifacts:       data.artifacts || null,
        },
      }
      setMessages(prev => [...prev, assistantMessage])
      if (data.browser_input_state?.status === 'required') {
        setBrowserInputPending(data.browser_input_state)
      }
      loadConversationList()
    } catch (err) {
      setError(err.message || 'Failed to respond to approval.')
    } finally {
      setTaskApprovalPending(null)
    }
  }

  const handleWebAgentPermission = (data) => {
    setWebPermissionPending({ message: data.message || 'The web agent needs permission for a sensitive action.' })
  }

  const clearConversation = () => {
    setMessages([])
    localStorage.removeItem(CONVERSATION_ID_KEY)
    setConversationId(null)
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

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(e)
    }
    if (e.key === 'Escape') setSlashSuggestions([])
  }

  const selectSlashCommand = (cmd) => {
    setInputMessage(cmd + ' ')
    setSlashSuggestions([])
    inputRef.current?.focus()
  }

  // ── Onboarding ────────────────────────────────────────────────────────────

  if (showNamePrompt) {
    return (
      <div className="onboarding-overlay">
        <div className="onboarding-card">
          <div className="onboarding-icon">🤖</div>
          <h2>Welcome to SonarBot</h2>
          <p>What should I call you?</p>
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

  // ── Main Layout ───────────────────────────────────────────────────────────
  return (
    <div className="app-layout">

      {/* ── Sidebar ── */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <span className="brand-icon">🤖</span>
            {sidebarOpen && <span className="brand-name">SonarBot</span>}
          </div>
          <button className="btn-icon sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)}
            title={sidebarOpen ? 'Collapse' : 'Expand'}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d={sidebarOpen ? 'M15 18l-6-6 6-6' : 'M9 18l6-6-6-6'} />
            </svg>
          </button>
        </div>

        {/* ── Chats ── */}
        <>
          <button className="btn-new-chat" onClick={clearConversation}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
            </svg>
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
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                    </svg>
                    <span className="conv-title">{conv.title || conv.conversation_id?.substring(0, 24)}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </>

        {/* ── Profile Footer ── */}
        <div className="sidebar-footer" ref={profileRef}>
          {showProfile && sidebarOpen && (
            <div className="profile-dropdown">
              <div className="profile-dropdown-header">
                <div className="avatar lg">{(getUserName() || 'U')[0].toUpperCase()}</div>
                <div>
                  <div className="profile-name">{getUserName() || 'User'}</div>
                  <div className="profile-id">{userId.substring(0, 16)}…</div>
                </div>
              </div>
              <div className="profile-dropdown-divider" />
              {googleConnected ? (
                <button className="profile-dropdown-item" onClick={disconnectGoogle}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
                  </svg>
                  Disconnect Google
                </button>
              ) : (
                <button className="profile-dropdown-item" onClick={connectGoogle}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
                  </svg>
                  Connect Google
                </button>
              )}
              <div className="profile-dropdown-item version">SonarBot v0.4.0</div>
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
              <svg className="profile-dots" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="12" cy="19" r="1.5" />
              </svg>
            )}
          </button>
        </div>
      </aside>

      {/* ── Main Chat Area ── */}
      <main className="chat-main">
        <header className="chat-topbar">
          {!sidebarOpen && (
            <button className="btn-icon" onClick={() => setSidebarOpen(true)} title="Open sidebar">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
          )}
          <div className="topbar-title">{conversationId ? 'Chat' : 'New Chat'}</div>
          <div className="topbar-actions">
            {progress && <div className="topbar-progress">{progress}</div>}
          </div>
        </header>

        {error && (
          <div className="error-banner">
            <span>⚠️ {error}</span>
            <button onClick={() => setError(null)} className="btn-icon-sm">✕</button>
          </div>
        )}

        {webPermissionPending && (
          <div className="permission-banner">
            <div className="permission-icon">⚠️</div>
            <div className="permission-content">
              <div className="permission-title">Web Agent — Permission Required</div>
              <div className="permission-desc">{webPermissionPending.message}</div>
            </div>
            <div className="permission-actions">
              <button className="btn-permission approve" onClick={() => respondToWebPermission(true)}>✅ Approve</button>
              <button className="btn-permission deny"    onClick={() => respondToWebPermission(false)}>❌ Deny</button>
            </div>
          </div>
        )}

        {taskApprovalPending && (
          <div className="permission-banner">
            <div className="permission-icon">⚠️</div>
            <div className="permission-content">
              <div className="permission-title">Approval Required</div>
              <div className="permission-desc">{taskApprovalPending.reason}</div>
            </div>
            <div className="permission-actions">
              <button className="btn-permission approve" onClick={() => respondToTaskApproval(true)}>Approve</button>
              <button className="btn-permission deny"    onClick={() => respondToTaskApproval(false)}>Deny</button>
            </div>
          </div>
        )}

        <div className="chat-messages">
          <MessageList messages={messages} isLoading={isLoading} onClarificationSelect={handleClarificationSelect} />
          <div ref={messagesEndRef} />
        </div>

        {/* ── Input area ── */}
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

          {browserInputPending?.status === 'required' && (
            <div className="browser-input-banner">
              <div className="browser-input-title">Browser Input Required</div>
              <div className="browser-input-desc">
                {browserInputPending.reason || `Please provide ${browserInputPending.field_description || 'the requested input'}.`}
              </div>
              <form className="browser-input-form" onSubmit={submitBrowserInput}>
                <input
                  type={browserInputPending.input_type === 'password' ? 'password' : 'text'}
                  value={browserInputValue}
                  onChange={(e) => setBrowserInputValue(e.target.value)}
                  placeholder={`Provide ${browserInputPending.field_description || 'input'}`}
                  className="browser-input-field"
                  autoComplete="off"
                />
                <button type="submit" className="btn-send" disabled={!browserInputValue.trim() || isLoading}>
                  Continue
                </button>
              </form>
              <div className="browser-input-hint">
                Your answer continues the active browser task. Secret values are not echoed back into the chat history.
              </div>
            </div>
          )}

          <form onSubmit={sendMessage} className="chat-form">
            <input
              ref={inputRef}
              type="text"
              value={inputMessage}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={isLoading ? 'Processing…' : 'Message SonarBot…'}
              className="chat-input"
              disabled={isLoading || browserInputPending?.status === 'required'}
              autoFocus
            />
            <button
              type="submit"
              className="btn-send"
              disabled={!inputMessage.trim() || isLoading || browserInputPending?.status === 'required'}
            >
              {isLoading ? (
                <span className="send-spinner" />
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
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
