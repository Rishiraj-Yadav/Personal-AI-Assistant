import { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import MessageList from './MessageList'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

function ChatInterface({ conversationId, setConversationId }) {
  const [messages, setMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [useMultiAgent, setUseMultiAgent] = useState(false)
  const [progress, setProgress] = useState(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, progress])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Auto-dismiss errors after 5 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 5000)
      return () => clearTimeout(timer)
    }
  }, [error])

  // Handle suggestion chip clicks
  const handleSuggestion = (text) => {
    // Strip the emoji prefix
    const cleanText = text.replace(/^[^\w]+\s*/, '')
    setInputMessage(cleanText)
    inputRef.current?.focus()
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
      let response

      if (useMultiAgent) {
        response = await sendWithMultiAgent(inputMessage)
      } else {
        response = await axios.post(`${API_BASE_URL}/chat`, {
          message: inputMessage,
          conversation_id: conversationId,
          user_id: 'web_user'
        })
      }

      const assistantMessage = {
        role: 'assistant',
        content: response.data.response,
        timestamp: response.data.timestamp || new Date().toISOString(),
        metadata: {
          model: response.data.model_used,
          tokens: response.data.tokens_used,
          skills_used: response.data.skills_used || [],
          task_type: response.data.task_type,
          agent_path: response.data.agent_path,
          iterations: response.data.metadata?.total_iterations,
          code: response.data.code,
          file_path: response.data.file_path
        }
      }

      setMessages(prev => [...prev, assistantMessage])

      if (!conversationId) {
        setConversationId(response.data.conversation_id)
      }

    } catch (err) {
      console.error('Error sending message:', err)
      setError(err.response?.data?.detail || 'Failed to send message. Please try again.')
      setMessages(prev => prev.slice(0, -1))
    } finally {
      setIsLoading(false)
      setProgress(null)
      inputRef.current?.focus()
    }
  }

  const sendWithMultiAgent = async (message) => {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://localhost:8000/api/v1/multi-agent/stream`)
      let finalResult = null

      ws.onopen = () => {
        ws.send(JSON.stringify({
          message: message,
          conversation_id: conversationId,
          max_iterations: 5
        }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.type === 'status') setProgress(data.message)
        else if (data.type === 'classification') setProgress(`📍 ${data.message}`)
        else if (data.type === 'iteration') setProgress(`🔄 Iteration ${data.iteration}/${data.total}`)
        else if (data.type === 'fixing') setProgress(`🔧 ${data.message}`)
        else if (data.type === 'complete') { finalResult = data.result; ws.close() }
        else if (data.type === 'error') { reject(new Error(data.message)); ws.close() }
      }

      ws.onerror = (error) => { reject(error); ws.close() }

      ws.onclose = () => {
        if (finalResult) {
          resolve({
            data: {
              response: finalResult.response,
              conversation_id: conversationId || 'multi_agent_conv',
              timestamp: new Date().toISOString(),
              model_used: 'Multi-Agent (Gemini)',
              task_type: finalResult.task_type,
              agent_path: finalResult.agent_path,
              code: finalResult.code,
              file_path: finalResult.file_path,
              metadata: finalResult.metadata
            }
          })
        } else {
          reject(new Error('Connection closed'))
        }
      }
    })
  }

  const clearConversation = async () => {
    if (!conversationId) {
      setMessages([])
      return
    }
    try {
      await axios.delete(`${API_BASE_URL}/conversation/${conversationId}`)
      setMessages([])
      setConversationId(null)
      setError(null)
      setProgress(null)
    } catch (err) {
      console.error('Error clearing conversation:', err)
    }
  }

  return (
    <div className="chat-interface">
      <div className="chat-controls">
        <button
          onClick={clearConversation}
          className="btn-clear"
          disabled={messages.length === 0}
        >
          🗑️ Clear
        </button>

        <div className="multi-agent-toggle">
          <label>
            <input
              type="checkbox"
              checked={useMultiAgent}
              onChange={(e) => setUseMultiAgent(e.target.checked)}
              disabled={isLoading}
            />
            <span className="toggle-label">
              Multi-Agent
              {useMultiAgent && <span className="badge">ON</span>}
            </span>
          </label>
        </div>
      </div>

      {error && (
        <div className="error-message">
          {error}
          <button onClick={() => setError(null)} className="btn-close">×</button>
        </div>
      )}

      {progress && (
        <div className="progress-bar">
          <div className="progress-message">{progress}</div>
        </div>
      )}

      <MessageList
        messages={messages}
        isLoading={isLoading}
        onSuggestionClick={handleSuggestion}
      />
      <div ref={messagesEndRef} />

      <form onSubmit={sendMessage} className="chat-input-form">
        <input
          ref={inputRef}
          type="text"
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          placeholder={useMultiAgent ? "Describe code to generate..." : "Message SoNAR..."}
          className="chat-input"
          disabled={isLoading}
          autoFocus
        />
        <button
          type="submit"
          className="btn-send"
          disabled={!inputMessage.trim() || isLoading}
        >
          {isLoading ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeDasharray="31.42" strokeDashoffset="10">
                <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite" />
              </circle>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3.4 20.4l17.45-7.48a1 1 0 0 0 0-1.84L3.4 3.6a.993.993 0 0 0-1.39.91L2 9.12c0 .5.37.93.87.99L17 12 2.87 13.88c-.5.07-.87.5-.87 1l.01 4.61c0 .71.73 1.2 1.39.91z" />
            </svg>
          )}
        </button>
      </form>
    </div>
  )
}

export default ChatInterface