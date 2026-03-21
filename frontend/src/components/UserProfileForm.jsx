import { useState } from 'react'
import { getUserName, setUserName } from '../utils/userId'

const MAX_NAME_LENGTH = 64

function UserProfileForm({ onClose, onSave }) {
  const [name, setName] = useState(getUserName() || '')
  const [error, setError] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Name cannot be empty.')
      return
    }
    if (trimmed.length > MAX_NAME_LENGTH) {
      setError(`Name must be ${MAX_NAME_LENGTH} characters or fewer.`)
      return
    }
    setUserName(trimmed)
    onSave(trimmed)
    onClose()
  }

  return (
    <div className="profile-form-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="profile-form-modal" role="dialog" aria-modal="true" aria-labelledby="profile-form-title">
        <div className="profile-form-header">
          <h2 id="profile-form-title">Edit Profile</h2>
          <button className="btn-icon-sm profile-form-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="profile-form-body">
          <label htmlFor="profile-name-input" className="profile-form-label">Display Name</label>
          <input
            id="profile-name-input"
            type="text"
            value={name}
            onChange={(e) => { setName(e.target.value); setError('') }}
            placeholder="Enter your name"
            className={`profile-form-input${error ? ' input-error' : ''}`}
            maxLength={MAX_NAME_LENGTH}
            autoFocus
          />
          {error && <p className="profile-form-error">{error}</p>}
          <div className="profile-form-actions">
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary">Save</button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default UserProfileForm
