function MessageList({ messages, isLoading }) {
  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  }

  const renderFileTree = (structure, files) => {
    const renderTree = (node, path = '', level = 0) => {
      return Object.entries(node).map(([key, value]) => {
        const currentPath = path ? `${path}/${key}` : key
        const isFile = value === 'file' || typeof value === 'string'
        return (
          <div key={currentPath} style={{ marginLeft: `${level * 16}px` }}>
            {isFile ? (
              <div className="file-item">
                <span className="file-icon">📄</span>
                <span className="file-name">{key}</span>
                <button onClick={() => navigator.clipboard.writeText(files[currentPath])} className="btn-copy-sm">Copy</button>
              </div>
            ) : (
              <>
                <div className="folder-item"><span className="folder-icon">📁</span> {key}/</div>
                {renderTree(value, currentPath, level + 1)}
              </>
            )}
          </div>
        )
      })
    }
    return (
      <div className="file-tree">
        <div className="file-tree-header">📁 Project Structure</div>
        {renderTree(structure)}
      </div>
    )
  }

  const renderCode = (code, language = 'python') => (
    <div className="code-block">
      <div className="code-header">
        <span className="code-lang">{language}</span>
        <button onClick={() => navigator.clipboard.writeText(code)} className="btn-copy">📋 Copy</button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  )

  /* ── Welcome Screen ── */
  if (messages.length === 0 && !isLoading) {
    return (
      <div className="message-list">
        <div className="welcome">
          <div className="welcome-icon">🤖</div>
          <h2>How can I help you today?</h2>
          <p className="welcome-sub">I can write code, control your desktop, browse the web, manage emails, and more.</p>
          <div className="welcome-grid">
            <div className="welcome-card">
              <div className="wc-icon">💻</div>
              <div className="wc-label">Write Code</div>
              <div className="wc-example">"Create a React todo app"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">🌐</div>
              <div className="wc-label">Web Tasks</div>
              <div className="wc-example">"Scrape prices from Amazon"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">🖥️</div>
              <div className="wc-label">Desktop Control</div>
              <div className="wc-example">"Open Chrome and take a screenshot"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">📧</div>
              <div className="wc-label">Email & Calendar</div>
              <div className="wc-example">"Check my unread emails"</div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  /* ── Message Display ── */
  return (
    <div className="message-list">
      {messages.map((message, index) => (
        <div key={index} className={`msg ${message.role}`}>
          <div className="msg-avatar">
            {message.role === 'user' ? (
              <div className="avatar sm user-av">Y</div>
            ) : (
              <div className="avatar sm bot-av">S</div>
            )}
          </div>
          <div className="msg-body">
            <div className="msg-header">
              <span className="msg-role">{message.role === 'user' ? 'You' : 'SonarBot'}</span>
              <span className="msg-time">{formatTimestamp(message.timestamp)}</span>
            </div>
            <div className="msg-content">{message.content}</div>

            {/* Multi-file project */}
            {message.metadata?.files && Object.keys(message.metadata.files).length > 1 && (
              <div className="project-display">
                {message.metadata.project_structure && renderFileTree(message.metadata.project_structure, message.metadata.files)}
                {message.metadata.main_file && (
                  <div className="main-file-preview">
                    <div className="preview-header">🚀 {message.metadata.main_file}</div>
                    {renderCode(message.metadata.files[message.metadata.main_file], message.metadata.language)}
                  </div>
                )}
                {message.metadata.server_running && (
                  <div className="server-info">
                    <span>✅ Server running at </span>
                    <a href={message.metadata.server_url} target="_blank" rel="noopener noreferrer">{message.metadata.server_url}</a>
                  </div>
                )}
              </div>
            )}

            {/* Single file code */}
            {message.metadata?.code && !message.metadata?.files && (
              <div className="msg-code">
                {renderCode(message.metadata.code, message.metadata.language)}
                {message.metadata.file_path && (
                  <div className="file-info">💾 Saved to: <code>{message.metadata.file_path}</code></div>
                )}
              </div>
            )}

            {/* Metadata badges */}
            {message.metadata && (message.metadata.task_type || message.metadata.agent_path?.length > 0) && (
              <div className="msg-meta">
                {message.metadata.task_type && (
                  <span className="meta-badge type">{message.metadata.task_type}</span>
                )}
                {message.metadata.agent_path && [...new Set(message.metadata.agent_path)].map((agent, i) => (
                  <span key={i} className="meta-badge agent">{agent}</span>
                ))}
                {message.metadata.iterations && (
                  <span className="meta-badge iter">{message.metadata.iterations} iterations</span>
                )}
              </div>
            )}
          </div>
        </div>
      ))}

      {isLoading && (
        <div className="msg assistant">
          <div className="msg-avatar"><div className="avatar sm bot-av">S</div></div>
          <div className="msg-body">
            <div className="msg-header"><span className="msg-role">SonarBot</span></div>
            <div className="msg-content loading">
              <div className="typing-dots"><span /><span /><span /></div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MessageList
