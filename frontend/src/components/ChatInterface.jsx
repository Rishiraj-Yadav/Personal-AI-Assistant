import { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import MessageList from './MessageList'
import { getUserId, getUserName, setUserName, hasUserName } from '../utils/userId'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

// ✅ Store conversation ID in localStorage
const CONVERSATION_ID_KEY = 'sonarbot_conversation_id';

function ChatInterface() {
  const [messages, setMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  const [userId] = useState(getUserId())
  const [showNamePrompt, setShowNamePrompt] = useState(!hasUserName())
  
  // ✅ Load conversation ID from localStorage on mount
  const [conversationId, setConversationId] = useState(() => {
    return localStorage.getItem(CONVERSATION_ID_KEY) || null
  })
  
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, progress])

  // ✅ Load conversation history when component mounts
  useEffect(() => {
    if (conversationId) {
      loadConversationHistory(conversationId)
    }
  }, [])

  // ✅ Save conversation ID to localStorage whenever it changes
  useEffect(() => {
    if (conversationId) {
      localStorage.setItem(CONVERSATION_ID_KEY, conversationId)
      console.log('💾 Saved conversation ID:', conversationId)
    }
  }, [conversationId])

  // ✅ Load previous conversation from database
  const loadConversationHistory = async (convId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/multi-agent/conversation/${convId}`)
      if (response.data && response.data.messages) {
        setMessages(response.data.messages)
        console.log(`✅ Loaded ${response.data.messages.length} messages from ${convId}`)
      }
    } catch (err) {
      console.warn('Could not load conversation history:', err)
      if (err.response?.status === 404) {
        // Conversation not found, clear stored ID
        localStorage.removeItem(CONVERSATION_ID_KEY)
        setConversationId(null)
      }
    }
  }

  const handleSetName = (name) => {
    if (name.trim()) {
      setUserName(name.trim())
      setShowNamePrompt(false)
    }
  }

  const sendMessage = async (e) => {
    e.preventDefault()
    
    if (!inputMessage.trim() || isLoading) return

    const userMessage = {
      role: 'user',
      content: inputMessage,
      timestamp: new Date().toISOString()
    }

    setMessages(prev => [...prev, userMessage])
    setInputMessage('')
    setIsLoading(true)
    setError(null)
    setProgress(null)

    try {
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
          language: response.data.language
        }
      }

      setMessages(prev => [...prev, assistantMessage])
      
      // ✅ Save conversation ID if new
      if (!conversationId && response.data.conversation_id) {
        setConversationId(response.data.conversation_id)
      }

    } catch (err) {
      console.error('Error sending message:', err)
      setError(err.response?.data?.detail || 'Failed to send message. Please try again.')
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
          message: message,
          user_id: userId,
          conversation_id: conversationId,  // ✅ Send existing conversation ID
          max_iterations: 5
        }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        
        if (data.type === 'router') {
          setProgress('🎯 ' + data.message)
        } else if (data.type === 'classification') {
          setProgress(`📍 Detected: ${data.task_type} task`)
        } else if (data.type === 'generating') {
          setProgress('🎨 ' + data.message)
        } else if (data.type === 'iteration') {
          setProgress(`🔄 Iteration ${data.iteration}/${data.total}`)
        } else if (data.type === 'fixing') {
          setProgress('🔧 ' + data.message)
        } else if (data.type === 'success') {
          setProgress('✅ ' + data.message)
        } else if (data.type === 'complete') {
          finalResult = data.result
          ws.close()
        } else if (data.type === 'error') {
          reject(new Error(data.message))
          ws.close()
        }
      }

      ws.onerror = (error) => {
        reject(error)
        ws.close()
      }

      ws.onclose = () => {
        if (finalResult) {
          resolve({
            data: {
              response: finalResult.response,
              conversation_id: conversationId || finalResult.conversation_id || 'new_conv',
              timestamp: new Date().toISOString(),
              model_used: 'Smart Multi-Agent (Gemini)',
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
              metadata: finalResult.metadata
            }
          })
        } else {
          reject(new Error('WebSocket closed without result'))
        }
      }
    })
  }

  const clearConversation = async () => {
    // ✅ Clear both UI and stored conversation ID
    setMessages([])
    localStorage.removeItem(CONVERSATION_ID_KEY)
    setConversationId(null)
    setError(null)
    setProgress(null)
    
    console.log('🗑️ Started new conversation')
  }

  if (showNamePrompt) {
    return (
      <div className="name-prompt-modal">
        <div className="name-prompt-content">
          <h2>👋 Welcome to SonarBot!</h2>
          <p>What should I call you? (Optional)</p>
          <form onSubmit={(e) => {
            e.preventDefault()
            const name = e.target.name.value
            handleSetName(name || 'User')
          }}>
            <input
              type="text"
              name="name"
              placeholder="Your name"
              autoFocus
              className="name-input"
            />
            <div className="name-buttons">
              <button type="submit" className="btn-primary">
                Let's go!
              </button>
              <button
                type="button"
                onClick={() => handleSetName('User')}
                className="btn-secondary"
              >
                Skip
              </button>
            </div>
          </form>
          <small className="name-hint">
            💡 I'll remember your preferences to personalize our interactions
          </small>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-interface">
      <div className="chat-controls">
        <button 
          onClick={clearConversation}
          className="btn-clear"
          disabled={messages.length === 0}
        >
          🗑️ New Chat
        </button>

        <div className="user-info">
          <span className="user-name">
            👤 {getUserName() || 'User'}
          </span>
          <small className="user-id" title={userId}>
            ID: {userId.substr(0, 12)}...
          </small>
          {conversationId && (
            <small className="conv-id" title={conversationId}>
              💬 Active conversation
            </small>
          )}
        </div>
      </div>

      {error && (
        <div className="error-message">
          ⚠️ {error}
          <button onClick={() => setError(null)} className="btn-close">×</button>
        </div>
      )}

      {progress && (
        <div className="progress-bar">
          <div className="progress-message">{progress}</div>
        </div>
      )}

      <MessageList messages={messages} isLoading={isLoading} />
      <div ref={messagesEndRef} />

      <form onSubmit={sendMessage} className="chat-input-form">
        <input
          type="text"
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          placeholder="Ask me anything - I'll remember our conversation! 🧠"
          className="chat-input"
          disabled={isLoading}
          autoFocus
        />
        <button 
          type="submit" 
          className="btn-send"
          disabled={!inputMessage.trim() || isLoading}
        >
          {isLoading ? '⏳' : '📤'} Send
        </button>
      </form>

      <div className="mode-indicator">
        🤖 Smart Agent with Memory - Remembers conversations forever
      </div>
    </div>
  )
}

export default ChatInterface