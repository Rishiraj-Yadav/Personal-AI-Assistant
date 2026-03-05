"""
Task Planner — LLM-powered DAG builder for multi-agent pipeline orchestration.

Replaces the single-category Router Agent. Decomposes compound tasks into
Directed Acyclic Graphs (DAGs) with dependency tracking and parallel groups.
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from loguru import logger
import google.generativeai as genai


# ════════════════════════════════════════════════════════
# Data Structures
# ════════════════════════════════════════════════════════

@dataclass
class DAGNode:
    """A single step in the execution pipeline."""
    id: str
    agent: str                                  # desktop | browser | coding | general
    action: str                                 # open_app | navigate | generate | chat
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # IDs of prerequisite steps
    context_keys: List[str] = field(default_factory=list) # Keys to pull from memory
    timeout_s: int = 30
    retries: int = 2
    fallback: Optional[str] = None              # Alternative agent if this fails
    risk_level: str = "low"                     # low | medium | high

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExecutionDAG:
    """Directed Acyclic Graph of pipeline steps."""
    nodes: List[DAGNode]
    complexity: str = "simple"                  # simple | compound | complex
    estimated_cost: float = 0.0
    reasoning: str = ""

    def get_execution_batches(self) -> List[List[DAGNode]]:
        """
        Topological sort into execution batches.
        Nodes in the same batch have all dependencies satisfied → can run in parallel.
        """
        completed = set()
        remaining = list(self.nodes)
        batches = []

        max_iterations = len(remaining) + 1  # Deadlock guard
        iteration = 0

        while remaining and iteration < max_iterations:
            iteration += 1
            # Find nodes whose dependencies are all completed
            batch = [
                n for n in remaining
                if all(dep in completed for dep in n.depends_on)
            ]

            if not batch:
                # Circular dependency detected
                logger.error(f"Circular dependency in DAG: {[n.id for n in remaining]}")
                # Force-add remaining as single batch
                batches.append(remaining)
                break

            batches.append(batch)
            for n in batch:
                completed.add(n.id)
                remaining.remove(n)

        return batches

    def to_dict(self) -> Dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "complexity": self.complexity,
            "estimated_cost": self.estimated_cost,
            "reasoning": self.reasoning,
        }


# ════════════════════════════════════════════════════════
# Task Planner
# ════════════════════════════════════════════════════════

class TaskPlanner:
    """
    Decomposes user requests into execution DAGs using Gemini.
    Handles simple (1 step), compound (2-3 sequential), and
    complex (parallel + sequential) tasks.
    """

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("⚠️ GOOGLE_API_KEY not set — planner will fail")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        logger.info("✅ Task Planner initialized")

    async def decompose(self, user_message: str) -> ExecutionDAG:
        """
        Decompose user message into an execution DAG.

        Returns an ExecutionDAG with ordered nodes.
        """
        prompt = self._build_prompt(user_message)

        try:
            response = await asyncio.to_thread(
                self.model.generate_content, prompt
            )
            text = response.text.strip()
            dag = self._parse_response(text, user_message)
            logger.info(
                f"📋 Planned: {len(dag.nodes)} steps, "
                f"complexity={dag.complexity}, "
                f"reasoning={dag.reasoning}"
            )
            return dag

        except Exception as e:
            logger.error(f"Task Planner failed: {e}")
            # Fallback: single general step
            return ExecutionDAG(
                nodes=[DAGNode(id="0", agent="general", action="chat")],
                complexity="simple",
                reasoning=f"Planner error, falling back to general: {e}",
            )

    async def replan(
        self, original_dag: ExecutionDAG, failed_steps: List[Dict], attempt: int
    ) -> Optional[ExecutionDAG]:
        """
        Re-plan after step failures. Returns None if unrecoverable.

        Strategy:
        - attempt 1: Retry same step
        - attempt 2: Use fallback agent
        - attempt 3+: Skip failed step or abort
        """
        if attempt >= 3:
            logger.warning("🛑 Max re-plan attempts reached, aborting pipeline")
            return None

        new_nodes = []
        for node in original_dag.nodes:
            failed = next(
                (f for f in failed_steps if f.get("step_id") == node.id), None
            )

            if failed and attempt == 2 and node.fallback:
                # Swap to fallback agent
                logger.info(f"🔄 Re-planning: {node.id} → fallback {node.fallback}")
                new_node = DAGNode(
                    id=node.id,
                    agent=node.fallback,
                    action=node.action,
                    params=node.params,
                    depends_on=node.depends_on,
                    context_keys=node.context_keys,
                    timeout_s=node.timeout_s,
                    retries=1,
                    fallback=None,
                    risk_level=node.risk_level,
                )
                new_nodes.append(new_node)
            elif failed and attempt >= 2:
                # Skip this step, remove dependents
                logger.info(f"⏭️ Skipping failed step: {node.id}")
                continue
            else:
                new_nodes.append(node)

        if not new_nodes:
            return None

        # Update dependencies for removed nodes
        remaining_ids = {n.id for n in new_nodes}
        for node in new_nodes:
            node.depends_on = [d for d in node.depends_on if d in remaining_ids]

        return ExecutionDAG(
            nodes=new_nodes,
            complexity=original_dag.complexity,
            reasoning=f"Re-planned (attempt {attempt})",
        )

    def _build_prompt(self, user_message: str) -> str:
        return f"""You are a task decomposition expert. Break down the user's request into sequential and/or parallel steps.

User Request: "{user_message}"

Available Agents:
1. DESKTOP — Control the computer: open apps, click, type, screenshots, manage files
   Actions: open_app, screenshot, mouse_click, keyboard_type, window_manage, file_manager
   
2. BROWSER — Navigate websites: go to URLs, click buttons, fill forms, search
   Actions: navigate, click, type, search, extract
   
3. CODING — Write, execute, and debug code in a sandbox
   Actions: generate, execute, debug

4. QA — Verify generated code by writing and running automated tests
   Actions: verify
   IMPORTANT: Always add a QA step AFTER any CODING step. The QA step must depend on the coding step and use context_keys ["files", "project_type"].

5. EMAIL — Send, read, search, and reply to emails
   Actions: send, read, search, reply

6. DEVOPS — Manage infrastructure, health checks, and environment cleanup
   Actions: health_check, cleanup, provision, diagnose

7. GENERAL — Answer questions, have conversations, explain things
   Actions: chat

Rules:
- If the task needs an app opened FIRST (like "open Brave and search YouTube"):
  Step 1 = DESKTOP open_app, Step 2 = BROWSER navigate (depends on step 1)
- If sub-tasks are INDEPENDENT (like "check weather AND search YouTube"):
  They can run in PARALLEL (same depends_on)
- Browser tasks that need a specific browser should have a desktop step first
- Simple questions = single GENERAL step
- CODING tasks MUST be followed by a QA verify step that depends on the coding step
- File operations (read, write, move, copy, search, delete) use DESKTOP with file_manager action
- Email tasks (send, read, search, reply) use EMAIL agent
- Sending emails, deleting files, or running destructive commands is 'high' risk
- Assign a `risk_level` to each step (low, medium, high). Executing code that modifies files or system state is 'high' risk. Safe browsing or chatting is 'low' risk.

Return ONLY valid JSON in this exact format:
{{
  "nodes": [
    {{
      "id": "0",
      "agent": "desktop",
      "action": "open_app",
      "params": {{"app": "brave", "flags": ["--remote-debugging-port=9222"]}},
      "depends_on": [],
      "context_keys": [],
      "timeout_s": 10,
      "retries": 2,
      "fallback": "browser",
      "risk_level": "medium"
    }},
    {{
      "id": "1",
      "agent": "browser",
      "action": "navigate",
      "params": {{"url": "youtube.com"}},
      "depends_on": ["0"],
      "context_keys": ["cdp_port", "cdp_url"],
      "timeout_s": 30,
      "retries": 1,
      "fallback": null,
      "risk_level": "low"
    }}
  ],
  "complexity": "compound",
  "reasoning": "Need to open browser app first, then navigate inside it"
}}

Respond with ONLY the JSON, no explanation."""

    def _parse_response(self, text: str, user_message: str) -> ExecutionDAG:
        """Parse LLM response into ExecutionDAG."""
        # Strip markdown fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse DAG JSON: {text[:200]}")
            return ExecutionDAG(
                nodes=[DAGNode(id="0", agent="general", action="chat")],
                complexity="simple",
                reasoning="JSON parse error, fallback to general",
            )

        nodes = []
        for node_data in data.get("nodes", []):
            nodes.append(
                DAGNode(
                    id=str(node_data.get("id", len(nodes))),
                    agent=node_data.get("agent", "general"),
                    action=node_data.get("action", "chat"),
                    params=node_data.get("params", {}),
                    depends_on=[str(d) for d in node_data.get("depends_on", [])],
                    context_keys=node_data.get("context_keys", []),
                    timeout_s=node_data.get("timeout_s", 30),
                    retries=node_data.get("retries", 2),
                    fallback=node_data.get("fallback"),
                    risk_level=node_data.get("risk_level", "low"),
                )
            )

        if not nodes:
            nodes = [DAGNode(id="0", agent="general", action="chat")]

        return ExecutionDAG(
            nodes=nodes,
            complexity=data.get("complexity", "simple"),
            estimated_cost=data.get("estimated_cost", 0.0),
            reasoning=data.get("reasoning", ""),
        )


# Legacy compatibility: keep classify_task interface
class RouterAgentCompat:
    """Backward-compatible wrapper around TaskPlanner."""

    def __init__(self):
        self.planner = TaskPlanner()

    def classify_task(self, user_message: str) -> Dict[str, Any]:
        """Legacy interface — returns single classification."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, use to_thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    dag = pool.submit(
                        asyncio.run, self.planner.decompose(user_message)
                    ).result()
            else:
                dag = asyncio.run(self.planner.decompose(user_message))
        except Exception:
            dag = ExecutionDAG(
                nodes=[DAGNode(id="0", agent="general", action="chat")],
                complexity="simple",
                reasoning="Fallback",
            )

        # Return first node's agent as task_type for backward compat
        primary_agent = dag.nodes[0].agent if dag.nodes else "general"
        return {
            "task_type": primary_agent,
            "confidence": 0.9,
            "reasoning": dag.reasoning,
            "next_agent": primary_agent,
            "dag": dag,
        }


# Global instances
task_planner = TaskPlanner()
router_agent = RouterAgentCompat()
