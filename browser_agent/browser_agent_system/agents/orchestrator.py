"""
OrchestratorAgent
───────────────────────────────────────────────
The "brain" of the multi-agent system.
Receives a high-level task, decides which agent(s)
should handle it, and returns the final result.

Currently supports:
  - BrowserAgent  → for any web/browser tasks

Easily extensible — add more agents to AGENT_REGISTRY
and update the routing prompt.
"""

from __future__ import annotations
import asyncio
import json
import os
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# ─── Agent Registry ──────────────────────────────────────────────────────────
# Import agents here. Add new agents to AGENT_REGISTRY below.
from agents.browser_agent import BrowserAgent


AGENT_REGISTRY = {
    "browser": {
        "description": "Handles all web browser tasks: navigating websites, searching the internet, scraping data, filling forms, clicking buttons, extracting content from web pages.",
        "examples": [
            "Search Google for X",
            "Go to amazon.com and find the price of Y",
            "Fill out a contact form on Z website",
            "Scrape product listings from a website",
            "Log in to a website and check account info",
        ]
    },
    # ── Add more agents here as you build them ──
    # "file": {
    #     "description": "Handles reading, writing, and organizing files on disk.",
    #     "examples": ["Read report.csv", "Save these results to output.txt"]
    # },
    # "code": {
    #     "description": "Writes and executes Python code to perform data analysis or automation.",
    #     "examples": ["Analyze this dataset", "Write a script to sort these files"]
    # },
}


ORCHESTRATOR_SYSTEM = """You are an Orchestrator Agent that manages a team of specialized AI agents.

Your job is to:
1. Understand the user's task
2. Decide which agent(s) should handle it
3. Break down the task if it requires multiple agents
4. Return a routing plan as JSON

## Available Agents
{agent_descriptions}

## Response Format
Respond with ONLY a JSON object:
{{
  "plan": [
    {{
      "step": 1,
      "agent": "<agent_name>",
      "task": "<specific task description for this agent>",
      "context": {{}}  // optional extra info
    }}
  ],
  "reasoning": "Brief explanation of your routing decision"
}}

## Rules
- Use the most specific agent for each task
- For multi-step tasks, break them into sequential steps
- Keep task descriptions clear and self-contained
- If a task clearly needs browser access (web, URLs, online data), use "browser"
"""


class OrchestratorAgent:
    """
    Routing orchestrator that analyzes tasks and delegates
    them to the appropriate specialized agents.
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",  # Fast model for routing
        verbose: bool = True,
    ):
        self.model = model
        self.verbose = verbose
        self._classifier = genai.GenerativeModel(model_name=model)

        # Instantiate all available agents
        self.agents = {
            "browser": BrowserAgent(verbose=verbose),
        }

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _build_agent_descriptions(self) -> str:
        lines = []
        for name, info in AGENT_REGISTRY.items():
            examples = "\n    ".join(f"• {e}" for e in info["examples"])
            lines.append(f"**{name}**: {info['description']}\n  Examples:\n    {examples}")
        return "\n\n".join(lines)

    def _classify(self, task: str) -> list[dict]:
        """Use Gemini to classify and route the task. Returns the plan."""
        system = ORCHESTRATOR_SYSTEM.format(
            agent_descriptions=self._build_agent_descriptions()
        )

        prompt = f"{system}\n\nUser Task: {task}"
        response = self._classifier.generate_content(prompt)
        raw = response.text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        return parsed

    async def run(self, task: str) -> str:
        """
        Main entry point. Takes a task, routes it, and returns the final result.
        """
        self._log(f"\n{'='*60}")
        self._log(f"[Orchestrator] Task: {task}")
        self._log(f"{'='*60}")

        # Step 1: Classify and build the plan
        try:
            plan_data = self._classify(task)
            plan = plan_data["plan"]
            reasoning = plan_data.get("reasoning", "")
            self._log(f"\n[Orchestrator] Routing decision: {reasoning}")
        except Exception as e:
            self._log(f"[Orchestrator] Classification failed: {e}. Defaulting to browser agent.")
            plan = [{"step": 1, "agent": "browser", "task": task, "context": {}}]

        # Step 2: Execute each step
        results = []

        for step in plan:
            step_num = step["step"]
            agent_name = step["agent"]
            sub_task = step["task"]
            context = step.get("context", {})

            # Pass results from previous steps as context
            if results:
                context["previous_results"] = results[-1]

            self._log(f"\n[Orchestrator] → Step {step_num}: [{agent_name}] {sub_task}")

            agent = self.agents.get(agent_name)
            if not agent:
                result = f"Error: Agent '{agent_name}' not found in registry."
                self._log(f"[Orchestrator] ⚠️  {result}")
            else:
                result = await agent.run(sub_task, context=context)

            results.append(result)

        # Step 3: Aggregate and return final result
        if len(results) == 1:
            return results[0]
        else:
            combined = "\n\n".join(f"[Step {i+1}]\n{r}" for i, r in enumerate(results))
            return combined

    async def close(self):
        """Shut down all agents cleanly."""
        for agent in self.agents.values():
            if hasattr(agent, "close"):
                await agent.close()
