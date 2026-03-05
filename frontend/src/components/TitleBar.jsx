import './TitleBar.css'

function TitleBar() {
    const isElectron = window.electronAPI != null

    if (!isElectron) return null

    const handleMinimize = () => window.electronAPI.minimize()
    const handleMaximize = () => window.electronAPI.maximize()
    const handleClose = () => window.electronAPI.close()

    return (
        <div className="titlebar" id="titlebar">
            <div className="titlebar-drag">
                <div className="titlebar-logo">
                    <div className="titlebar-icon">◉</div>
                    <span className="titlebar-title">SoNAR</span>
                </div>
            </div>
            <div className="titlebar-controls">
                <button
                    className="titlebar-btn titlebar-btn-minimize"
                    onClick={handleMinimize}
                    aria-label="Minimize"
                    id="btn-minimize"
                >
                    <svg width="10" height="1" viewBox="0 0 10 1">
                        <rect width="10" height="1" fill="currentColor" />
                    </svg>
                </button>
                <button
                    className="titlebar-btn titlebar-btn-maximize"
                    onClick={handleMaximize}
                    aria-label="Maximize"
                    id="btn-maximize"
                >
                    <svg width="10" height="10" viewBox="0 0 10 10">
                        <rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="1" />
                    </svg>
                </button>
                <button
                    className="titlebar-btn titlebar-btn-close"
                    onClick={handleClose}
                    aria-label="Close"
                    id="btn-close"
                >
                    <svg width="10" height="10" viewBox="0 0 10 10">
                        <line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" strokeWidth="1.2" />
                        <line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" strokeWidth="1.2" />
                    </svg>
                </button>
            </div>
        </div>
    )
}

export default TitleBar
