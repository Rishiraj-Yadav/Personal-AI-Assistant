#!/usr/bin/env python3
"""
Phase 6 Quick Start Script
==========================

Starts both the backend and desktop-agent for testing.
Run from the repository root:
    python scripts/start_phase6.py
"""

import subprocess
import sys
import os
import time
from pathlib import Path

# Get repository root
REPO_ROOT = Path(__file__).parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
DESKTOP_AGENT_DIR = REPO_ROOT / "desktop-agent" / "app"


def check_python():
    """Check Python version."""
    if sys.version_info < (3, 10):
        print("❌ Python 3.10+ required")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")


def start_backend():
    """Start the backend server."""
    print("\n🚀 Starting Backend...")
    os.chdir(BACKEND_DIR)
    
    # Start uvicorn in background
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    
    print(f"   Backend PID: {proc.pid}")
    print("   URL: http://localhost:8000")
    return proc


def start_desktop_agent():
    """Start the desktop agent."""
    print("\n🖥️ Starting Desktop Agent...")
    os.chdir(DESKTOP_AGENT_DIR)
    
    # Start the desktop agent
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    
    print(f"   Desktop Agent PID: {proc.pid}")
    print("   URL: http://localhost:7777")
    print("   WebSocket: ws://localhost:8000/ws/desktop")
    return proc


def main():
    print("=" * 60)
    print("🔧 Phase 6: Production-Grade OpenClaw Architecture")
    print("=" * 60)
    
    check_python()
    
    print("\n📋 Starting Services...")
    print("-" * 40)
    
    # Start both services
    backend_proc = start_backend()
    time.sleep(3)  # Give backend time to start
    
    desktop_proc = start_desktop_agent()
    
    print("\n" + "=" * 60)
    print("✅ Both services started!")
    print("=" * 60)
    print("""
Test the integration:
1. Open http://localhost:3000 (frontend)
2. Try: "open my downloads folder"
3. Try: "launch notepad"
4. Try: "take a screenshot"

Press Ctrl+C to stop all services.
""")
    
    try:
        # Wait for processes
        while True:
            time.sleep(1)
            
            # Check if processes are still running
            if backend_proc.poll() is not None:
                print("❌ Backend stopped unexpectedly!")
                break
            if desktop_proc.poll() is not None:
                print("❌ Desktop agent stopped unexpectedly!")
                break
                
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping services...")
        backend_proc.terminate()
        desktop_proc.terminate()
        print("✅ Services stopped.")


if __name__ == "__main__":
    main()
