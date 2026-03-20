/**
 * WebSocket Handler - Phase 4 Frontend
 *
 * Manages WebSocket connection to backend gateway:
 * - Bidirectional real-time communication
 * - Automatic reconnection
 * - Event-based message handling
 * - Streaming support
 */

import { sessionManager } from './sessionManager';

export class WebSocketHandler {
  constructor(url, options = {}) {
    this.url = url;
    this.options = {
      autoReconnect: true,
      reconnectInterval: 3000,
      maxReconnectAttempts: 5,
      ...options
    };

    this.ws = null;
    this.connected = false;
    this.reconnectAttempts = 0;
    this.reconnectTimeout = null;

    // Event handlers
    this.eventHandlers = {};

    // Message queue (for offline messages)
    this.messageQueue = [];
  }

  /**
   * Connect to WebSocket server
   */
  connect() {
    const session = sessionManager.getSessionInfo();

    // Build WebSocket URL with session params
    const wsUrl = new URL(this.url);
    wsUrl.searchParams.set('session_id', session.sessionId);
    wsUrl.searchParams.set('user_id', session.userId);

    console.log('Connecting to WebSocket:', wsUrl.toString());

    try {
      this.ws = new WebSocket(wsUrl.toString());

      this.ws.onopen = this.handleOpen.bind(this);
      this.ws.onmessage = this.handleMessage.bind(this);
      this.ws.onclose = this.handleClose.bind(this);
      this.ws.onerror = this.handleError.bind(this);

    } catch (error) {
      console.error('WebSocket connection error:', error);
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.connected = false;
    sessionManager.setConnected(false);
  }

  /**
   * Handle WebSocket open event
   */
  handleOpen(event) {
    console.log('WebSocket connected');

    this.connected = true;
    this.reconnectAttempts = 0;
    sessionManager.setConnected(true);

    // Emit connected event
    this.emit('connected', { timestamp: new Date() });

    // Send queued messages
    this.flushMessageQueue();
  }

  /**
   * Handle incoming WebSocket message
   */
  handleMessage(event) {
    try {
      const data = JSON.parse(event.data);

      console.log('Received message:', data.type);

      // Add to session history
      sessionManager.addMessage(data);

      // Emit event based on message type
      const messageType = data.type;
      this.emit(messageType, data);

      // Also emit generic 'message' event
      this.emit('message', data);

    } catch (error) {
      console.error('Error handling message:', error);
    }
  }

  /**
   * Handle WebSocket close event
   */
  handleClose(event) {
    console.log('WebSocket disconnected:', event.code, event.reason);

    this.connected = false;
    this.ws = null;
    sessionManager.setConnected(false);

    // Emit disconnected event
    this.emit('disconnected', { code: event.code, reason: event.reason });

    // Attempt reconnection
    if (this.options.autoReconnect) {
      this.scheduleReconnect();
    }
  }

  /**
   * Handle WebSocket error event
   */
  handleError(error) {
    console.error('WebSocket error:', error);
    this.emit('error', error);
  }

  /**
   * Schedule reconnection attempt
   */
  scheduleReconnect() {
    if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      this.emit('reconnect_failed');
      return;
    }

    this.reconnectAttempts++;

    console.log(`Reconnecting in ${this.options.reconnectInterval}ms (attempt ${this.reconnectAttempts})...`);

    this.reconnectTimeout = setTimeout(() => {
      this.emit('reconnecting', { attempt: this.reconnectAttempts });
      this.connect();
    }, this.options.reconnectInterval);
  }

  /**
   * Send message to server
   */
  send(data) {
    if (!this.connected || !this.ws) {
      console.warn('WebSocket not connected, queueing message');
      this.messageQueue.push(data);
      return false;
    }

    try {
      // Add session info if not present
      const session = sessionManager.getSessionInfo();
      const messageData = {
        session_id: session.sessionId,
        user_id: session.userId,
        conversation_id: session.conversationId,
        ...data,
        timestamp: new Date().toISOString()
      };

      this.ws.send(JSON.stringify(messageData));
      return true;

    } catch (error) {
      console.error('Error sending message:', error);
      this.messageQueue.push(data);
      return false;
    }
  }

  /**
   * Send user message
   */
  sendMessage(message, context = {}) {
    return this.send({
      type: 'user_message',
      message: message,
      context: context
    });
  }

  /**
   * Cancel active request
   */
  cancelRequest(requestId) {
    return this.send({
      type: 'cancel_request',
      request_id: requestId
    });
  }

  /**
   * Flush queued messages
   */
  flushMessageQueue() {
    if (this.messageQueue.length === 0) {
      return;
    }

    console.log(`Flushing ${this.messageQueue.length} queued messages`);

    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift();
      this.send(message);
    }
  }

  /**
   * Register event handler
   */
  on(event, handler) {
    if (!this.eventHandlers[event]) {
      this.eventHandlers[event] = [];
    }
    this.eventHandlers[event].push(handler);
  }

  /**
   * Unregister event handler
   */
  off(event, handler) {
    if (!this.eventHandlers[event]) {
      return;
    }

    this.eventHandlers[event] = this.eventHandlers[event].filter(
      h => h !== handler
    );
  }

  /**
   * Emit event to all registered handlers
   */
  emit(event, data) {
    const handlers = this.eventHandlers[event] || [];

    handlers.forEach(handler => {
      try {
        handler(data);
      } catch (error) {
        console.error(`Error in ${event} handler:`, error);
      }
    });
  }

  /**
   * Check if connected
   */
  isConnected() {
    return this.connected;
  }
}

// Create global WebSocket handler instance
const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000/ws/chat';
export const wsHandler = new WebSocketHandler(WS_URL);
