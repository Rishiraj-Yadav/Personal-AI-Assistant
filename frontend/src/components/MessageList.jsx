function MessageList({ messages, isLoading }) {
  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit' 
    })
  }

  return (
    <div className="message-list">
      {messages.length === 0 && !isLoading && (
        <div className="welcome-message">
          <h2>👋 Welcome to OpenClaw Agent!</h2>
          <p>I'm your AI assistant powered by Groq's Llama model.</p>
          <p>Ask me anything or request help with tasks!</p>
          <div className="example-prompts">
            <p><strong>Try asking:</strong></p>
            <ul>
              <li>"Help me plan my day"</li>
              <li>"Explain quantum computing simply"</li>
              <li>"Create a task list for a project"</li>
            </ul>
          </div>
        </div>
      )}

      {messages.map((message, index) => (
        <div key={index} className={`message message-${message.role}`}>
          <div className="message-header">
            <span className="message-role">
              {message.role === 'user' ? '👤 You' : '🤖 Agent'}
            </span>
            <span className="message-time">
              {formatTimestamp(message.timestamp)}
            </span>
          </div>
          <div className="message-content">
            {message.content}
          </div>
          {message.metadata && (
            <div className="message-metadata">
              Model: {message.metadata.model} | Tokens: {message.metadata.tokens}
              {message.metadata.skills_used && message.metadata.skills_used.length > 0 && (
                <>
                  <br />
                  <span className="skills-used">
                    🔧 Skills used: {message.metadata.skills_used.map(s => s.skill_name).join(', ')}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      ))}

      {isLoading && (
        <div className="message message-assistant">
          <div className="message-header">
            <span className="message-role">🤖 Agent</span>
          </div>
          <div className="message-content loading">
            <div className="typing-indicator">
              <span></span>
              <span></span>
              <span></span>
            </div>
            Thinking...
          </div>
        </div>
      )}
    </div>
  )
}

export default MessageList