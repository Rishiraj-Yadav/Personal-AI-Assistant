"""
interactive_cli.py — Interactive terminal for testing the Browser Agent

Features:
  - Persistent browser session across commands (browser stays open)
  - Optional conversation memory (agent remembers previous steps)
  - Built-in slash commands: /help, /reset, /screenshot, /url, /clear, /history
  - Colored output for easy reading
  - Route directly to BrowserAgent OR through the Orchestrator

Run:
    python interactive_cli.py                  # uses Orchestrator (auto-routing)
    python interactive_cli.py --direct         # talks directly to BrowserAgent
    python interactive_cli.py --direct --memory  # BrowserAgent with memory across turns
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime

# ── Optional color support (works on Windows too with colorama) ──────────────
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    def green(s):  return Fore.GREEN + str(s) + Style.RESET_ALL
    def blue(s):   return Fore.CYAN + str(s) + Style.RESET_ALL
    def yellow(s): return Fore.YELLOW + str(s) + Style.RESET_ALL
    def red(s):    return Fore.RED + str(s) + Style.RESET_ALL
    def bold(s):   return Style.BRIGHT + str(s) + Style.RESET_ALL
    def gray(s):   return Fore.WHITE + str(s) + Style.RESET_ALL
except ImportError:
    def green(s):  return str(s)
    def blue(s):   return str(s)
    def yellow(s): return str(s)
    def red(s):    return str(s)
    def bold(s):   return str(s)
    def gray(s):   return str(s)

from dotenv import load_dotenv
load_dotenv()


# ─── Slash commands ──────────────────────────────────────────────────────────

HELP_TEXT = """
{title}

{commands}

{tips}
""".format(
    title=bold("=== Browser Agent — Interactive Test CLI ==="),
    commands="\n".join([
        bold("Slash Commands:"),
        f"  {yellow('/help')}          Show this help message",
        f"  {yellow('/screenshot')}    Take a screenshot of the current page (saved as test_shot.png)",
        f"  {yellow('/url')}           Print the current browser URL",
        f"  {yellow('/pageinfo')}      Show inputs/buttons on the current page",
        f"  {yellow('/reset')}         Reset agent memory (keeps browser open)",
        f"  {yellow('/restart')}       Close browser + reset everything",
        f"  {yellow('/history')}       Show your command history this session",
        f"  {yellow('/clear')}         Clear the terminal screen",
        f"  {yellow('/exit')}          Quit",
    ]),
    tips="\n".join([
        bold("Tips:"),
        "  - The browser stays OPEN between commands — great for multi-step testing",
        "  - Use --memory flag to let the agent remember previous steps",
        "  - Use --direct to skip the orchestrator and talk straight to BrowserAgent",
        "  - Type natural language: 'search for cats on google', 'click the first result'",
    ])
)


# ─── Main Interactive CLI ────────────────────────────────────────────────────

class InteractiveCLI:
    def __init__(self, direct: bool = False, memory: bool = False, verbose: bool = False):
        self.direct = direct        # bypass orchestrator
        self.memory = memory        # keep agent history across turns
        self.verbose = verbose      # show internal tool calls
        self.command_history: list[str] = []
        self.agent = None
        self.orchestrator = None

    async def setup(self):
        """Initialize agents."""
        if self.direct:
            from agents.browser_agent import BrowserAgent
            self.agent = BrowserAgent(verbose=self.verbose)
            print(blue("  Mode: Direct → BrowserAgent"))
        else:
            from agents.orchestrator import OrchestratorAgent
            self.orchestrator = OrchestratorAgent(verbose=self.verbose)
            self.agent = self.orchestrator.agents.get("browser")
            print(blue("  Mode: Orchestrator → BrowserAgent"))

        memory_status = green("ON") if self.memory else yellow("OFF")
        print(blue(f"  Memory across turns: {memory_status}"))

    async def handle_slash_command(self, cmd: str) -> bool:
        """
        Handle /commands. Returns True if handled, False if not a slash command.
        """
        cmd = cmd.strip().lower()

        if cmd == "/help":
            print(HELP_TEXT)

        elif cmd == "/screenshot":
            import tools.browser_tools as bt
            page = await bt._get_page()
            fname = f"test_shot_{datetime.now().strftime('%H%M%S')}.png"
            await bt.screenshot(fname)
            print(green(f"  ✅ Screenshot saved: {fname}"))

        elif cmd == "/url":
            import tools.browser_tools as bt
            page = await bt._get_page()
            print(blue(f"  Current URL: {page.url}"))

        elif cmd == "/pageinfo":
            import tools.browser_tools as bt
            info = await bt.get_page_info()
            print(blue(info))

        elif cmd == "/reset":
            if self.agent:
                self.agent.reset()
            print(yellow("  🔄 Agent memory reset. Browser stays open."))

        elif cmd == "/restart":
            import tools.browser_tools as bt
            await bt.close_browser()
            if self.agent:
                self.agent.reset()
            print(yellow("  🔄 Browser closed + memory reset. Will relaunch on next task."))

        elif cmd == "/history":
            if not self.command_history:
                print(gray("  No commands yet."))
            else:
                print(bold("  Command history:"))
                for i, h in enumerate(self.command_history, 1):
                    print(f"  {gray(str(i) + '.')} {h}")

        elif cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")

        elif cmd in ("/exit", "/quit", "/q"):
            return "exit"

        else:
            print(red(f"  Unknown command: {cmd}. Type /help for options."))

        return True

    async def run_task(self, task: str) -> str:
        """Run the task through the appropriate agent."""
        if self.direct:
            # Direct to BrowserAgent — optionally keep memory
            result = await self.agent.run(task, reset_history=not self.memory)
        else:
            # Through orchestrator
            result = await self.orchestrator.run(task)
        return result

    async def start(self):
        """Main REPL loop."""
        os.system("cls" if os.name == "nt" else "clear")

        print(bold("\n" + "="*58))
        print(bold("   🤖  Browser Agent — Interactive Test Terminal"))
        print(bold("="*58))
        await self.setup()
        print(gray("  Type a task or /help for commands. Ctrl+C to quit.\n"))

        while True:
            # Prompt
            try:
                user_input = input(green("You: ")).strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n{yellow('Goodbye!')}")
                break

            if not user_input:
                continue

            # Slash commands
            if user_input.startswith("/"):
                result = await self.handle_slash_command(user_input)
                if result == "exit":
                    print(yellow("Goodbye!"))
                    break
                continue

            # Record history
            self.command_history.append(user_input)

            # Run the task
            print(gray(f"\n  ⏳ Running..."))
            start = asyncio.get_event_loop().time()

            try:
                result = await self.run_task(user_input)
                elapsed = asyncio.get_event_loop().time() - start
                print(f"\n{bold('Agent:')} {result}")
                print(gray(f"\n  ⏱  {elapsed:.1f}s | Type /help for commands\n"))
            except Exception as e:
                print(red(f"\n  ❌ Error: {e}\n"))

        # Cleanup
        import tools.browser_tools as bt
        await bt.close_browser()


# ─── Entry Point ─────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Interactive terminal for testing the Browser Agent"
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Talk directly to BrowserAgent, skip the Orchestrator"
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Keep agent conversation memory across turns (only works with --direct)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show all tool calls and results in real time"
    )
    args = parser.parse_args()

    if not os.environ.get("GOOGLE_API_KEY"):
        print(red("❌ GOOGLE_API_KEY not set. Add it to your .env file."))
        sys.exit(1)

    cli = InteractiveCLI(
        direct=args.direct,
        memory=args.memory,
        verbose=args.verbose,
    )
    await cli.start()


if __name__ == "__main__":
    asyncio.run(main())
