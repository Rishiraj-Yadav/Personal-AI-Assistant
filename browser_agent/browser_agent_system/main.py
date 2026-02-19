"""
main.py — Entry point for the multi-agent system.

Run modes:
  1. Interactive REPL:       python main.py
  2. Single task (CLI arg):  python main.py --task "Search for Python tutorials"
  3. Browser agent direct:   python main.py --agent browser --task "Go to google.com"
"""

import asyncio
import argparse
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def check_env():
    if not os.environ.get("GOOGLE_API_KEY"):
        print("❌ Error: GOOGLE_API_KEY not set in .env")
        sys.exit(1)


async def run_interactive():
    """Start an interactive REPL."""
    from agents.orchestrator import OrchestratorAgent

    print("\n" + "="*60)
    print("  🤖 Multi-Agent System  |  Browser Agent v1.0")
    print("="*60)
    print("  Type a task and press Enter. Type 'exit' to quit.\n")

    orchestrator = OrchestratorAgent(verbose=True)

    try:
        while True:
            try:
                task = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not task:
                continue

            if task.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break

            result = await orchestrator.run(task)
            print(f"\nResult:\n{result}\n")
    finally:
        await orchestrator.close()


async def run_single_task(task: str, agent: str = None):
    """Run one task, optionally bypassing the orchestrator."""
    if agent == "browser":
        from agents.browser_agent import BrowserAgent
        a = BrowserAgent(verbose=True)
        try:
            result = await a.run(task)
            print(f"\nResult:\n{result}")
        finally:
            await a.close()
    else:
        from agents.orchestrator import OrchestratorAgent
        o = OrchestratorAgent(verbose=True)
        try:
            result = await o.run(task)
            print(f"\nResult:\n{result}")
        finally:
            await o.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Agent System with Browser Agent")
    parser.add_argument("--task", type=str, help="Task to run (skips interactive mode)")
    parser.add_argument("--agent", type=str, choices=["browser"], help="Route directly to a specific agent")
    args = parser.parse_args()

    check_env()

    if args.task:
        asyncio.run(run_single_task(args.task, agent=args.agent))
    else:
        asyncio.run(run_interactive())
