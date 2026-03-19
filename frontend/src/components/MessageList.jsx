function MessageList({ messages, isLoading, onClarificationSelect }) {
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
                <span className="file-icon">FILE</span>
                <span className="file-name">{key}</span>
                <button
                  onClick={() => navigator.clipboard.writeText(files[currentPath])}
                  className="btn-copy-sm"
                >
                  Copy
                </button>
              </div>
            ) : (
              <>
                <div className="folder-item">
                  <span className="folder-icon">DIR</span> {key}/
                </div>
                {renderTree(value, currentPath, level + 1)}
              </>
            )}
          </div>
        )
      })
    }

    return (
      <div className="file-tree">
        <div className="file-tree-header">Project Structure</div>
        {renderTree(structure)}
      </div>
    )
  }

  const renderCode = (code, language = 'python') => (
    <div className="code-block">
      <div className="code-header">
        <span className="code-lang">{language}</span>
        <button onClick={() => navigator.clipboard.writeText(code)} className="btn-copy">
          Copy
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  )

  const summarizeEvidence = (entry) => {
    if (!entry) return 'Evidence captured'
    if (typeof entry === 'string') return entry
    if (entry.path) return `Path: ${entry.path}`
    if (entry.title) return `Window: ${entry.title}`
    if (entry.text) return `Text: ${String(entry.text).slice(0, 120)}`
    if (entry.value) return `${entry.type || 'value'}: ${entry.value}`
    if (entry.type) return entry.type
    return 'Evidence captured'
  }

  const shouldShowExecutionDetails = (metadata) => {
    if (!metadata) return false
    return metadata.show_debug_execution === true || import.meta.env.VITE_SHOW_EXECUTION_DEBUG === 'true'
  }

  const shouldShowMessageMeta = (metadata) => {
    if (!metadata) return false
    return metadata.show_debug_execution === true || import.meta.env.VITE_SHOW_EXECUTION_DEBUG === 'true'
  }

  const renderPlan = (plan) => {
    if (!plan || !plan.steps?.length) return null

    return (
      <div className="execution-card">
        <div className="execution-card-header">
          <span>Plan</span>
          {plan.workflow_name && <span className="execution-pill">{plan.workflow_name}</span>}
        </div>
        <div className="execution-summary">{plan.summary}</div>
        <div className="execution-steps">
          {plan.steps.map((step) => (
            <div key={step.step_id} className="execution-step">
              <span className={`step-status ${step.status || 'pending'}`}>{step.status || 'pending'}</span>
              <div className="step-main">
                <div className="step-goal">{step.goal}</div>
                <div className="step-meta-line">
                  {step.agent_type}
                  {step.tool_name ? ` | ${step.tool_name}` : ''}
                  {step.approval_level !== 'none' ? ` | ${step.approval_level}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderTrace = (trace) => {
    if (!trace?.length) return null

    return (
      <div className="execution-card">
        <div className="execution-card-header">
          <span>Execution Trace</span>
          <span className="execution-pill">{trace.length} events</span>
        </div>
        <div className="trace-list">
          {trace.map((event, index) => (
            <div key={`${event.event_type}-${event.step_id || index}`} className="trace-event">
              <span
                className={`trace-dot ${
                  event.success === true ? 'success' : event.success === false ? 'failed' : 'neutral'
                }`}
              />
              <div className="trace-main">
                <div className="trace-title">
                  <span className="trace-phase">{event.phase}</span>
                  <span>{event.message}</span>
                </div>
                <div className="trace-meta-line">
                  {event.event_type}
                  {event.step_id ? ` | ${event.step_id}` : ''}
                  {event.agent_type ? ` | ${event.agent_type}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const renderEvidence = (artifacts) => {
    const evidence = artifacts?.desktop_evidence || artifacts?.desktop_result?.evidence || []
    if (!evidence.length) return null

    return (
      <div className="execution-card">
        <div className="execution-card-header">
          <span>Evidence</span>
          <span className="execution-pill">{evidence.length}</span>
        </div>
        <div className="evidence-list">
          {evidence.slice(0, 6).map((entry, index) => (
            <div key={index} className="evidence-item">{summarizeEvidence(entry)}</div>
          ))}
        </div>
      </div>
    )
  }

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="message-list">
        <div className="welcome">
          <div className="welcome-icon">SB</div>
          <h2>How can I help you today?</h2>
          <p className="welcome-sub">I can write code, control your desktop, browse the web, manage emails, and more.</p>
          <div className="welcome-grid">
            <div className="welcome-card">
              <div className="wc-icon">DEV</div>
              <div className="wc-label">Write Code</div>
              <div className="wc-example">"Create a React todo app"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">WEB</div>
              <div className="wc-label">Web Agent</div>
              <div className="wc-example">"Search the web for best laptops 2026"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">DESK</div>
              <div className="wc-label">Desktop Control</div>
              <div className="wc-example">"Open Chrome and take a screenshot"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">MAIL</div>
              <div className="wc-label">Email & Calendar</div>
              <div className="wc-example">"Check my unread emails"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">INFO</div>
              <div className="wc-label">Research</div>
              <div className="wc-example">"Research AI news and summarize"</div>
            </div>
            <div className="welcome-card">
              <div className="wc-icon">TASK</div>
              <div className="wc-label">Workflows</div>
              <div className="wc-example">"Open my coding setup"</div>
            </div>
          </div>
        </div>
      </div>
    )
  }

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

            {message.metadata?.approval_state?.status === 'required' && (
              <div className="approval-note">
                Approval required: {message.metadata.approval_state.reason || 'Confirmation needed before continuing.'}
              </div>
            )}

            {message.metadata?.clarification_state?.status === 'required' && (
              <div className="clarification-card">
                <div className="clarification-header">Clarification needed: reply with the number or full path shown above.</div>
                {message.metadata.clarification_state.options?.length > 0 && (
                  <div className="clarification-options">
                    {message.metadata.clarification_state.options.map((opt, optIdx) => (
                      <button
                        key={optIdx}
                        className="clarification-option-btn"
                        onClick={() => onClarificationSelect && onClarificationSelect(String(opt.index || optIdx + 1))}
                        title={opt.path || opt.label}
                      >
                        <span className="clar-opt-num">{opt.index || optIdx + 1}</span>
                        <span className="clar-opt-path">{opt.path || opt.label}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {message.metadata?.file_content && (
              <div className="file-content-card">
                <div className="file-content-header">
                  <span className="file-content-icon">FILE</span>
                  <span className="file-content-name">{message.metadata.file_content_path || 'File content'}</span>
                  <button
                    className="btn-copy-sm"
                    onClick={() => navigator.clipboard.writeText(message.metadata.file_content)}
                  >Copy</button>
                </div>
                <pre className="file-content-body"><code>{message.metadata.file_content}</code></pre>
              </div>
            )}

            {message.metadata?.files && Object.keys(message.metadata.files).length > 1 && (
              <div className="project-display">
                {message.metadata.project_structure && renderFileTree(message.metadata.project_structure, message.metadata.files)}
                {message.metadata.main_file && (
                  <div className="main-file-preview">
                    <div className="preview-header">{message.metadata.main_file}</div>
                    {renderCode(message.metadata.files[message.metadata.main_file], message.metadata.language)}
                  </div>
                )}
                {message.metadata.server_running && (
                  <div className="server-info">
                    <span>Server running at </span>
                    <a href={message.metadata.server_url} target="_blank" rel="noopener noreferrer">
                      {message.metadata.server_url}
                    </a>
                  </div>
                )}
              </div>
            )}

            {message.metadata?.web_screenshots && message.metadata.web_screenshots.length > 0 && (
              <div className="web-agent-screenshots">
                <div className="web-screenshot-header">Web Agent Browser View</div>
                {message.metadata.web_current_url && (
                  <div className="web-url-bar">
                    <span className="url-text">{message.metadata.web_current_url}</span>
                  </div>
                )}
                <div className="web-screenshot-frame">
                  <img
                    src={`data:image/png;base64,${message.metadata.web_screenshots[message.metadata.web_screenshots.length - 1]}`}
                    alt="Web page screenshot"
                    className="web-screenshot-img"
                  />
                </div>
              </div>
            )}

            {message.metadata?.web_autonomous && (
              <div className="web-agent-info">
                <span className="meta-badge web-auto">Autonomous Web Agent</span>
                {message.metadata.web_actions_count > 0 && (
                  <span className="meta-badge web-actions">{message.metadata.web_actions_count} actions performed</span>
                )}
              </div>
            )}

            {message.metadata?.code && !message.metadata?.files && (
              <div className="msg-code">
                {renderCode(message.metadata.code, message.metadata.language)}
                {message.metadata.file_path && (
                  <div className="file-info">Saved to: <code>{message.metadata.file_path}</code></div>
                )}
              </div>
            )}

            {shouldShowExecutionDetails(message.metadata) && renderPlan(message.metadata?.plan)}
            {shouldShowExecutionDetails(message.metadata) && renderTrace(message.metadata?.execution_trace)}
            {shouldShowExecutionDetails(message.metadata) && renderEvidence(message.metadata?.artifacts)}

            {shouldShowMessageMeta(message.metadata) && message.metadata && (message.metadata.task_type || message.metadata.agent_path?.length > 0) && (
              <div className="msg-meta">
                {message.metadata.task_type && (
                  <span className="meta-badge type">{message.metadata.task_type}</span>
                )}
                {message.metadata.agent_path && [...new Set(message.metadata.agent_path)].map((agent, agentIndex) => (
                  <span key={agentIndex} className="meta-badge agent">{agent}</span>
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
