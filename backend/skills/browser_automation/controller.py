#!/usr/bin/env python3
"""
Browser Automation Skill Controller
Forwards goals to the Browser Agent HTTP server and streams back logs.
"""
import os
import json
import sys
import requests
from typing import Optional


# Browser Agent connection settings
BROWSER_AGENT_URL = os.environ.get(
    "BROWSER_AGENT_URL", "http://localhost:4000"
)


def _read_api_key() -> Optional[str]:
    """Read shared API key from the config file (same pattern as desktop-agent)."""
    # Try env var first
    key = os.environ.get("BROWSER_AGENT_API_KEY")
    if key:
        return key

    # Try reading the key file mounted/shared from browser-agent
    key_paths = [
        "/app/browser_agent_key.txt",  # Docker mounted path
        os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "browser-agent", "config", "api_key.txt"),
    ]
    for p in key_paths:
        try:
            with open(p, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            continue
    return None


def execute_goal(goal: str) -> dict:
    """
    Send a goal to the Browser Agent and return the result with logs.

    Args:
        goal: Natural-language browser automation goal.

    Returns:
        dict with success, status, logs, and optional error.
    """
    api_key = _read_api_key()
    if not api_key:
        return {
            "error": "Cannot connect to Browser Agent: API key not found. "
                     "Make sure browser-agent is running (npm run serve)."
        }

    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }

    # Health check first
    try:
        health = requests.get(
            f"{BROWSER_AGENT_URL}/health", timeout=5
        )
        if health.status_code != 200:
            return {
                "error": f"Browser Agent health check failed (HTTP {health.status_code}). "
                         "Is browser-agent running?"
            }
    except requests.ConnectionError:
        return {
            "error": "Cannot connect to Browser Agent at "
                     f"{BROWSER_AGENT_URL}. Make sure browser-agent is running."
        }

    # Execute the goal
    try:
        response = requests.post(
            f"{BROWSER_AGENT_URL}/execute",
            headers=headers,
            json={"goal": goal},
            timeout=300,  # 5 minute timeout for long browser tasks
        )

        if response.status_code == 401:
            return {"error": "Browser Agent rejected our API key."}

        result = response.json()
        return result

    except requests.Timeout:
        return {
            "error": "Browser Agent timed out after 5 minutes."
        }
    except Exception as e:
        return {
            "error": f"Browser Agent request failed: {str(e)}"
        }


def main():
    """Entry point when executed as a skill script."""
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)

        goal = params.get("goal")
        if not goal:
            print(json.dumps({"error": "Missing required parameter: goal"}))
            sys.exit(1)

        result = execute_goal(goal)
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
