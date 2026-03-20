/**
 * Enhanced Chat Interface - Phase 4
 *
 * Integrated chat with:
 * - Persistent session
 * - Real-time WebSocket communication
 * - Action display
 * - Streaming responses
 * - Cancel request support
 */

import React, { useState, useEffect, useRef } from 'react';
import { wsHandler } from '../services/websocketHandler';
import { sessionManager } from '../services/sessionManager';
import ActionDisplay from './ActionDisplay';
import './EnhancedChat.css';

const EnhancedChat = () => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingMessage, setThinkingMessage] = useState('');
  const [currentAction, setCurrentAction] = useState(null);
  const [completedActions, setCompletedActions] = useState([]);
  const [activeRequestId, setActiveRequestId] = useState(null);
  const [streamingMessage, setStreamingMessage] = useState('');

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Initialize WebSocket on mount
  useEffect(() => {
    console.log('Connecting to assistant...');
    wsHandler.connect();

    // Register event handlers
    wsHandler.on('connected', handleConnected);
    wsHandler.on('disconnected', handleDisconnected);
    wsHandler.on('ack', handleAck);
    wsHandler.on('thinking', handleThinking);
    wsHandler.on('stream_chunk', handleStreamChunk);
    wsHandler.on('stream_end', handleStreamEnd);
    wsHandler.on('action_started', handleActionStarted);
    wsHandler.on('action_progress', handleActionProgress);
    wsHandler.on('action_completed', handleActionCompleted);
    wsHandler.on('action_failed', handleActionFailed);
    wsHandler.on('desktop_result', handleDesktopResult);
    wsHandler.on('complete', handleComplete);
    wsHandler.on('error', handleError);

    // Cleanup on unmount
    return () => {
      wsHandler.disconnect();
    };
  }, []);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingMessage]);

  // Event handlers
  const handleConnected = (data) => {
    console.log('Connected to assistant');
    setIsConnected(true);
    addSystemMessage('Connected to assistant');
  };

  const handleDisconnected = (data) => {
    console.log('Disconnected from assistant');
    setIsConnected(false);
    addSystemMessage('Disconnected. Reconnecting...');
  };

  const handleAck = (data) => {
    console.log('ACK received:', data);
    setActiveRequestId(data.request_id);
  };

  const handleThinking = (data) => {
    console.log('Thinking:', data.message);
    setIsThinking(true);
    setThinkingMessage(data.message);
    setStreamingMessage('');
  };

  const handleStreamChunk = (data) => {
    setStreamingMessage(prev => prev + data.content);
  };

  const handleStreamEnd = (data) => {
    console.log('Stream ended');

    if (streamingMessage) {
      addMessage({
        role: 'assistant',
        content: streamingMessage,
        timestamp: new Date().toISOString()
      });

      setStreamingMessage('');
    }

    setIsThinking(false);
  };

  const handleActionStarted = (data) => {
    console.log('Action started:', data.description);
    setCurrentAction({
      action_type: data.action_type,
      description: data.description,
      progress: 0,
      status: 'running'
    });
  };

  const handleActionProgress = (data) => {
    setCurrentAction(prev => ({
      ...prev,
      progress: data.progress,
      description: data.description
    }));
  };

  const handleActionCompleted = (data) => {
    console.log('Action completed:', data.description);

    setCompletedActions(prev => [
      ...prev,
      {
        description: data.description,
        status: 'completed',
        result: data.result
      }
    ]);

    setCurrentAction(null);
  };

  const handleActionFailed = (data) => {
    console.log('Action failed:', data.description);

    setCompletedActions(prev => [
      ...prev,
      {
        description: data.description,
        status: 'failed',
        error: data.error
      }
    ]);

    setCurrentAction(null);
  };

  const handleDesktopResult = (data) => {
    console.log('Desktop result:', data);

    if (data.success) {
      addSystemMessage(`✓ ${data.command} completed`);
    } else {
      addSystemMessage(`✗ ${data.command} failed: ${data.error}`);
    }
  };

  const handleComplete = (data) => {
    console.log('Request complete:', data);

    setIsThinking(false);
    setCurrentAction(null);
    setActiveRequestId(null);

    const timeSeconds = (data.total_time_ms / 1000).toFixed(2);
    const pathType = data.is_fast_path ? 'fast path' : 'full runtime';
    addSystemMessage(`Completed in ${timeSeconds}s (${pathType})`);
  };

  const handleError = (data) => {
    console.error('Error:', data.message);

    setIsThinking(false);
    setCurrentAction(null);
    setActiveRequestId(null);

    addMessage({
      role: 'assistant',
      content: `Error: ${data.message}`,
      isError: true,
      timestamp: new Date().toISOString()
    });
  };

  // Helper functions
  const addMessage = (message) => {
    setMessages(prev => [...prev, message]);
    sessionManager.addMessage(message);
  };

  const addSystemMessage = (content) => {
    addMessage({
      role: 'system',
      content,
      timestamp: new Date().toISOString()
    });
  };

  // User actions
  const handleSendMessage = () => {
    if (!inputValue.trim() || !isConnected) {
      return;
    }

    const message = inputValue.trim();

    // Add user message to UI
    addMessage({
      role: 'user',
      content: message,
      timestamp: new Date().toISOString()
    });

    // Send via WebSocket
    wsHandler.sendMessage(message);

    // Clear input
    setInputValue('');
    inputRef.current?.focus();
  };

  const handleCancelRequest = () => {
    if (activeRequestId) {
      console.log('Cancelling request:', activeRequestId);
      wsHandler.cancelRequest(activeRequestId);

      setIsThinking(false);
      setCurrentAction(null);
      setActiveRequestId(null);
      setStreamingMessage('');

      addSystemMessage('Request cancelled');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="enhanced-chat">
      {/* Header */}
      <div className="chat-header">
        <h2>AI Assistant</h2>
        <div className="connection-status">
          <div className={`status-indicator ${isConnected ? 'connected' : 'disconnected'}`} />
          <span>{isConnected ? 'Connected' : 'Connecting...'}</span>
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.map((msg, index) => (
          <div key={index} className={`message message-${msg.role} ${msg.isError ? 'error' : ''}`}>
            <div className="message-role">{msg.role}</div>
            <div className="message-content">{msg.content}</div>
            <div className="message-timestamp">
              {new Date(msg.timestamp).toLocaleTimeString()}
            </div>
          </div>
        ))}

        {/* Streaming message */}
        {streamingMessage && (
          <div className="message message-assistant streaming">
            <div className="message-role">assistant</div>
            <div className="message-content">{streamingMessage}</div>
            <div className="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        )}

        {/* Thinking indicator */}
        {isThinking && !streamingMessage && (
          <div className="thinking-indicator">
            <div className="thinking-icon">
              <div className="spinner"></div>
            </div>
            <div className="thinking-text">{thinkingMessage || 'Thinking...'}</div>
          </div>
        )}

        {/* Action display */}
        <ActionDisplay
          actions={completedActions}
          currentAction={currentAction}
        />

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="chat-input-area">
        {activeRequestId && (
          <div className="cancel-button-container">
            <button
              className="cancel-button"
              onClick={handleCancelRequest}
            >
              Cancel Request
            </button>
          </div>
        )}

        <div className="chat-input">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={isConnected ? "Ask me anything..." : "Connecting..."}
            disabled={!isConnected}
            rows={3}
          />
          <button
            onClick={handleSendMessage}
            disabled={!isConnected || !inputValue.trim()}
            className="send-button"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
};

export default EnhancedChat;
