"""Manual smoke runner for the desktop-agent browser runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.browser_agent import browser_agent  # noqa: E402
from browser_runtime.service import BrowserCommand, browser_service  # noqa: E402


def dump(label: str, payload) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(payload, indent=2, default=str))


def run_status(session_id: str, profile: str) -> int:
    result = browser_service.execute(BrowserCommand(command="status", session_id=session_id, profile=profile))
    dump("status", result)
    return 0 if result.get("success") else 1


def run_live_cycle(session_id: str, profile: str, url: str, stop_after: bool) -> int:
    start = browser_service.execute(BrowserCommand(command="start", session_id=session_id, profile=profile))
    dump("start", start)
    if not start.get("success"):
        return 1

    navigate = browser_service.execute(
        BrowserCommand(command="navigate", session_id=session_id, profile=profile, url=url)
    )
    dump("navigate", navigate)

    snapshot = browser_service.execute(
        BrowserCommand(command="snapshot", session_id=session_id, profile=profile, mode="ai")
    )
    dump("snapshot", snapshot)

    exit_code = 0 if navigate.get("success") and snapshot.get("success") else 1

    if stop_after:
        stop = browser_service.execute(BrowserCommand(command="stop", session_id=session_id, profile=profile))
        dump("stop", stop)
        if not stop.get("success"):
            exit_code = 1

    return exit_code


def run_alias_open(session_id: str, profile: str, url: str) -> int:
    result = browser_agent.execute("open_browser", {"session_id": session_id, "profile": profile, "url": url})
    dump("alias-open_browser", result)
    return 0 if result.get("success") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test the desktop-agent browser runtime.")
    parser.add_argument("--session-id", default="smoke-script", help="Runtime session id to use")
    parser.add_argument("--profile", default="openclaw", help="Browser profile to target")
    parser.add_argument("--url", default="https://example.com", help="URL for live smoke runs")
    parser.add_argument(
        "mode",
        choices=["status", "live-cycle", "alias-open", "stop"],
        default="status",
        nargs="?",
        help="Smoke mode to run",
    )
    parser.add_argument("--keep-open", action="store_true", help="Do not stop the browser after live-cycle")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.mode == "status":
        return run_status(args.session_id, args.profile)
    if args.mode == "live-cycle":
        return run_live_cycle(args.session_id, args.profile, args.url, stop_after=not args.keep_open)
    if args.mode == "alias-open":
        return run_alias_open(args.session_id, args.profile, args.url)
    if args.mode == "stop":
        result = browser_service.execute(BrowserCommand(command="stop", session_id=args.session_id, profile=args.profile))
        dump("stop", result)
        return 0 if result.get("success") else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
