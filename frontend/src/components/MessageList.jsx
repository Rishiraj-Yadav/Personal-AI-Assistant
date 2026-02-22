function MessageList({ messages, isLoading }) {
  const formatTimestamp = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit'
    })
  }

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
                >Copy</button>
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
          >Copy</button>
        </div>
        <pre><code>{code}</code></pre>
      </div>
    )
  }

  return (
    <div className="message-list">
      {messages.length === 0 && !isLoading && (
        <div className="welcome-message">
          <div className="welcome-icon">⚡</div>
          <h2>How can I help you?</h2>
          <p>I can automate your desktop, browse the web, write code, and more.</p>

          <div className="mode-cards">
            <div className="mode-card">
              <h3>💬 Chat</h3>
              <p>Conversations, desktop control, web scraping</p>
            </div>
            <div className="mode-card highlight">
              <h3>🤖 Multi-Agent</h3>
              <p>Code generation with auto-testing & fixing</p>
            </div>
          </div>

          <div className="suggestion-chips">
            <button className="suggestion-chip">💡 Open Task Manager</button>
            <button className="suggestion-chip">💡 What's the weather?</button>
            <button className="suggestion-chip">💡 Write a Python script</button>
            <button className="suggestion-chip">💡 Search YouTube</button>
          </div>
        </div>
      )}

      {messages.map((message, index) => (
        <div key={index} className={`message message-${message.role}`}>
          <div className="message-header">
            <span className="message-role">
              {message.role === 'user' ? 'You' : 'OpenClaw'}
            </span>
            <span className="message-time">
              {formatTimestamp(message.timestamp)}
            </span>
          </div>

          <div className="message-content">
            {message.content}
          </div>

          {/* Pipeline Steps Display */}
          {message.metadata?.pipeline_steps && message.metadata.pipeline_steps.length > 0 && (
            <div className="pipeline-display">
              <div className="pipeline-header">
                <span className="pipeline-icon">⚡</span>
                <span>Pipeline Execution</span>
                <span className="pipeline-complexity">
                  {message.metadata.pipeline_complexity || 'compound'}
                </span>
              </div>
              <div className="pipeline-steps">
                {message.metadata.pipeline_steps.map((step, i) => (
                  <div key={i} className={`pipeline-step ${step.success ? 'step-success' : 'step-failed'}`}>
                    <div className="step-status-icon">
                      {step.success ? '✅' : '❌'}
                    </div>
                    <div className="step-details">
                      <div className="step-header">
                        <span className="step-number">Step {i + 1}</span>
                        <span className={`step-agent-badge agent-${step.agent}`}>
                          {step.agent === 'desktop' ? '🖥️' :
                            step.agent === 'browser' ? '🌐' :
                              step.agent === 'coding' ? '💻' : '💬'} {step.agent}
                        </span>
                        <span className="step-action">{step.action}</span>
                      </div>
                      <div className="step-meta">
                        {step.duration_ms > 0 && (
                          <span className="step-duration">{step.duration_ms}ms</span>
                        )}
                        {step.attempt > 1 && (
                          <span className="step-retries">🔄 {step.attempt} attempts</span>
                        )}
                        {step.used_fallback && (
                          <span className="step-fallback">↩️ fallback</span>
                        )}
                      </div>
                      {step.error && (
                        <div className="step-error">⚠️ {step.error}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              {message.metadata.pipeline_duration_ms && (
                <div className="pipeline-footer">
                  Total: {message.metadata.pipeline_duration_ms}ms
                  {message.metadata.pipeline_id && (
                    <span className="pipeline-id">{message.metadata.pipeline_id}</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Multi-file project display */}
          {message.metadata?.files && Object.keys(message.metadata.files).length > 1 && (
            <div className="project-display">
              {message.metadata.project_structure && renderFileTree(
                message.metadata.project_structure,
                message.metadata.files
              )}
              {message.metadata.main_file && (
                <div className="main-file-preview">
                  <div className="preview-header">
                    🚀 {message.metadata.main_file}
                  </div>
                  {renderCode(
                    message.metadata.files[message.metadata.main_file],
                    message.metadata.language
                  )}
                </div>
              )}
              {message.metadata.server_running && (
                <div className="server-info success">
                  <div className="server-status">✅ Server is running!</div>
                  <div className="server-details">
                    <div>🌐 <a href={message.metadata.server_url} target="_blank" rel="noopener noreferrer">{message.metadata.server_url}</a></div>
                    <div>📦 {message.metadata.project_type}</div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Legacy single-file */}
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

          {/* Metadata */}
          {message.metadata && message.role === 'assistant' && (
            <div className="message-metadata">
              <div className="metadata-row">
                <span>{message.metadata.model || 'gemini-2.0-flash'}</span>
                {message.metadata.tokens && <span>· {message.metadata.tokens} tokens</span>}
              </div>

              {message.metadata.task_type && (
                <div className="metadata-row multi-agent-info">
                  <span className="task-type">📍 {message.metadata.task_type}</span>
                  {message.metadata.iterations && (
                    <span className="iterations">🔄 {message.metadata.iterations} iterations</span>
                  )}
                </div>
              )}

              {message.metadata.agent_path && message.metadata.agent_path.length > 0 && (
                <div className="agent-path">
                  {message.metadata.agent_path.map((agent, i) => (
                    <span key={i} className="agent-badge">{agent}</span>
                  ))}
                </div>
              )}

              {message.metadata.skills_used && message.metadata.skills_used.length > 0 && (
                <div className="skills-used">
                  🔧 {message.metadata.skills_used.map(s =>
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
