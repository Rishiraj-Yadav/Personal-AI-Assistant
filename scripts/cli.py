"""
🚀 Personal AI Assistant — CLI Mode
Starts all services (Docker + Desktop Agent) and drops you into an interactive chat.
Messages go through the BACKEND (port 8000) — same pipeline as the web frontend,
so memory, context, and routing are all shared.
"""
import os
import sys
import time
import json
import uuid
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# Reuse run.py utilities for starting services
CURRENT_DIR = Path(__file__).parent
sys.path.insert(0, str(CURRENT_DIR))
import run

ROOT_DIR = CURRENT_DIR.parent
BACKEND_URL = "http://localhost:8000"
DESKTOP_AGENT_URL = "http://localhost:7777"

# Persistent conversation ID so memory carries across messages
CONVERSATION_ID = f"cli_{uuid.uuid4().hex[:12]}"
USER_ID = "default_user"


def wait_for_backend():
    """Wait for the Docker backend to become responsive."""
    print("⏳ Waiting for Backend (port 8000) to initialize...")
    for i in range(120):
        if i > 0 and i % 30 == 0:
            print(f"⏳ Still waiting... ({i} seconds elapsed)")
        try:
            req = urllib.request.Request(f"{BACKEND_URL}/health")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return True
        except:
            pass
        time.sleep(1)
    return False


def wait_for_agent():
    """Wait for the Desktop Agent to become responsive."""
    print("⏳ Waiting for Desktop Agent (port 7777) to initialize...")
    for i in range(120):
        if i > 0 and i % 30 == 0:
            print(f"⏳ Still waiting... ({i} seconds elapsed)")
        try:
            req = urllib.request.Request(f"{DESKTOP_AGENT_URL}/health")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return True
        except:
            pass
        time.sleep(1)
    return False


def send_message(message: str):
    """Send a message through the Backend chat API (same as frontend)"""
    url = f"{BACKEND_URL}/api/v1/chat"
    headers = {"Content-Type": "application/json"}
    data = json.dumps({
        "message": message,
        "conversation_id": CONVERSATION_ID,
        "user_id": USER_ID,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
            return True, result

    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        try:
            error_msg = json.loads(error_msg).get("detail", error_msg)
        except:
            pass
        return False, f"HTTP Error {e.code}: {error_msg}"

    except urllib.error.URLError as e:
        return False, f"Connection Error: {e.reason}"

    except Exception as e:
        return False, f"Unexpected Error: {e}"


def main():
    print("\n" + "=" * 60)
    print("🤖  PERSONAL AI ASSISTANT — CLI MODE")
    print("Messages go through the Backend (same memory as web UI)")
    print("=" * 60)

    docker_proc = None
    agent_proc = None

    try:
        # 1. Start Docker Services (Backend, Frontend, Gateway, Qdrant)
        if run.check_docker():
            print("🐳 Starting Docker services (Backend, Frontend, Qdrant)...")
            docker_proc = subprocess.Popen(
                ["docker", "compose", "up", "--build"],
                cwd=str(ROOT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        # 2. Start Desktop Agent natively
        run.check_env()
        run.check_dependencies()

        print("🖥️  Starting local Desktop Agent...")
        agent_proc = subprocess.Popen(
            [sys.executable, str(ROOT_DIR / "desktop-agent" / "app" / "main.py")],
            cwd=str(ROOT_DIR / "desktop-agent")
        )

        # 3. Wait for both services
        if not wait_for_agent():
            print("⚠️  Desktop Agent did not start, but CLI can still chat via backend.")

        if not wait_for_backend():
            print("❌ Backend failed to start. Cannot proceed.")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ ALL SERVICES RUNNING")
        print(f"📝 Conversation ID: {CONVERSATION_ID}")
        print("Type 'exit' or 'quit' to shut down everything.")
        print("=" * 60)

        # 4. Interactive Chat Loop
        while True:
            try:
                command = input("\n> You: ").strip()
                if not command:
                    continue

                if command.lower() in ["exit", "quit", "q"]:
                    print("Goodbye! Shutting down...")
                    break

                print("\n🤖 Thinking...")
                success, result = send_message(command)

                if success:
                    response_text = result.get("response", "No response")
                    skills = result.get("skills_used", [])
                    model = result.get("model_used", "unknown")

                    print(f"\n=> SonarBot: {response_text}")

                    if skills:
                        print(f"\n[Skills Used]: {', '.join(s.get('name', str(s)) for s in skills)}")
                    print(f"[Model: {model}]")
                else:
                    print(f"\n=> Error: {result}")

            except KeyboardInterrupt:
                print("\nGoodbye! Shutting down...")
                break

    finally:
        # Cleanup
        print("\n🛑 Cleaning up services...")
        if agent_proc and agent_proc.poll() is None:
            agent_proc.terminate()
            try:
                agent_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent_proc.kill()

        if docker_proc and docker_proc.poll() is None:
            docker_proc.terminate()

        subprocess.run(
            ["docker", "compose", "down"],
            cwd=str(ROOT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ Cleanup complete.")


if __name__ == "__main__":
    main()
