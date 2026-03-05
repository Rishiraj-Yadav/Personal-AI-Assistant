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

    # Class-level dict for HITL approvals — shared across all instances
    pending_approvals: Dict[str, Any] = {}

    @classmethod
    def resolve_approval(cls, pipeline_id: str, step_id: str, approved: bool) -> bool:
        """Resolve a pending HITL approval. Called by WebSocket/API endpoint."""
        key = f"{pipeline_id}:{step_id}"
        if key in cls.pending_approvals:
            cls.pending_approvals[key]["approved"] = approved
            cls.pending_approvals[key]["event"].set()
            return True
        return False

    @classmethod
    def get_pending_approvals(cls) -> List[Dict]:
        """Get all pending HITL approvals for the frontend."""
        return [
            {"key": k, "node": v["node"], "pipeline_id": v["pipeline_id"]}
            for k, v in cls.pending_approvals.items()
        ]

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

        # ── HITL Checkpoint ──
        risk_level = getattr(node, "risk_level", "low")
        if risk_level == "high":
            logger.warning(f"⚠️ HITL Checkpoint: Step {node.id} ({node.agent}.{node.action}) is HIGH RISK.")
            self.monitor.log_step(
                pipeline_id, node.id, node.agent, node.action,
                event_type="hitl_checkpoint", status="waiting_approval"
            )

            # Store a pending approval event
            approval_key = f"{pipeline_id}:{node.id}"
            approval_event = asyncio.Event()
            PipelineEngine.pending_approvals[approval_key] = {
                "event": approval_event,
                "node": node.to_dict(),
                "pipeline_id": pipeline_id,
                "approved": None,
            }

            # Notify the frontend via callback
            if hasattr(self, '_current_callback') and self._current_callback:
                await self._current_callback({
                    "type": "hitl_approval_required",
                    "message": f"⚠️ HIGH RISK: {node.agent}.{node.action} requires your approval",
                    "pipeline_id": pipeline_id,
                    "step_id": node.id,
                    "agent": node.agent,
                    "action": node.action,
                    "params": node.params,
                })

            # Wait for approval (timeout: 120s auto-approve)
            try:
                await asyncio.wait_for(approval_event.wait(), timeout=120)
            except asyncio.TimeoutError:
                logger.info(f"⏰ HITL Timeout: Step {node.id} auto-approved after 120s.")

            approval_data = PipelineEngine.pending_approvals.pop(approval_key, {})
            if approval_data.get("approved") is False:
                logger.info(f"🛑 HITL DENIED: Step {node.id} rejected by user.")
                return StepResult(
                    step_id=node.id, agent=node.agent, action=node.action,
                    success=False, error="Step denied by user via HITL checkpoint",
                )

            logger.info(f"✅ HITL Checkpoint: Step {node.id} approved for execution.")

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
        elif node.agent == "qa":
            return await self._dispatch_qa(node, context)
        elif node.agent == "devops":
            return await self._dispatch_devops(node, context)
        elif node.agent == "email":
            return await self._dispatch_email(node, context)
        else:
            return await self._dispatch_general(node, context)

    async def _dispatch_desktop(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute via Desktop Agent HTTP API."""
        try:
            # ── MCP-lite Internal Protocol ──
            mcp_payload = {
                "action": node.action,
                "resources": node.params,
                "context": context
            }

            # Map action to Desktop Agent skill format
            skill_map = {
                "open_app": "app_launcher",
                "screenshot": "screenshot",
                "mouse_click": "mouse_control",
                "keyboard_type": "keyboard_control",
                "window_manage": "window_manager",
            }
            skill_name = skill_map.get(mcp_payload["action"], mcp_payload["action"])

            # Build Legacy HTTP request
            payload = {
                "skill": skill_name,
                "args": {**mcp_payload["resources"], **mcp_payload["context"]},
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
            # ── MCP-lite Internal Protocol ──
            mcp_payload = {
                "action": node.action,
                "resources": node.params,
                "context": context
            }

            # Extract resources and context
            params = {**mcp_payload["resources"], **mcp_payload["context"]}
            goal = params.get("goal") or params.get("url") or mcp_payload["action"]

            # Legacy HTTP Payload
            payload = {"goal": goal}

            # Pass CDP URL if available from context (Desktop → Browser handoff)
            if mcp_payload["context"].get("cdp_url"):
                payload["cdp_url"] = mcp_payload["context"]["cdp_url"]

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

            # ── Self-Correction: Check if QA feedback exists from a previous iteration ──
            qa_feedback = context.get("qa_feedback")
            previous_error = context.get("previous_error") or qa_feedback
            iteration = int(context.get("correction_iteration", 1))

            if previous_error and iteration > 1:
                logger.info(f"🔄 Self-Correction: Coding iteration {iteration} with QA feedback")

            result = await code_specialist.generate_code(
                description=description,
                context=None,
                iteration=iteration,
                previous_error=previous_error,
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
                    context_out={
                        "code_output": exec_result.get("stdout", ""),
                        "files": result.get("files", {}),
                        "project_type": result.get("project_type", "python")
                    }
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

    async def _dispatch_qa(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute QA Verification Agent to write and run tests."""
        try:
            from .qa_specialist_agent import qa_specialist

            # The code files should come from the context (previous coding step's output)
            files = context.get("files", {})
            if not files and node.params.get("files"):
                files = node.params["files"]
                
            project_type = context.get("project_type", node.params.get("project_type", "python"))
            request_desc = node.params.get("task", "Verify the generated code works correctly.")

            if not files:
                return StepResult(
                    step_id=node.id, agent="qa", action=node.action,
                    success=False, error="No files provided to QA agent in context or params."
                )

            result = await qa_specialist.verify_code(
                files=files, project_type=project_type, original_request=request_desc
            )

            tests_passed = result.get("tests_passed", False)
            return StepResult(
                step_id=node.id, agent="qa", action=node.action,
                success=tests_passed,
                output=result,
                context_out={
                    "tests_passed": tests_passed,
                    "qa_feedback": result.get("feedback", ""),
                    "test_output": result.get("test_output", ""),
                }
            )
        except Exception as e:
            return StepResult(
                step_id=node.id, agent="qa", action=node.action,
                success=False, error=str(e),
            )

    async def _dispatch_devops(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute DevOps Agent for infrastructure management."""
        try:
            from .devops_agent import devops_agent

            result = await devops_agent.execute(
                action=node.action,
                params=node.params,
                context=context,
            )

            return StepResult(
                step_id=node.id, agent="devops", action=node.action,
                success=result.get("success", False),
                output=result,
                context_out={
                    "devops_status": result.get("message", ""),
                    "services_health": result.get("services", {}),
                },
            )
        except Exception as e:
            return StepResult(
                step_id=node.id, agent="devops", action=node.action,
                success=False, error=str(e),
            )

    async def _dispatch_email(self, node: DAGNode, context: Dict) -> StepResult:
        """Execute Email Agent for sending/reading emails."""
        try:
            from .email_agent import email_agent

            result = await email_agent.execute(
                action=node.action,
                params=node.params,
                context=context,
            )

            return StepResult(
                step_id=node.id, agent="email", action=node.action,
                success=result.get("success", False),
                output=result,
                context_out={
                    "email_result": result.get("message", ""),
                },
            )
        except Exception as e:
            return StepResult(
                step_id=node.id, agent="email", action=node.action,
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
