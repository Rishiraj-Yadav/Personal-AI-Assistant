"""
🚀 Personal AI Assistant — One-Click Launcher
Run this single file to start the ENTIRE project:
  1. Docker services (Backend, Frontend, Gateway, Qdrant)
  2. Desktop Agent (runs natively on your host)

Usage:
    python run.py          # Start everything
    python run.py --agent  # Start only the desktop agent
    python run.py --docker # Start only the Docker services
"""
import os
import sys
import subprocess
import signal
import time
import argparse
import importlib
from pathlib import Path

# ───── Project paths ─────
PROJECT_ROOT = Path(__file__).parent
DESKTOP_AGENT_DIR = PROJECT_ROOT / "desktop-agent"
ENV_FILE = PROJECT_ROOT / ".env"
DESKTOP_ENV_FILE = DESKTOP_AGENT_DIR / ".env.desktop"


def print_banner():
    print("\n" + "=" * 60)
    print("🤖  PERSONAL AI ASSISTANT — OpenClaw Architecture")
    print("=" * 60)
    print(f"  Project Root : {PROJECT_ROOT}")
    print(f"  Agent Dir    : {DESKTOP_AGENT_DIR}")
    print(f"  Python       : {sys.executable}")
    print("=" * 60)


def check_env():
    """Ensure the .env.desktop file exists with a GOOGLE_API_KEY."""
    if not DESKTOP_ENV_FILE.exists():
        google_key = os.environ.get("GOOGLE_API_KEY", "")
        if not google_key and ENV_FILE.exists():
            with open(ENV_FILE, "r") as f:
                for line in f:
                    if line.strip().startswith("GOOGLE_API_KEY"):
                        google_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

        if google_key:
            with open(DESKTOP_ENV_FILE, "w") as f:
                f.write(f"GOOGLE_API_KEY={google_key}\n")
            print(f"  ✅ Created {DESKTOP_ENV_FILE.name} with API key from root .env")
        else:
            print("  ⚠️  No GOOGLE_API_KEY found. The brain will not be active.")
            print(f"     Set it in {DESKTOP_ENV_FILE} or the root .env file.\n")
    else:
        print(f"  ✅ Found {DESKTOP_ENV_FILE.name}")


def check_dependencies():
    """Check that required Python packages are installed."""
    required = ["fastapi", "uvicorn", "loguru", "pydantic_settings", "google.generativeai"]
    missing = []
    for pkg in required:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"\n  ⚠️  Missing packages: {', '.join(missing)}")
        print(f"  Installing from requirements.txt ...")
        req_file = DESKTOP_AGENT_DIR / "requirements.txt"
        if req_file.exists():
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            )
            print("  ✅ Dependencies installed.")
        else:
            print(f"  ❌ requirements.txt not found at {req_file}")
            sys.exit(1)
    else:
        print("  ✅ All dependencies satisfied")


def check_docker():
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            print(f"  ✅ Docker Compose found")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    print("  ⚠️  Docker not found. Backend services will not start.")
    print("     Install Docker Desktop: https://www.docker.com/products/docker-desktop")
    return False


def start_docker_services():
    """Start Docker containers (Backend, Frontend, Gateway, Qdrant)."""
    print("\n" + "-" * 60)
    print("🐳 Cleaning up old containers...")
    print("-" * 60)

    # Pre-cleanup: remove stale containers to avoid zombie conflicts
    subprocess.run(
        ["docker", "compose", "down", "--remove-orphans"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    # Force-prune any dead containers
    subprocess.run(
        ["docker", "container", "prune", "-f"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )

    print("🐳 Starting Docker services (Backend, Frontend, Gateway, Qdrant)...")

    docker_proc = subprocess.Popen(
        ["docker", "compose", "up", "--build"],
        cwd=str(PROJECT_ROOT),
    )
    return docker_proc


def start_desktop_agent():
    """Start the desktop agent natively on the host."""
    print("\n" + "-" * 60)
    print("🖥️  Starting Desktop Agent on http://127.0.0.1:7777 ...")
    print("-" * 60 + "\n")

    agent_proc = subprocess.Popen(
        [sys.executable, str(DESKTOP_AGENT_DIR / "app" / "main.py")],
        cwd=str(DESKTOP_AGENT_DIR),
    )
    return agent_proc


def main():
    parser = argparse.ArgumentParser(description="Personal AI Assistant Launcher")
    parser.add_argument("--agent", action="store_true", help="Start only the Desktop Agent")
    parser.add_argument("--docker", action="store_true", help="Start only the Docker services")
    args = parser.parse_args()

    # Default: start everything
    start_all = not args.agent and not args.docker

    print_banner()
    docker_proc = None
    agent_proc = None

    try:
        # ── Docker services ──
        if start_all or args.docker:
            if check_docker():
                docker_proc = start_docker_services()
                time.sleep(3)  # Give Docker a head start

        # ── Desktop Agent ──
        if start_all or args.agent:
            check_env()
            check_dependencies()
            agent_proc = start_desktop_agent()

        if not docker_proc and not agent_proc:
            print("\n❌ Nothing to start. Use --agent or --docker, or run without flags for everything.")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ ALL SERVICES RUNNING — Press Ctrl+C to stop everything")
        print("=" * 60)
        print("  🖥️  Desktop Agent  → http://127.0.0.1:7777")
        print("  🌐 Frontend        → http://localhost:3000")
        print("  ⚙️  Backend API     → http://localhost:8000")
        print("  🔗 Gateway         → http://localhost:18789")
        print("  🧠 Qdrant          → http://localhost:6333")
        print("=" * 60 + "\n")

        # Wait — but keep desktop agent alive even if Docker has issues
        while True:
            if docker_proc and docker_proc.poll() is not None:
                print(f"\n⚠️  Docker exited with code {docker_proc.returncode}.")
                print("    Desktop Agent is still running. Press Ctrl+C to stop it.")
                docker_proc = None  # Don't check again

            if agent_proc and agent_proc.poll() is not None:
                print(f"\n⚠️  Desktop Agent exited with code {agent_proc.returncode}")
                break

            if not docker_proc and not agent_proc:
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down all services...")

        if agent_proc and agent_proc.poll() is None:
            print("  Stopping Desktop Agent...")
            agent_proc.terminate()
            try:
                agent_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                agent_proc.kill()

        if docker_proc and docker_proc.poll() is None:
            print("  Stopping Docker...")
            docker_proc.terminate()

        # Always try docker compose down for clean shutdown
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
        )

        print("  ✅ All services stopped. Goodbye! 👋\n")


if __name__ == "__main__":
    main()
