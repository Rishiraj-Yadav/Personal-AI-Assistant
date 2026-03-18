import React, { useState, useEffect } from 'react';

export default function GatewayConsole({ open, onClose }) {
  if (!open) return null;

  return (
    <div style={{
      position: 'fixed', top: '10%', left: '10%', right: '10%', bottom: '10%',
      backgroundColor: '#1e1e1e', color: '#00ff00', zIndex: 9999,
      padding: '20px', borderRadius: '8px', boxShadow: '0 4px 20px rgba(0,0,0,0.8)',
      fontFamily: 'monospace', display: 'flex', flexDirection: 'column'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #333', paddingBottom: '10px', marginBottom: '10px' }}>
        <h2 style={{ margin: 0, fontSize: '1.2rem', color: '#fff' }}>[ Gateway Console ]</h2>
        <button 
          onClick={onClose} 
          style={{ background: '#ff4444', color: 'white', border: 'none', padding: '5px 15px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}
        >
          Close (Esc)
        </button>
      </div>
      
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px', backgroundColor: '#000', borderRadius: '4px' }}>
        <p>{'>'} Gateway connection endpoint: ws://localhost:18789/ws</p>
        <p>{'>'} Awaiting commands...</p>
      </div>
    </div>
  );
}
