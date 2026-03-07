function MessageList({ messages, isLoading }) {
  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit' 
    })
  }

  // ✅ NEW: File Tree Rendering Function
  const renderFileTree = (structure, files) => {
    const renderTree = (node, path = '', level = 0) => {
      return Object.entries(node).map(([key, value]) => {
        const currentPath = path ? `${path}/${key}` : key;
        const isFile = value === 'file' || typeof value === 'string';
        
        return (
          <div key={currentPath} style={{ marginLeft: `${level * 20}px` }}>
            {isFile ? (
              <div className="file-item">
                📄 <span className="file-name">{key}</span>
                <button 
                  onClick={() => navigator.clipboard.writeText(files[currentPath])}
                  className="btn-copy-small"
                >
                  Copy
                </button>
              </div>
            ) : (
              <>
                <div className="folder-item">📁 {key}/</div>
                {renderTree(value, currentPath, level + 1)}
              </>
            )}
          </div>
        );
      });
    };
    
    return (
      <div className="file-tree">
        <div className="file-tree-header">📁 Project Structure</div>
        {renderTree(structure)}
      </div>
    );
  };

  const renderCode = (code, language = 'python') => {
    return (
      <div className="code-block">
        <div className="code-header">
          <span className="code-language">{language}</span>
          <button 
            onClick={() => navigator.clipboard.writeText(code)}
            className="btn-copy"
          >
            📋 Copy
          </button>
        </div>
        <pre><code>{code}</code></pre>
      </div>
    )
  }

  return (
    <div className="message-list">
      // Update the welcome message section:

{messages.length === 0 && !isLoading && (
  <div className="welcome-message">
    <h2>👋 Welcome to SonarBot!</h2>
    <p>I automatically detect what you need - just ask naturally!</p>
    
    <div className="feature-cards">
      <div className="feature-card">
        <h3>🤖 Smart Detection</h3>
        <p>No buttons, no modes - I figure out what you want</p>
      </div>
      
      <div className="feature-card">
        <h3>🧠 Learns Your Style</h3>
        <p>Remembers your preferences over time</p>
      </div>
      
      <div className="feature-card">
        <h3>💻 Full Context</h3>
        <p>Knows our conversation history</p>
      </div>
    </div>

    <div className="example-prompts">
      <p><strong>Just ask naturally:</strong></p>
      <ul>
        <li>"create a react todo app" → Detects: Coding</li>
        <li>"open Chrome" → Detects: Desktop control</li>
        <li>"scrape example.com" → Detects: Web scraping</li>
        <li>"explain quantum physics" → Detects: General chat</li>
      </ul>
      <p className="smart-note">
        ✨ I learn from each interaction to serve you better!
      </p>
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

          {/* ✅ Multi-file project display */}
          {message.metadata?.files && Object.keys(message.metadata.files).length > 1 && (
            <div className="project-display">
              
              {/* File tree */}
              {message.metadata.project_structure && renderFileTree(
                message.metadata.project_structure,
                message.metadata.files
              )}
              
              {/* Main file preview */}
              {message.metadata.main_file && (
                <div className="main-file-preview">
                  <div className="preview-header">
                    🚀 {message.metadata.main_file} (Entry Point)
                  </div>
                  {renderCode(
                    message.metadata.files[message.metadata.main_file],
                    message.metadata.language
                  )}
                </div>
              )}
              
              {/* Server info */}
              {message.metadata.server_running && (
                <div className="server-info success">
                  <div className="server-status">
                    ✅ Server is running!
                  </div>
                  <div className="server-details">
                    <div>
                      🌐 Live Preview:{" "}
                      <a 
                        href={message.metadata.server_url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                      >
                        {message.metadata.server_url}
                      </a>
                    </div>
                    <div>🔌 Port: {message.metadata.server_port}</div>
                    <div>📦 Type: {message.metadata.project_type}</div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ✅ Legacy single-file display */}
          {message.metadata?.code && !message.metadata?.files && (
            <div className="message-code">
              {renderCode(message.metadata.code, message.metadata.language)}
              {message.metadata.file_path && (
                <div className="file-info">
                  💾 Saved to: <code>{message.metadata.file_path}</code>
                </div>
              )}
            </div>
          )}
          
          {/* Metadata section */}
          {message.metadata && (
            <div className="message-metadata">
              <div className="metadata-row">
                <span>Model: {message.metadata.model}</span>
                {message.metadata.tokens && <span>Tokens: {message.metadata.tokens}</span>}
              </div>

              {message.metadata.task_type && (
                <div className="metadata-row multi-agent-info">
                  <span className="task-type">
                    📍 Task: {message.metadata.task_type}
                  </span>
                  {message.metadata.iterations && (
                    <span className="iterations">
                      🔄 Iterations: {message.metadata.iterations}
                    </span>
                  )}
                </div>
              )}

              {message.metadata.agent_path && message.metadata.agent_path.length > 0 && (
                <div className="agent-path">
                  <span className="agent-path-label">🤖 Agents used:</span>
                  {message.metadata.agent_path.map((agent, i) => (
                    <span key={i} className="agent-badge">{agent}</span>
                  ))}
                </div>
              )}

              {message.metadata.skills_used && message.metadata.skills_used.length > 0 && (
                <div className="skills-used">
                  🔧 Skills: {message.metadata.skills_used.map(s => 
                    typeof s === 'string' ? s : s.skill_name
                  ).join(', ')}
                </div>
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
            Processing...
          </div>
        </div>
      )}
    </div>
  )
}

export default MessageList
