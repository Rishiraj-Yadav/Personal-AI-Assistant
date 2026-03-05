"""
Supervisor Agent — Top-level dynamic orchestrator.

Responsibilities:
- Accept user request
- Call Task Planner to decompose into execution DAG
- Monitor Pipeline Engine execution
- Re-plan on failures (retry, fallback, skip)
- Aggregate results into final user-facing response
"""

import asyncio
import uuid
import json
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from loguru import logger

from .task_planner import task_planner, ExecutionDAG, DAGNode
from .pipeline_engine import PipelineEngine, PipelineResult
from .context_memory import ContextMemory
from .monitor import agent_monitor


MAX_PIPELINE_RETRIES = 3


class SupervisorAgent:
    """
    Dynamic orchestrator that plans, executes, and re-plans pipelines.
    Entry point for all multi-agent task processing.
    """

    def __init__(self):
        self.engine = PipelineEngine()
        self.planner = task_planner
        self.monitor = agent_monitor
        logger.info("✅ Supervisor Agent initialized")

    async def process(
        self,
        user_message: str,
        conversation_id: str = None,
        message_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point: plan → execute → re-plan on failure → summarize.

        Args:
            user_message: The user's raw instruction
            conversation_id: Optional conversation ID for context
            message_callback: Async callback for streaming progress to frontend

        Returns:
            Dict with output, metadata, agent_path, etc.
        """
        pipeline_id = f"pipe_{uuid.uuid4().hex[:10]}"
        start_time = datetime.now()

        logger.info(f"🧠 Supervisor: '{user_message[:60]}...' → pipeline {pipeline_id}")

        if message_callback:
            await message_callback({
                "type": "status",
                "message": "🧠 Analyzing your request...",
            })

        # ── Step 1: Plan ──
        try:
            dag = await self.planner.decompose(user_message)
        except Exception as e:
            logger.error(f"Planner failed: {e}")
            dag = ExecutionDAG(
                nodes=[DAGNode(id="0", agent="general", action="chat")],
                complexity="simple",
                reasoning=f"Planner error: {e}",
            )

        # For simple general queries, skip the pipeline entirely
        if (
            len(dag.nodes) == 1
            and dag.nodes[0].agent == "general"
            and dag.nodes[0].action == "chat"
        ):
            return self._general_fallback(user_message, pipeline_id, start_time, dag)

        logger.info(
            f"📋 Plan: {len(dag.nodes)} steps, complexity={dag.complexity}"
        )
        if message_callback:
            step_preview = ", ".join(
                f"{n.agent}.{n.action}" for n in dag.nodes
            )
            await message_callback({
                "type": "pipeline_plan",
                "message": f"📋 Plan: {step_preview}",
                "steps": [n.to_dict() for n in dag.nodes],
                "complexity": dag.complexity,
            })

        # ── Step 2: Execute with re-planning ──
        memory = ContextMemory(pipeline_id)
        result = None

        MAX_SELF_CORRECTIONS = 3

        for attempt in range(1, MAX_PIPELINE_RETRIES + 1):
            result = await self.engine.execute(
                pipeline_id=pipeline_id,
                dag=dag,
                memory=memory,
                user_message=user_message,
                callback=message_callback,
            )

            if result.all_succeeded:
                break

            # ── Self-Correction Loop ──
            # Check if the failure was from a QA step specifically
            qa_failures = [
                s for s in result.steps
                if s.agent == "qa" and not s.success
            ]

            if qa_failures:
                # Find the coding step that preceded the QA step
                coding_steps = [s for s in result.steps if s.agent == "coding" and s.success]
                correction_iteration = int(memory.get_session("correction_iteration", 1))

                if correction_iteration < MAX_SELF_CORRECTIONS and coding_steps:
                    correction_iteration += 1
                    qa_feedback = qa_failures[0].output.get("feedback", qa_failures[0].error) if isinstance(qa_failures[0].output, dict) else qa_failures[0].error
                    logger.info(
                        f"🔄 Self-Correction: QA failed → re-running coding with feedback "
                        f"(iteration {correction_iteration}/{MAX_SELF_CORRECTIONS})"
                    )

                    # Store correction context so _dispatch_coding picks it up
                    memory.set_session("correction_iteration", correction_iteration)
                    memory.set_session("qa_feedback", qa_feedback)
                    memory.set_session("previous_error", qa_feedback)

                    if message_callback:
                        await message_callback({
                            "type": "self_correction",
                            "message": f"🔄 QA failed — auto-correcting code (attempt {correction_iteration}/{MAX_SELF_CORRECTIONS})...",
                            "iteration": correction_iteration,
                            "feedback_preview": str(qa_feedback)[:200],
                        })

                    # Rebuild a mini DAG: coding → qa
                    correction_dag = ExecutionDAG(
                        nodes=[
                            DAGNode(
                                id=f"fix_{correction_iteration}",
                                agent="coding",
                                action="generate",
                                params=dag.nodes[0].params if dag.nodes else {},
                                context_keys=["qa_feedback", "previous_error", "correction_iteration", "files", "project_type"],
                                timeout_s=60,
                                retries=1,
                                risk_level="medium",
                            ),
                            DAGNode(
                                id=f"verify_{correction_iteration}",
                                agent="qa",
                                action="verify",
                                depends_on=[f"fix_{correction_iteration}"],
                                context_keys=["files", "project_type"],
                                timeout_s=60,
                                retries=0,
                                risk_level="low",
                            ),
                        ],
                        complexity="compound",
                        reasoning=f"Self-correction iteration {correction_iteration}",
                    )
                    dag = correction_dag
                    continue  # Re-run with correction DAG

                else:
                    logger.warning(f"🛑 Max self-corrections ({MAX_SELF_CORRECTIONS}) reached — accepting result")
                    break

            # Re-plan failed steps (non-QA failures)
            failed_steps = [
                {"step_id": s.step_id, "error": s.error}
                for s in result.steps if not s.success
            ]
            logger.info(
                f"🔄 Re-planning (attempt {attempt}): "
                f"{len(failed_steps)} failed steps"
            )

            new_dag = await self.planner.replan(dag, failed_steps, attempt)
            if new_dag is None:
                logger.warning("🛑 Re-plan returned None — unrecoverable")
                break

            dag = new_dag

            if message_callback:
                await message_callback({
                    "type": "replanning",
                    "message": f"🔄 Re-planning (attempt {attempt}/{MAX_PIPELINE_RETRIES})...",
                    "attempt": attempt,
                })

        # ── Step 3: Build final response ──
        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        if message_callback and result:
            status = "✅ Complete" if result.all_succeeded else "⚠️ Partial"
            await message_callback({
                "type": "pipeline_complete",
                "message": f"{status} — {len(result.steps)} steps in {duration_ms}ms",
                "success": result.all_succeeded,
            })

        return self._build_response(
            result=result,
            user_message=user_message,
            pipeline_id=pipeline_id,
            dag=dag,
            start_time=start_time,
            end_time=end_time,
        )

    def _general_fallback(
        self,
        user_message: str,
        pipeline_id: str,
        start_time: datetime,
        dag: ExecutionDAG,
    ) -> Dict[str, Any]:
        """For simple general queries, return immediately without pipeline."""
        return {
            "success": True,
            "task_type": "general",
            "confidence": 0.9,
            "output": "General query (using existing LLM)",
            "pipeline_id": pipeline_id,
            "agent_path": ["supervisor", "general"],
            "metadata": {
                "dag": dag.to_dict(),
                "total_steps": 1,
                "pipeline_mode": True,
                "start_time": start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
            },
        }

    def _build_response(
        self,
        result: Optional[PipelineResult],
        user_message: str,
        pipeline_id: str,
        dag: ExecutionDAG,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """Build final response dict for the API layer."""
        if not result:
            return {
                "success": False,
                "task_type": dag.nodes[0].agent if dag.nodes else "general",
                "output": "❌ Pipeline execution produced no result",
                "pipeline_id": pipeline_id,
                "agent_path": ["supervisor"],
                "error": "No result",
            }

        # Determine primary task type
        agents_used = list({s.agent for s in result.steps})
        primary_type = agents_used[0] if len(agents_used) == 1 else "multi"

        # Collect step outputs for rich response
        step_outputs = []
        for step in result.steps:
            step_outputs.append({
                "agent": step.agent,
                "action": step.action,
                "success": step.success,
                "output": step.output,
                "error": step.error,
                "duration_ms": step.duration_ms,
                "attempt": step.attempt,
                "used_fallback": step.used_fallback,
            })

        return {
            "success": result.all_succeeded,
            "task_type": primary_type,
            "confidence": 0.9,
            "output": result.summary or "Pipeline completed",
            "pipeline_id": pipeline_id,
            "agent_path": ["supervisor"] + agents_used,

            # Pipeline details
            "pipeline_steps": step_outputs,
            "pipeline_mode": True,

            # Metadata
            "metadata": {
                "dag": dag.to_dict(),
                "total_steps": len(result.steps),
                "steps_succeeded": sum(1 for s in result.steps if s.success),
                "steps_failed": sum(1 for s in result.steps if not s.success),
                "total_duration_ms": result.total_duration_ms,
                "complexity": dag.complexity,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },

            "error": None if result.all_succeeded else "Some steps failed",
        }


# Global instance
supervisor = SupervisorAgent()
