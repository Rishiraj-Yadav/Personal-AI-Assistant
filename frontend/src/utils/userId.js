/**
 * User ID Management
 * Stores user ID in localStorage for memory persistence
 */

const USER_ID_KEY = 'openclaw_user_id';
const USER_NAME_KEY = 'openclaw_user_name';

/**
 * Get or create user ID
 * @returns {string} User ID
 */
export function getUserId() {
  let userId = localStorage.getItem(USER_ID_KEY);
  
  if (!userId) {
    // Generate unique ID: user_timestamp_random
    const timestamp = Date.now();
    const random = Math.random().toString(36).substr(2, 9);
    userId = `user_${timestamp}_${random}`;
    
    localStorage.setItem(USER_ID_KEY, userId);
    console.log('✅ Created new user ID:', userId);
  }
  
  return userId;
}

/**
 * Set user name (optional)
 * @param {string} name - User's display name
 */
export function setUserName(name) {
  localStorage.setItem(USER_NAME_KEY, name);
}

/**
 * Get user name
 * @returns {string|null} User name or null
 */
export function getUserName() {
  return localStorage.getItem(USER_NAME_KEY);
}

/**
 * Reset user (clear ID and name)
 * Use this to start fresh
 */
export function resetUser() {
  localStorage.removeItem(USER_ID_KEY);
  localStorage.removeItem(USER_NAME_KEY);
  console.log('🔄 User reset - will create new ID on next load');
}

/**
 * Check if user has a name set
 * @returns {boolean}
 */
export function hasUserName() {
  return !!localStorage.getItem(USER_NAME_KEY);
}