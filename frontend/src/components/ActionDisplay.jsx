/**
 * Action Display Component - Phase 4 Frontend
 *
 * Shows real-time system actions:
 * - "Looking at your screen..."
 * - "Opening VS Code..."
 * - "Reading file..."
 * - Progress indicators
 */

import React from 'react';
import './ActionDisplay.css';

const ActionDisplay = ({ actions, currentAction }) => {
  if (!currentAction && (!actions || actions.length === 0)) {
    return null;
  }

  return (
    <div className="action-display">
      {/* Current active action */}
      {currentAction && (
        <div className="action-item active">
          <div className="action-icon">
            <div className="spinner"></div>
          </div>
          <div className="action-content">
            <div className="action-description">{currentAction.description}</div>
            {currentAction.progress > 0 && (
              <div className="action-progress">
                <div
                  className="action-progress-bar"
                  style={{ width: `${currentAction.progress * 100}%` }}
                ></div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Recent completed actions */}
      {actions && actions.slice(-3).map((action, index) => (
        <div
          key={index}
          className={`action-item ${action.status}`}
        >
          <div className="action-icon">
            {action.status === 'completed' && '✓'}
            {action.status === 'failed' && '✗'}
          </div>
          <div className="action-content">
            <div className="action-description">{action.description}</div>
            {action.result && (
              <div className="action-result">
                {JSON.stringify(action.result).substring(0, 50)}...
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

export default ActionDisplay;
