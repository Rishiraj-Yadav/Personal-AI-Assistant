import { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import MessageList from './MessageList'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

function ChatInterface({ conversationId, setConversationId }) {
  const [messages, setMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const sendMessage = async (e) => {
    e.preventDefault()
    
    if (!inputMessage.trim() || isLoading) return

    const userMessage = {
      role: 'user',
      content: inputMessage,
      timestamp: new Date().toISOString()
    }

    // Add user message immediately
    setMessages(prev => [...prev, userMessage])
    setInputMessage('')
    setIsLoading(true)
    setError(null)

    try {
      const response = await axios.post(`${API_BASE_URL}/chat`, {
        message: inputMessage,
        conversation_id: conversationId,
        user_id: 'web_user'
      })

      // Add assistant response
      const assistantMessage = {
        role: 'assistant',
        content: response.data.response,
        timestamp: response.data.timestamp,
        metadata: {
          model: response.data.model_used,
          tokens: response.data.tokens_used,
          skills_used: response.data.skills_used || []
        }
      }

      setMessages(prev => [...prev, assistantMessage])
      
      // Update conversation ID if it's a new conversation
      if (!conversationId) {
        setConversationId(response.data.conversation_id)
      }

    } catch (err) {
      console.error('Error sending message:', err)
      setError(err.response?.data?.detail || 'Failed to send message. Please try again.')
      
      // Remove the user message if request failed
      setMessages(prev => prev.slice(0, -1))
    } finally {
      setIsLoading(false)
    }
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
    } catch (err) {
      console.error('Error clearing conversation:', err)
      setError('Failed to clear conversation')
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
          🗑️ Clear Chat
        </button>
      </div>

      {error && (
        <div className="error-message">
          ⚠️ {error}
          <button onClick={() => setError(null)} className="btn-close">×</button>
        </div>
      )}

      <MessageList messages={messages} isLoading={isLoading} />
      <div ref={messagesEndRef} />

      <form onSubmit={sendMessage} className="chat-input-form">
        <input
          type="text"
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          placeholder="Type your message here..."
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
    </div>
  )
}

export default ChatInterface