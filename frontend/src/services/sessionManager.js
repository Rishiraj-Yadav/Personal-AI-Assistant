/**
 * Session Manager - Phase 4 Frontend
 *
 * Manages persistent session state on frontend:
 * - Session ID (localStorage)
 * - User ID
 * - Connection status
 * - Message history
 */

const SESSION_STORAGE_KEY = 'assistant_session';
const USER_STORAGE_KEY = 'assistant_user';

export class SessionManager {
  constructor() {
    this.sessionId = null;
    this.userId = null;
    this.conversationId = null;
    this.connected = false;
    this.messageHistory = [];

    // Load from localStorage
    this.loadSession();
  }

  /**
   * Load session from localStorage
   */
  loadSession() {
    try {
      const savedSession = localStorage.getItem(SESSION_STORAGE_KEY);
      const savedUser = localStorage.getItem(USER_STORAGE_KEY);

      if (savedSession) {
        const session = JSON.parse(savedSession);
        this.sessionId = session.sessionId;
        this.conversationId = session.conversationId;
      }

      if (savedUser) {
        this.userId = savedUser;
      }

      // Generate IDs if not found
      if (!this.sessionId) {
        this.sessionId = this.generateId('web');
      }

      if (!this.userId) {
        this.userId = this.generateId('user');
      }

      // Save to ensure persistence
      this.saveSession();

    } catch (error) {
      console.error('Error loading session:', error);
      this.resetSession();
    }
  }

  /**
   * Save session to localStorage
   */
  saveSession() {
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
        sessionId: this.sessionId,
        conversationId: this.conversationId,
        timestamp: new Date().toISOString()
      }));

      localStorage.setItem(USER_STORAGE_KEY, this.userId);

    } catch (error) {
      console.error('Error saving session:', error);
    }
  }

  /**
   * Reset session (clear and generate new)
   */
  resetSession() {
    this.sessionId = this.generateId('web');
    this.userId = this.generateId('user');
    this.conversationId = null;
    this.messageHistory = [];
    this.saveSession();
  }

  /**
   * Generate unique ID
   */
  generateId(prefix) {
    const randomPart = Math.random().toString(36).substring(2, 10);
    const timestamp = Date.now().toString(36);
    return `${prefix}_${timestamp}_${randomPart}`;
  }

  /**
   * Get session info
   */
  getSessionInfo() {
    return {
      sessionId: this.sessionId,
      userId: this.userId,
      conversationId: this.conversationId,
      connected: this.connected
    };
  }

  /**
   * Set conversation ID
   */
  setConversationId(conversationId) {
    this.conversationId = conversationId;
    this.saveSession();
  }

  /**
   * Set connection status
   */
  setConnected(connected) {
    this.connected = connected;
  }

  /**
   * Add message to history
   */
  addMessage(message) {
    this.messageHistory.push({
      ...message,
      timestamp: new Date().toISOString()
    });

    // Keep last 100 messages
    if (this.messageHistory.length > 100) {
      this.messageHistory = this.messageHistory.slice(-100);
    }
  }

  /**
   * Get message history
   */
  getMessageHistory() {
    return this.messageHistory;
  }

  /**
   * Clear message history
   */
  clearHistory() {
    this.messageHistory = [];
  }
}

// Global instance
export const sessionManager = new SessionManager();
