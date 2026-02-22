"""
Pipeline Engine — Executes DAGs with hybrid sequential/parallel execution.

Features:
- Topological batch execution (parallel within batch, sequential across batches)
- Per-node retries with exponential backoff
- Timeout enforcement via asyncio.wait_for
- Fallback agent swapping on failure
- Deadlock detection
- Full observability via AgentMonitor
"""

import os
import json
import time
import asyncio
import requests
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger

from .task_planner import DAGNode, ExecutionDAG
from .context_memory import ContextMemory
from .monitor import agent_monitor


# ════════════════════════════════════════════════════════
# Result types
# ════════════════════════════════════════════════════════

@dataclass
class StepResult:
    step_id: str
    agent: str
    action: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    context_out: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    attempt: int = 1
    used_fallback: bool = False


@dataclass
class PipelineResult:
    pipeline_id: str
    steps: List[StepResult] = field(default_factory=list)
    all_succeeded: bool = False
    summary: str = ""
    total_duration_ms: int = 0


# ════════════════════════════════════════════════════════
# Agent URLs
# ════════════════════════════════════════════════════════

DESKTOP_AGENT_URL = os.getenv("DESKTOP_AGENT_URL", "http://host.docker.internal:7777")
BROWSER_AGENT_URL = os.getenv("BROWSER_AGENT_URL", "http://host.docker.internal:4000")
DESKTOP_API_KEY = os.getenv("DESKTOP_AGENT_API_KEY", "")


# ════════════════════════════════════════════════════════
# Pipeline Engine
# ════════════════════════════════════════════════════════

class PipelineEngine:
    """Executes multi-step agent pipelines with context passing."""

    def __init__(self):
        self.monitor = agent_monitor

    async def execute(
        self,
        pipeline_id: str,
        dag: ExecutionDAG,
        memory: ContextMemory,
        user_message: str,
        callback: Optional[Callable] = None,
    ) -> PipelineResult:
        """
        Execute a full DAG pipeline.

        Args:
            pipeline_id: Unique ID for this pipeline run
            dag: The execution DAG from TaskPlanner
            memory: Shared context memory
            user_message: Original user message
            callback: Async callback for frontend progress updates
        """
        start_time = time.time()
        all_results: List[StepResult] = []

        # Log pipeline start
        self.monitor.log_pipeline_start(
            pipeline_id, user_message, json.dumps(dag.to_dict()), len(dag.nodes)
        )

        # Get execution batches (topological sort)
        batches = dag.get_execution_batches()
        total_steps = len(dag.nodes)

        logger.info(
            f"⚡ Pipeline {pipeline_id}: {total_steps} steps in {len(batches)} batches"
        )

        abort = False
        step_counter = 0

        for batch_idx, batch in enumerate(batches):
            if abort:
                break

            if len(batch) == 1:
                # ── Sequential execution ──
                node = batch[0]
                step_counter += 1

                if callback:
                    await callback({
                        "type": "pipeline_step",
                        "step": step_counter,
                        "total": total_steps,
                        "agent": node.agent,
                        "action": node.action,
                        "status": "running",
                        "message": f"Step {step_counter}/{total_steps}: {node.agent} → {node.action}",
                    })

                result = await self._execute_node(pipeline_id, node, memory)
                all_results.append(result)

                if callback:
                    await callback({
                        "type": "pipeline_step",
                        "step": step_counter,
                        "total": total_steps,
                        "agent": node.agent,
                        "action": node.action,
                        "status": "success" if result.success else "failed",
                        "message": f"Step {step_counter}: {'✅' if result.success else '❌'} {node.agent}.{node.action}",
                        "output": str(result.output)[:200] if result.output else None,
                    })

                if not result.success:
                    # Check if downstream steps depend on this
                    has_dependents = any(
                        node.id in n.depends_on for n in dag.nodes
                    )
                    if has_dependents:
                        logger.warning(
                            f"⛔ Step {node.id} failed with dependents — aborting"
                        )
                        abort = True

            else:
                # ── Parallel execution ──
                logger.info(f"🔀 Parallel batch: {[n.id for n in batch]}")
                tasks = []
                for node in batch:
                    step_counter += 1
                    if callback:
                        await callback({
                            "type": "pipeline_step",
                            "step": step_counter,
                            "total": total_steps,
                            "agent": node.agent,
                            "action": node.action,
                            "status": "running",
                            "message": f"Step {step_counter} (parallel): {node.agent} → {node.action}",
                        })
                    tasks.append(self._execute_node(pipeline_id, node, memory))

                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                for node, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        result = StepResult(
                            step_id=node.id,
                            agent=node.agent,
                            action=node.action,
                            success=False,
                            error=str(result),
                        )
                    all_results.append(result)

        # Calculate totals
        total_duration = int((time.time() - start_time) * 1000)
        all_ok = all(r.success for r in all_results)

        # Log pipeline end
        self.monitor.log_pipeline_end(pipeline_id, all_ok)

        # Build summary
        summary_parts = []
        for r in all_results:
            icon = "✅" if r.success else "❌"
            summary_parts.append(f"{icon} {r.agent}.{r.action}")
            if r.output and isinstance(r.output, dict):
                # Include key outputs
                for k, v in r.output.items():
                    if k in ("message", "result", "page_title", "url"):
                        summary_parts.append(f"   → {v}")

        return PipelineResult(
            pipeline_id=pipeline_id,
            steps=all_results,
            all_succeeded=all_ok,
            summary="\n".join(summary_parts),
            total_duration_ms=total_duration,
        )

    # ════════════════════════════════════════════════════════
    # Node Execution (with retry + timeout + fallback)
    # ════════════════════════════════════════════════════════

    async def _execute_node(
        self, pipeline_id: str, node: DAGNode, memory: ContextMemory
    ) -> StepResult:
        """Execute a single DAG node with retries and fallback."""

        for attempt in range(1, node.retries + 2):  # retries + 1 initial attempt
            start = time.time()

            # Check for infinite loop
            if self.monitor.check_infinite_loop(pipeline_id, node.id):
                return StepResult(
                    step_id=node.id, agent=node.agent, action=node.action,
                    success=False, error="Infinite loop detected", attempt=attempt,
                )

            try:
                # Inject scoped context
                context = memory.get_scoped(node.context_keys)

                # Log step start
                self.monitor.log_step(
                    pipeline_id, node.id, node.agent, node.action,
                    event_type="start", attempt=attempt, context_in=context,
                )

                # Execute with timeout
                result = await asyncio.wait_for(
                    self._dispatch(node, context),
                    timeout=node.timeout_s,
                )

                duration = int((time.time() - start) * 1000)

                if result.success:
                    # Store outputs in memory
                    memory.store_step_output(node.id, result.context_out)

                    self.monitor.log_step(
                        pipeline_id, node.id, node.agent, node.action,
                        event_type="complete", attempt=attempt, status="success",
                        duration_ms=duration, context_out=result.context_out,
                    )
                    result.duration_ms = duration
                    result.attempt = attempt
                    return result

                else:
                    # Step failed but didn't throw
                    self.monitor.log_step(
                        pipeline_id, node.id, node.agent, node.action,
                        event_type="retry" if attempt <= node.retries else "complete",
                        attempt=attempt, status="error",
                        duration_ms=duration, error=result.error,
                    )

            except asyncio.TimeoutError:
                duration = int((time.time() - start) * 1000)
                self.monitor.log_step(
                    pipeline_id, node.id, node.agent, node.action,
                    event_type="timeout", attempt=attempt, status="timeout",
                    duration_ms=duration,
                )
                logger.warning(
                    f"⏳ Step {node.id} timed out ({node.timeout_s}s), "
                    f"attempt {attempt}/{node.retries + 1}"
                )

            except Exception as e:
                duration = int((time.time() - start) * 1000)
                self.monitor.log_step(
                    pipeline_id, node.id, node.agent, node.action,
                    event_type="error", attempt=attempt, status="error",
                    duration_ms=duration, error=str(e),
                )
                logger.error(f"❌ Step {node.id} error: {e}")

            # Backoff before retry
            if attempt <= node.retries:
                backoff = min(2 ** attempt, 8)
                logger.info(f"⏳ Retrying {node.id} in {backoff}s...")
                await asyncio.sleep(backoff)

        # All retries exhausted — try fallback
        if node.fallback:
            logger.info(f"🔄 Falling back: {node.agent} → {node.fallback}")
            self.monitor.log_step(
                pipeline_id, node.id, node.agent, node.action,
                event_type="fallback", status="fallback",
            )
            fallback_node = DAGNode(
                id=node.id,
                agent=node.fallback,
                action=node.action,
                params=node.params,
                context_keys=node.context_keys,
                timeout_s=node.timeout_s,
                retries=0,
                fallback=None,
            )
            fallback_result = await self._dispatch(fallback_node, memory.get_scoped(node.context_keys))
            fallback_result.used_fallback = True
            return fallback_result

        return StepResult(
            step_id=node.id, agent=node.agent, action=node.action,
            success=False, error="All retries exhausted",
        )

    # ════════════════════════════════════════════════════════
    # Dispatchers (route to actual agents)
    # ════════════════════════════════════════════════════════

    async def _dispatch(self, node: DAGNode, context: Dict) -> StepResult:
        """Route execution to the correct agent."""
        if node.agent == "desktop":
            return await self._dispatch_desktop(node, context)
        elif node.agent == "browser":
            return await self._dispatch_browser(node, context)
        elif node.agent == "coding":
            return await self._dispatch_coding(node, context)
        else:
            return await self._dispatch_general(node, context)

    async def _dispatch_desktop(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute via Desktop Agent HTTP API."""
        try:
            # Map action to Desktop Agent skill format
            skill_map = {
                "open_app": "app_launcher",
                "screenshot": "screenshot",
                "mouse_click": "mouse_control",
                "keyboard_type": "keyboard_control",
                "window_manage": "window_manager",
            }
            skill_name = skill_map.get(node.action, node.action)

            # Build request
            payload = {
                "skill": skill_name,
                "args": {**node.params, **context},
            }
            headers = {"X-API-Key": DESKTOP_API_KEY}

            response = await asyncio.to_thread(
                requests.post,
                f"{DESKTOP_AGENT_URL}/execute",
                json=payload,
                headers=headers,
                timeout=node.timeout_s,
            )

            if response.status_code == 200:
                data = response.json()
                context_out = {}

                # Extract CDP info if browser was opened
                result_data = data.get("result", {})
                if isinstance(result_data, dict):
                    if result_data.get("cdp_port"):
                        context_out["cdp_port"] = result_data["cdp_port"]
                        context_out["cdp_url"] = f"http://localhost:{result_data['cdp_port']}"

                return StepResult(
                    step_id=node.id, agent="desktop", action=node.action,
                    success=data.get("success", False),
                    output=result_data,
                    context_out=context_out,
                )
            else:
                return StepResult(
                    step_id=node.id, agent="desktop", action=node.action,
                    success=False, error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except requests.exceptions.ConnectionError:
            return StepResult(
                step_id=node.id, agent="desktop", action=node.action,
                success=False, error="Desktop Agent not reachable at :7777",
            )
        except Exception as e:
            return StepResult(
                step_id=node.id, agent="desktop", action=node.action,
                success=False, error=str(e),
            )

    async def _dispatch_browser(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute via Browser Agent HTTP API."""
        try:
            # Build goal from action + params
            params = {**node.params, **context}
            goal = params.get("goal") or params.get("url") or node.action

            payload = {"goal": goal}

            # Pass CDP URL if available from context (Desktop → Browser handoff)
            if context.get("cdp_url"):
                payload["cdp_url"] = context["cdp_url"]

            # Read API key from browser-agent config
            browser_api_key = ""
            key_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "..",
                "browser-agent", "config", "api_key.txt"
            )
            try:
                with open(key_path, "r") as f:
                    browser_api_key = f.read().strip()
            except Exception:
                pass

            headers = {"X-API-Key": browser_api_key} if browser_api_key else {}

            response = await asyncio.to_thread(
                requests.post,
                f"{BROWSER_AGENT_URL}/browse",
                json=payload,
                headers=headers,
                timeout=node.timeout_s,
            )

            if response.status_code == 200:
                data = response.json()
                return StepResult(
                    step_id=node.id, agent="browser", action=node.action,
                    success=data.get("success", True),
                    output=data,
                    context_out={
                        "page_url": data.get("url", ""),
                        "page_title": data.get("title", ""),
                    },
                )
            else:
                return StepResult(
                    step_id=node.id, agent="browser", action=node.action,
                    success=False, error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except requests.exceptions.ConnectionError:
            return StepResult(
                step_id=node.id, agent="browser", action=node.action,
                success=False, error="Browser Agent not reachable at :4000",
            )
        except Exception as e:
            return StepResult(
                step_id=node.id, agent="browser", action=node.action,
                success=False, error=str(e),
            )

    async def _dispatch_coding(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute via Code Specialist (inline, same process)."""
        try:
            from .code_specialist_agent import code_specialist
            from ..services.sandbox_services import sandbox_service

            description = node.params.get("task", node.params.get("description", ""))
            result = await code_specialist.generate_code(
                description=description, context=None, iteration=1,
            )

            if result.get("success") and result.get("files"):
                exec_result = await sandbox_service.execute_project(
                    files=result["files"],
                    project_type=result.get("project_type", "python"),
                    project_name="pipeline-code",
                )
                return StepResult(
                    step_id=node.id, agent="coding", action=node.action,
                    success=exec_result.get("success", False),
                    output=exec_result,
                    context_out={"code_output": exec_result.get("stdout", "")},
                )
            else:
                return StepResult(
                    step_id=node.id, agent="coding", action=node.action,
                    success=False, error=result.get("error", "Code generation failed"),
                )
        except Exception as e:
            return StepResult(
                step_id=node.id, agent="coding", action=node.action,
                success=False, error=str(e),
            )

    async def _dispatch_general(self, node: DAGNode, context: Dict) -> StepResult:
        """General chat — pass through to LLM."""
        return StepResult(
            step_id=node.id, agent="general", action="chat",
            success=True,
            output={"message": "Handled by general LLM"},
            context_out={},
        )

    # ════════════════════════════════════════════════════════
    # Health checks
    # ════════════════════════════════════════════════════════

    def check_agent_health(self, agent: str) -> bool:
        """Ping an agent's /health endpoint."""
        urls = {
            "desktop": DESKTOP_AGENT_URL,
            "browser": BROWSER_AGENT_URL,
        }
        url = urls.get(agent)
        if not url:
            return True  # coding/general are in-process

        try:
            resp = requests.get(f"{url}/health", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False
