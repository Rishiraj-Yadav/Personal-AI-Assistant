"""Desktop planner/executor with verification and recovery."""
from __future__ import annotations

import json
import ntpath
import os
import re
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi.encoders import jsonable_encoder
from loguru import logger

from app.agents.orchestration_models import (
    ExecutionPlan,
    ExecutionTraceEvent,
    PlanStep,
    RecoveryPolicy,
    VerificationRequirement,
)
from app.core.llm import llm_adapter
from app.skills.desktop_bridge import desktop_bridge
from app.services.enhanced_memory_service import enhanced_memory_service


class DesktopExecutionService:
    def __init__(self) -> None:
        self.memory = enhanced_memory_service
        self.llm = llm_adapter

    async def execute(
        self,
        *,
        user_message: str,
        user_id: str,
        user_context: str = "",
        step_hint: Optional[Dict[str, Any]] = None,
        message_callback: Optional[Callable] = None,
        approval_granted: bool = False,
        resume_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = self.memory.get_user_profile(user_id)
        plan = await self._build_plan(user_message, user_context, profile, step_hint, resume_context)
        trace: List[ExecutionTraceEvent] = [
            ExecutionTraceEvent(
                event_type="desktop_plan_ready",
                phase="analysis",
                message=plan.summary,
                agent_type="desktop",
                success=True,
                data={"plan": plan.model_dump()},
            )
        ]
        await self._emit(message_callback, "desktop_plan_ready", plan.summary, plan=plan.model_dump())

        previous_results: Dict[str, Dict[str, Any]] = {}
        completed_steps: List[Dict[str, Any]] = []
        all_evidence: List[Dict[str, Any]] = []
        success = True
        approval_state: Dict[str, Any] = {"status": "not_required", "reason": "", "affected_steps": []}
        clarification_state: Dict[str, Any] = {"status": "not_required", "reason": "", "options": []}

        for step in plan.steps:
            prepared_arguments, clarification = self._prepare_step_arguments(step, previous_results, plan)
            if clarification:
                success = False
                clarification_state = clarification
                trace.append(
                    ExecutionTraceEvent(
                        event_type="desktop_clarification_required",
                        phase="analysis",
                        step_id=step.step_id,
                        agent_type="desktop",
                        message=clarification.get("reason", clarification.get("question", "Clarification required.")),
                        success=False,
                        data={"clarification_state": clarification},
                    )
                )
                await self._emit(
                    message_callback,
                    "clarification_required",
                    clarification.get("question", clarification.get("reason", "Clarification required.")),
                    step_id=step.step_id,
                    clarification_state=clarification,
                )
                break

            if step.approval_level != "none" and not approval_granted:
                approval_state = self._build_step_approval_state(step, prepared_arguments, plan)
                success = False
                trace.append(
                    ExecutionTraceEvent(
                        event_type="desktop_approval_required",
                        phase="analysis",
                        step_id=step.step_id,
                        agent_type="desktop",
                        message=approval_state.get("reason", "Approval required."),
                        success=False,
                        data={"approval_state": approval_state},
                    )
                )
                await self._emit(
                    message_callback,
                    "approval_required",
                    approval_state.get("reason", "Approval required."),
                    step_id=step.step_id,
                    approval_state=approval_state,
                )
                break

            await self._emit(message_callback, "desktop_step_started", step.goal, step=step.model_dump())
            result = await self._run_step(
                step,
                previous_results,
                profile,
                message_callback,
                approval_granted,
                prepared_arguments=prepared_arguments,
            )
            previous_results[step.step_id] = result
            completed_steps.append(result)
            trace.extend(result.get("trace_events", []))
            all_evidence.extend(result.get("evidence", []))
            if not result.get("success"):
                success = False
                break

        if clarification_state.get("status") == "required":
            summary = self._build_paused_summary(
                completed_steps,
                self._format_clarification_prompt(clarification_state),
            )
        elif approval_state.get("status") == "required":
            summary = self._build_paused_summary(
                completed_steps,
                f"Approval is required before I continue.\n\nReason: {approval_state.get('reason', 'Confirmation needed.')}",
            )
        else:
            summary = self._build_summary(completed_steps, success)
        is_paused = approval_state.get("status") == "required" or clarification_state.get("status") == "required"
        if plan.workflow_key and success:
            self.memory.record_workflow_run(
                user_id,
                plan.workflow_key,
                plan.workflow_name or plan.summary,
                success=True,
                parameters=plan.metadata,
                description=plan.summary,
                is_builtin=plan.workflow_source in {"builtin", "heuristic"},
            )
        elif plan.workflow_key and not is_paused:
            self.memory.record_workflow_run(
                user_id,
                plan.workflow_key,
                plan.workflow_name or plan.summary,
                success=False,
                parameters=plan.metadata,
                description=plan.summary,
                is_builtin=plan.workflow_source in {"builtin", "heuristic"},
            )
        if success:
            self._learn_from_success(user_id, plan, completed_steps)

        serialized_trace = [jsonable_encoder(event) for event in trace]
        serialized_steps = [self._serialize_completed_step(step) for step in completed_steps]
        return {
            "success": success,
            "output": summary,
            "plan": plan,
            "trace": serialized_trace,
            "approval_state": approval_state,
            "clarification_state": clarification_state,
            "desktop_result": {
                "plan": plan.model_dump(),
                "completed_steps": serialized_steps,
                "steps_completed": len([step for step in serialized_steps if step.get("success")]),
                "steps_total": len(plan.steps),
                "evidence": all_evidence[-10:],
                "approval_state": approval_state,
                "clarification_state": clarification_state,
            },
        }

    async def _emit(self, callback: Optional[Callable], event_type: str, message: str, **data: Any) -> None:
        if not callback:
            return
        payload = {"type": event_type, "message": message}
        payload.update(data)
        try:
            await callback(jsonable_encoder(payload))
        except Exception as exc:
            logger.warning(f"Desktop callback failed for {event_type}: {exc}")

    async def _build_plan(
        self,
        user_message: str,
        user_context: str,
        profile: Dict[str, Any],
        step_hint: Optional[Dict[str, Any]],
        resume_context: Optional[Dict[str, Any]],
    ) -> ExecutionPlan:
        if step_hint and step_hint.get("tool_name"):
            return self._plan_from_step_hint(step_hint)
        if resume_context:
            resumed = self._plan_from_resume_context(user_message, resume_context)
            if resumed:
                return resumed
        heuristic = self._heuristic_plan(user_message, profile)
        if heuristic:
            return heuristic
        llm_plan = await self._llm_plan(user_message, user_context, profile)
        if llm_plan:
            return llm_plan
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            task_type="desktop",
            summary="Attempt the request as a verified desktop action.",
            steps=[
                self._step(
                    1,
                    "Attempt the desktop action.",
                    user_message,
                    "open_application",
                    {"name": user_message},
                    verification_method="composite",
                    verification_target=user_message,
                    retry_budget=1,
                )
            ],
            workflow_source="fallback",
        )

    def _plan_from_step_hint(self, step_hint: Dict[str, Any]) -> ExecutionPlan:
        verification = step_hint.get("verification") or {}
        recovery = step_hint.get("recovery") or {}
        step = PlanStep(
            step_id=step_hint.get("step_id", "step-1"),
            agent_type="desktop",
            goal=step_hint.get("goal", "Execute the desktop action."),
            inputs=step_hint.get("inputs") or {"message": step_hint.get("goal", ""), "arguments": {}},
            approval_level=step_hint.get("approval_level", "none"),
            safety_level=step_hint.get("safety_level", "safe"),
            tool_name=step_hint.get("tool_name", ""),
            success_criteria=step_hint.get("success_criteria", ""),
            fallback_strategy=step_hint.get("fallback_strategy", ""),
            verification=VerificationRequirement(**verification) if verification else VerificationRequirement(),
            recovery=RecoveryPolicy(**recovery) if recovery else RecoveryPolicy(),
            retry_budget=int(step_hint.get("retry_budget", 0) or 0),
        )
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            task_type="desktop",
            summary=step.goal,
            steps=[step],
            workflow_source="top_level_step",
        )

    def _plan_from_resume_context(
        self,
        user_message: str,
        resume_context: Dict[str, Any],
    ) -> Optional[ExecutionPlan]:
        kind = str(resume_context.get("kind", "") or "").lower()
        selected_path = str(
            resume_context.get("selected_path")
            or (resume_context.get("selected_option") or {}).get("value")
            or ""
        ).strip()

        if kind == "open_folder" and selected_path:
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Open the resolved folder {selected_path}.",
                workflow_source="clarification_resume",
                metadata={"resolved_path": selected_path},
                steps=[
                    self._step(
                        1,
                        "Open the selected folder.",
                        user_message,
                        "open_application",
                        {"name": selected_path},
                        verification_method="file",
                        verification_target=selected_path,
                        verification_expected={"exists": True},
                        retry_budget=1,
                    )
                ],
            )

        if kind == "scoped_folder_search" and selected_path:
            inner_target = str(resume_context.get("inner_target", "") or "").strip()
            steps = [
                self._step(
                    1,
                    "Open the selected outer folder.",
                    user_message,
                    "open_application",
                    {"name": selected_path},
                    verification_method="file",
                    verification_target=selected_path,
                    verification_expected={"exists": True},
                    retry_budget=1,
                )
            ]
            if inner_target:
                steps.append(
                    self._step(
                        2,
                        "Search inside the selected folder.",
                        user_message,
                        "search_system",
                        {"query": inner_target, "roots": [selected_path], "max_results": 25},
                        verification_method="file",
                        verification_target=inner_target,
                        verification_expected={"count_at_least": 1, "match_type": "folder"},
                        retry_budget=1,
                        depends_on=["step-1"],
                    )
                )
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Continue with the selected folder {selected_path}.",
                workflow_source="clarification_resume",
                metadata={"resolved_path": selected_path, "inner_target": inner_target},
                steps=steps,
            )

        if kind == "write_file_path":
            file_path = str(resume_context.get("path", "") or "").strip()
            if file_path:
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Create or update {file_path}.",
                    workflow_source="approval_resume",
                    metadata={"resolved_path": file_path},
                    steps=[
                        self._step(
                            1,
                            "Create or update the requested file.",
                            user_message,
                            "write_file",
                            {
                                "path": file_path,
                                "content": str(resume_context.get("content", "") or ""),
                                "append": bool(resume_context.get("append", False)),
                            },
                            verification_method="file",
                            verification_target=file_path,
                            verification_expected={"exists": True},
                            retry_budget=0,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )

        if kind == "write_file" and selected_path:
            file_name = str(resume_context.get("file_name", "") or "").strip()
            if file_name:
                full_path = self._join_path(selected_path, file_name)
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Create or update {full_path}.",
                    workflow_source="clarification_resume",
                    metadata={"resolved_path": full_path},
                    steps=[
                        self._step(
                            1,
                            "Create or update the requested file.",
                            user_message,
                            "write_file",
                            {
                                "path": full_path,
                                "content": str(resume_context.get("content", "") or ""),
                                "append": bool(resume_context.get("append", False)),
                            },
                            verification_method="file",
                            verification_target=full_path,
                            verification_expected={"exists": True},
                            retry_budget=0,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )
        if kind == "create_folder_path":
            folder_path = str(resume_context.get("path", "") or "").strip()
            if folder_path:
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Create the folder {folder_path}.",
                    workflow_source="approval_resume",
                    metadata={"resolved_path": folder_path},
                    steps=[
                        self._step(
                            1,
                            "Create the requested folder.",
                            user_message,
                            "create_folder",
                            {"path": folder_path},
                            verification_method="file",
                            verification_target=folder_path,
                            verification_expected={"exists": True},
                            retry_budget=0,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )

        if kind == "read_file_path":
            file_path = str(resume_context.get("path", "") or "").strip()
            if file_path:
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Read the file {file_path}.",
                    workflow_source="approval_resume",
                    metadata={"resolved_path": file_path},
                    steps=[
                        self._step(
                            1,
                            "Read the requested file.",
                            user_message,
                            "read_file",
                            {"path": file_path},
                            verification_method="file",
                            verification_target=file_path,
                            verification_expected={"exists": True},
                            retry_budget=0,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )

        if kind == "read_file" and selected_path:
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Read the file at {selected_path}.",
                workflow_source="clarification_resume",
                metadata={"resolved_path": selected_path},
                steps=[
                    self._step(
                        1,
                        "Read the requested file.",
                        user_message,
                        "read_file",
                        {"path": selected_path},
                        verification_method="file",
                        verification_target=selected_path,
                        verification_expected={"exists": True},
                        retry_budget=0,
                        approval_level="confirm",
                        safety_level="confirm",
                    )
                ],
            )

        if kind in {"move_path", "copy_path"}:
            source = str(resume_context.get("source", "") or "").strip()
            destination = str(resume_context.get("destination", "") or "").strip()
            if source and destination:
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"{'Move' if kind == 'move_path' else 'Copy'} to {destination}.",
                    workflow_source="approval_resume",
                    metadata={"resolved_path": destination},
                    steps=[
                        self._step(
                            1,
                            "Resume the requested file operation.",
                            user_message,
                            kind,
                            {"source": source, "destination": destination},
                            verification_method="file",
                            verification_target=destination,
                            verification_expected={"exists": True},
                            retry_budget=1,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )
        return None

    def _step(
        self,
        index: int,
        goal: str,
        message: str,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        verification_method: str = "none",
        verification_target: str = "",
        verification_expected: Optional[Dict[str, Any]] = None,
        retry_budget: int = 0,
        depends_on: Optional[List[str]] = None,
        approval_level: str = "none",
        safety_level: str = "safe",
    ) -> PlanStep:
        return PlanStep(
            step_id=f"step-{index}",
            agent_type="desktop",
            goal=goal,
            inputs={"message": message, "arguments": arguments},
            depends_on=depends_on or [],
            tool_name=tool_name,
            approval_level=approval_level,  # type: ignore[arg-type]
            safety_level=safety_level,  # type: ignore[arg-type]
            verification=VerificationRequirement(
                method=verification_method,  # type: ignore[arg-type]
                target=verification_target,
                expected=verification_expected or {},
            ),
            recovery=RecoveryPolicy(
                strategy="Retry with desktop fallbacks.",
                alternate_tools=["list_windows", "get_active_window", "read_screen_text"],
                max_retries=retry_budget,
            ),
            retry_budget=retry_budget,
        )

    def _heuristic_plan(self, user_message: str, profile: Dict[str, Any]) -> Optional[ExecutionPlan]:
        message_lower = user_message.lower()
        browser = profile.get("preferred_browser") or "chrome"
        workspace = os.getenv("WORKSPACE_PATH", os.path.abspath(os.path.join(".", "workspace")))

        if any(phrase in message_lower for phrase in ("coding setup", "developer setup", "coding environment", "dev setup")):
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary="Open the personalized coding setup.",
                workflow_key="open_coding_setup",
                workflow_name="Open Coding Setup",
                workflow_source="heuristic",
                metadata={"workspace_path": workspace},
                steps=[
                    self._step(1, "Open the preferred editor.", f"Open {profile.get('preferred_editor') or 'code'}.", "open_application", {"name": profile.get("preferred_editor") or "code"}, verification_method="composite", verification_target=profile.get("preferred_editor") or "code", retry_budget=1),
                    self._step(2, "Open the preferred terminal.", f"Open {profile.get('preferred_terminal') or 'powershell'}.", "open_application", {"name": profile.get("preferred_terminal") or "powershell"}, verification_method="composite", verification_target=profile.get("preferred_terminal") or "powershell", retry_budget=1, depends_on=["step-1"]),
                    self._step(3, "Open the workspace folder.", f"Open {workspace}.", "open_application", {"name": workspace}, verification_method="file", verification_target=workspace, verification_expected={"exists": True}, retry_budget=1, depends_on=["step-2"]),
                ],
            )

        if "open browser and search" in message_lower or "search this in browser" in message_lower:
            query = self._extract_search_query(user_message)
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary="Open the browser and perform a verified search.",
                workflow_key="open_browser_search",
                workflow_name="Open Browser And Search",
                workflow_source="heuristic",
                metadata={"query": query, "browser": browser},
                steps=[
                    self._step(1, "Open the preferred browser.", f"Open {browser}.", "open_application", {"name": browser}, verification_method="browser", verification_target=browser, retry_budget=1),
                    self._step(2, "Type the search query.", f"Type {query}.", "type_text", {"text": query}, verification_method="ocr", verification_target=query, verification_expected={"contains_any_tokens": query.split()[:3]}, retry_budget=1, depends_on=["step-1"]),
                    self._step(3, "Submit the search query.", "Press Enter.", "press_key", {"key": "enter"}, verification_method="browser", verification_target=query, verification_expected={"title_or_ocr_contains_any_tokens": query.split()[:3]}, retry_budget=1, depends_on=["step-2"]),
                ],
            )

        if "download" in message_lower and "move" in message_lower:
            destination = self._extract_destination(user_message, profile)
            query = self._extract_filename_hint(user_message) or "download"
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary="Find the downloaded file and move it to the requested destination.",
                workflow_key="download_file_and_move",
                workflow_name="Download File And Move It",
                workflow_source="heuristic",
                metadata={"destination": destination, "search_query": query},
                steps=[
                    self._step(1, "Search the Downloads folder.", f"Search the Downloads folder for {query}.", "search_system", {"query": query, "roots": [os.path.join(os.path.expanduser('~'), 'Downloads')], "max_results": 10}, verification_method="file", verification_target=query, verification_expected={"count_at_least": 1}, retry_budget=1),
                    self._step(2, "Move the first matching file.", f"Move the downloaded file to {destination}.", "move_path", {"use_first_match_from": "step-1", "destination": destination}, verification_method="file", verification_target=destination, verification_expected={"exists": True}, retry_budget=1, depends_on=["step-1"], approval_level="confirm", safety_level="confirm"),
                ],
            )

        scoped_folder_search = self._extract_scoped_folder_search(user_message)
        if scoped_folder_search:
            outer_target = scoped_folder_search["outer"]
            inner_target = scoped_folder_search["inner"]
            location_roots = self._extract_location_hint(user_message)
            outer_search_args: Dict[str, Any] = {"query": outer_target, "max_results": 25}
            if location_roots:
                outer_search_args["roots"] = location_roots
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Open the folder {outer_target} and search for {inner_target} inside it.",
                steps=[
                    self._step(
                        1,
                        "Find the outer folder.",
                        user_message,
                        "search_system",
                        outer_search_args,
                        verification_method="file",
                        verification_target=outer_target,
                        verification_expected={"count_at_least": 1, "match_type": "folder"},
                        retry_budget=1,
                    ),
                    self._step(
                        2,
                        "Open the outer folder.",
                        f"Open the folder {outer_target}.",
                        "open_application",
                        {
                            "use_first_match_from": "step-1",
                            "use_first_match_as": "name",
                            "use_first_match_type": "folder",
                        },
                        verification_method="file",
                        verification_target=outer_target,
                        verification_expected={"exists": True},
                        retry_budget=2,
                        depends_on=["step-1"],
                    ),
                    self._step(
                        3,
                        "Search inside the opened folder.",
                        f"Search for {inner_target} in {outer_target}.",
                        "search_system",
                        {
                            "query": inner_target,
                            "use_first_match_from": "step-2",
                            "use_first_match_as": "roots",
                            "max_results": 25,
                        },
                        verification_method="file",
                        verification_target=inner_target,
                        verification_expected={"count_at_least": 1, "match_type": "folder"},
                        retry_budget=1,
                        depends_on=["step-1", "step-2"],
                    ),
                ],
            )

        if any(term in message_lower for term in ("take a screenshot", "capture the screen", "screenshot")):
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary="Take a verified screenshot.", steps=[self._step(1, "Capture the screen.", "Take a screenshot.", "take_screenshot", {}, verification_method="screenshot")])
        if any(term in message_lower for term in ("what's on my screen", "what is on my screen", "read the screen", "screen text")):
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary="Read screen text.", steps=[self._step(1, "Read visible text.", "Read screen text.", "read_screen_text", {}, verification_method="ocr")])
        if "list windows" in message_lower or "open windows" in message_lower:
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary="Inspect windows.", steps=[self._step(1, "List visible windows.", "List windows.", "list_windows", {}, verification_method="window")])

        file_write_request = self._extract_file_write_request(user_message)
        if file_write_request:
            target_file_name = file_write_request["file_name"]
            file_content = file_write_request.get("content", "")
            target_directory = file_write_request["directory"]

            if self._looks_like_path(target_directory):
                full_path = self._join_path(target_directory, target_file_name)
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Create the file {target_file_name}.",
                    steps=[
                        self._step(
                            1,
                            "Create or update the requested file.",
                            user_message,
                            "write_file",
                            {"path": full_path, "content": file_content, "append": False},
                            verification_method="file",
                            verification_target=full_path,
                            verification_expected={"exists": True},
                            retry_budget=0,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )

            write_loc_roots = self._extract_location_hint(user_message)
            write_search_args: Dict[str, Any] = {"query": target_directory, "max_results": 25}
            if write_loc_roots:
                write_search_args["roots"] = write_loc_roots
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Find the folder {target_directory} and create {target_file_name} there.",
                steps=[
                    self._step(
                        1,
                        "Find the destination folder.",
                        user_message,
                        "search_system",
                        write_search_args,
                        verification_method="file",
                        verification_target=target_directory,
                        verification_expected={"count_at_least": 1, "match_type": "folder"},
                        retry_budget=1,
                    ),
                    self._step(
                        2,
                        "Create the requested file in the selected folder.",
                        user_message,
                        "write_file",
                        {
                            "use_first_match_from": "step-1",
                            "use_first_match_as": "path",
                            "use_first_match_type": "folder",
                            "append_path": target_file_name,
                            "content": file_content,
                            "append": False,
                        },
                        verification_method="file",
                        verification_target=target_file_name,
                        verification_expected={"exists": True},
                        retry_budget=0,
                        depends_on=["step-1"],
                        approval_level="confirm",
                        safety_level="confirm",
                    ),
                ],
            )

        open_folder_target = self._extract_open_folder_target(user_message)
        if open_folder_target:
            if self._looks_like_path(open_folder_target):
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Open the folder {open_folder_target}.",
                    steps=[
                        self._step(
                            1,
                            "Open the requested folder path.",
                            user_message,
                            "open_application",
                            {"name": open_folder_target},
                            verification_method="file",
                            verification_target=open_folder_target,
                            verification_expected={"exists": True},
                            retry_budget=1,
                        )
                    ],
                )

            location_roots = self._extract_location_hint(user_message)
            search_args: Dict[str, Any] = {"query": open_folder_target, "max_results": 10}
            if location_roots:
                search_args["roots"] = location_roots
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Find and open the folder {open_folder_target}.",
                steps=[
                    self._step(
                        1,
                        "Search for the requested folder.",
                        user_message,
                        "search_system",
                        search_args,
                        verification_method="file",
                        verification_target=open_folder_target,
                        verification_expected={"count_at_least": 1, "match_type": "folder"},
                        retry_budget=1,
                    ),
                    self._step(
                        2,
                        "Open the best matching folder.",
                        f"Open the folder {open_folder_target}.",
                        "open_application",
                        {
                            "use_first_match_from": "step-1",
                            "use_first_match_as": "name",
                            "use_first_match_type": "folder",
                        },
                        verification_method="file",
                        verification_target=open_folder_target,
                        verification_expected={"exists": True},
                        retry_budget=1,
                        depends_on=["step-1"],
                    ),
                ],
            )

        file_read_request = self._extract_file_read_request(user_message)
        if file_read_request:
            read_target = file_read_request["target"]
            if self._looks_like_path(read_target):
                return ExecutionPlan(
                    plan_id=str(uuid.uuid4()),
                    task_type="desktop",
                    summary=f"Read the file {read_target}.",
                    steps=[
                        self._step(
                            1,
                            "Read the requested file.",
                            user_message,
                            "read_file",
                            {"path": read_target},
                            verification_method="file",
                            verification_target=read_target,
                            verification_expected={"exists": True},
                            retry_budget=0,
                            approval_level="confirm",
                            safety_level="confirm",
                        )
                    ],
                )
            read_loc_roots = self._extract_location_hint(user_message)
            read_search_args: Dict[str, Any] = {"query": read_target, "max_results": 10}
            if read_loc_roots:
                read_search_args["roots"] = read_loc_roots
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Find and read the file {read_target}.",
                steps=[
                    self._step(
                        1,
                        "Search for the file.",
                        user_message,
                        "search_system",
                        read_search_args,
                        verification_method="file",
                        verification_target=read_target,
                        verification_expected={"count_at_least": 1},
                        retry_budget=1,
                    ),
                    self._step(
                        2,
                        "Read the found file.",
                        user_message,
                        "read_file",
                        {
                            "use_first_match_from": "step-1",
                            "use_first_match_as": "path",
                            "use_first_match_type": "file",
                        },
                        verification_method="file",
                        verification_target=read_target,
                        retry_budget=0,
                        depends_on=["step-1"],
                        approval_level="confirm",
                        safety_level="confirm",
                    ),
                ],
            )

        focus_match = re.search(r"focus\s+(.+)", user_message, re.IGNORECASE)
        if focus_match:
            title = focus_match.group(1).strip().strip('"')
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary=f"Focus {title}.", steps=[self._step(1, "Focus the requested window.", user_message, "focus_window", {"title": title}, verification_method="window", verification_target=title, retry_budget=1)])

        type_match = re.search(r"type\s+(.+?)\s+in\s+(.+)", user_message, re.IGNORECASE)
        if type_match:
            text, app = type_match.group(1).strip().strip('"'), type_match.group(2).strip().strip('"')
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=f"Open {app} and type the requested text.",
                steps=[
                    self._step(1, f"Open {app}.", f"Open {app}.", "open_application", {"name": app}, verification_method="composite", verification_target=app, retry_budget=1),
                    self._step(2, "Type the requested text.", f"Type {text}.", "type_text", {"text": text}, verification_method="ocr", verification_target=text, verification_expected={"contains_any_tokens": text.split()[:3]}, retry_budget=1, depends_on=["step-1"]),
                ],
            )

        quoted = re.findall(r'"([^"]+)"', user_message)
        if len(quoted) >= 2 and "move" in message_lower:
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary=f"Move to {quoted[1]}.", steps=[self._step(1, "Move the requested path.", user_message, "move_path", {"source": quoted[0], "destination": quoted[1]}, verification_method="file", verification_target=quoted[1], verification_expected={"exists": True}, retry_budget=1, approval_level="confirm", safety_level="confirm")])
        if len(quoted) >= 2 and "copy" in message_lower:
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary=f"Copy to {quoted[1]}.", steps=[self._step(1, "Copy the requested path.", user_message, "copy_path", {"source": quoted[0], "destination": quoted[1]}, verification_method="file", verification_target=quoted[1], verification_expected={"exists": True}, retry_budget=1, approval_level="confirm", safety_level="confirm")])

        folder_search_match = re.search(r"\bsearch(?:\s+the)?\s+(.+?)\s+folder\b", user_message, re.IGNORECASE)
        if folder_search_match:
            query = folder_search_match.group(1).strip().strip('"')
            search_loc_roots = self._extract_location_hint(user_message)
            s_args: Dict[str, Any] = {"query": query, "max_results": 25}
            if search_loc_roots:
                s_args["roots"] = search_loc_roots
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary=f"Search for {query}.", steps=[self._step(1, "Search the system.", user_message, "search_system", s_args, verification_method="file", verification_target=query, verification_expected={"count_at_least": 1}, retry_budget=1)])

        if any(keyword in message_lower for keyword in ("find", "locate", "search", "look for")) and any(keyword in message_lower for keyword in ("file", "folder", "document", "pdf", "image", "download")):
            query = self._extract_filename_hint(user_message)
            find_loc_roots = self._extract_location_hint(user_message)
            f_args: Dict[str, Any] = {"query": query, "max_results": 25}
            if find_loc_roots:
                f_args["roots"] = find_loc_roots
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary=f"Search for {query}.", steps=[self._step(1, "Search the system.", user_message, "search_system", f_args, verification_method="file", verification_target=query, verification_expected={"count_at_least": 1}, retry_budget=1)])

        open_match = re.search(r"(?:open|launch|start)\s+(.+)", user_message, re.IGNORECASE)
        if open_match:
            target = open_match.group(1).strip().strip('"')
            return ExecutionPlan(plan_id=str(uuid.uuid4()), task_type="desktop", summary=f"Open {target}.", steps=[self._step(1, f"Open {target}.", user_message, "open_application", {"name": target}, verification_method="composite", verification_target=target, retry_budget=1)])
        return None

    async def _llm_plan(self, user_message: str, user_context: str, profile: Dict[str, Any]) -> Optional[ExecutionPlan]:
        from app.models import Message, MessageRole

        try:
            llm_messages = [
                Message(
                    role=MessageRole.SYSTEM,
                    content=(
                        "You are a desktop planner. Return JSON with summary and steps. "
                        "Each step must include goal, tool_name, arguments, verification, recovery, and retry_budget. "
                        "Allowed tools: open_application, close_application, list_running_apps, is_app_running, "
                        "list_windows, get_active_window, focus_window, maximize_window, minimize_window, "
                        "take_screenshot, read_screen_text, type_text, press_key, press_hotkey, "
                        "search_system, move_path, copy_path, create_folder, write_file, delete_path, "
                        "list_directory, read_file, get_file_info."
                    ),
                ),
                Message(
                    role=MessageRole.USER,
                    content=(
                        f"User defaults: browser={profile.get('preferred_browser') or 'chrome'}, "
                        f"editor={profile.get('preferred_editor') or 'code'}, terminal={profile.get('preferred_terminal') or 'powershell'}.\n"
                        f"Context:\n{user_context[:600]}\n\nRequest:\n{user_message}"
                    ),
                ),
            ]
            llm_result = await self.llm.generate_response(llm_messages)
            raw = llm_result.get("response", "")
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                return None
            parsed = json.loads(match.group(0))
            steps: List[PlanStep] = []
            for index, step_data in enumerate(parsed.get("steps", []), start=1):
                if not isinstance(step_data, dict):
                    continue
                verification = step_data.get("verification") or {}
                recovery = step_data.get("recovery") or {}
                if isinstance(verification, str):
                    verification = {"description": verification}
                elif not isinstance(verification, dict):
                    verification = {}
                if isinstance(recovery, str):
                    recovery = {"strategy": recovery}
                elif not isinstance(recovery, dict):
                    recovery = {}
                steps.append(
                    PlanStep(
                        step_id=f"step-{index}",
                        agent_type="desktop",
                        goal=step_data.get("goal", f"Desktop step {index}"),
                        inputs={"message": step_data.get("goal", ""), "arguments": step_data.get("arguments") or {}},
                        tool_name=step_data.get("tool_name", ""),
                        verification=VerificationRequirement(**verification) if verification else VerificationRequirement(),
                        recovery=RecoveryPolicy(**recovery) if recovery else RecoveryPolicy(),
                        retry_budget=int(step_data.get("retry_budget", 0) or 0),
                    )
                )
            if not steps:
                return None
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type="desktop",
                summary=parsed.get("summary", "Execute the desktop request."),
                steps=steps,
                workflow_source="llm",
            )
        except Exception as exc:
            logger.warning(f"Desktop LLM planner failed: {exc}")
            return None

    async def _run_step(
        self,
        step: PlanStep,
        previous_results: Dict[str, Dict[str, Any]],
        profile: Dict[str, Any],
        message_callback: Optional[Callable],
        approval_granted: bool,
        prepared_arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        attempts = 0
        current_step = step.model_copy(deep=True)
        trace_events: List[ExecutionTraceEvent] = []
        latest_response: Dict[str, Any] = {}
        latest_verification: Dict[str, Any] = {}

        while attempts <= current_step.retry_budget:
            attempts += 1
            if attempts == 1 and prepared_arguments is not None:
                arguments = dict(prepared_arguments)
            else:
                arguments = self._resolve_arguments(current_step, current_step.inputs.get("arguments") or {}, previous_results)
            if approval_granted and current_step.tool_name in {"read_file", "write_file", "create_folder", "move_path", "copy_path", "delete_path"}:
                arguments["_approval_granted"] = True
            latest_response = await desktop_bridge.execute_skill(current_step.tool_name, arguments, safe_mode=False)
            trace_events.append(
                ExecutionTraceEvent(
                    event_type="desktop_action_executed",
                    phase="execution",
                    step_id=current_step.step_id,
                    agent_type="desktop",
                    message=f"{current_step.tool_name} attempt {attempts}",
                    success=latest_response.get("success"),
                    data={"arguments": arguments, "response": latest_response, "attempt": attempts},
                )
            )

            latest_verification = await self._verify_step(current_step, arguments, latest_response)
            trace_events.append(
                ExecutionTraceEvent(
                    event_type="desktop_verification",
                    phase="verification",
                    step_id=current_step.step_id,
                    agent_type="desktop",
                    message=latest_verification.get("reason", "Verification completed."),
                    success=latest_verification.get("verified"),
                    data={"verification": latest_verification, "attempt": attempts},
                )
            )
            await self._emit(
                message_callback,
                "desktop_verification",
                latest_verification.get("reason", "Verification completed."),
                step_id=current_step.step_id,
                success=latest_verification.get("verified", False),
                verification=latest_verification,
            )

            if latest_response.get("success") and latest_verification.get("verified"):
                return {
                    "step_id": current_step.step_id,
                    "tool_name": current_step.tool_name,
                    "success": True,
                    "message": latest_verification.get("reason") or current_step.goal,
                    "response": latest_response,
                    "verification": latest_verification,
                    "evidence": latest_verification.get("evidence") or latest_response.get("evidence") or [],
                    "trace_events": trace_events,
                }

            if attempts > current_step.retry_budget:
                break
            recovered = await self._recover_step(current_step, arguments, latest_response, latest_verification, profile, previous_results)
            trace_events.append(
                ExecutionTraceEvent(
                    event_type="desktop_recovery",
                    phase="recovery",
                    step_id=current_step.step_id,
                    agent_type="desktop",
                    message=recovered.get("message", "Retrying with recovery strategy."),
                    success=recovered.get("recovered", False),
                    data={"recovery": recovered, "attempt": attempts},
                )
            )
            await self._emit(message_callback, "desktop_recovery", recovered.get("message", "Retrying with recovery strategy."), step_id=current_step.step_id, recovery=recovered)
            if not recovered.get("recovered"):
                break
            current_step = recovered["step"]

        return {
            "step_id": current_step.step_id,
            "tool_name": current_step.tool_name,
            "success": False,
            "message": latest_verification.get("reason") or latest_response.get("error") or f"{current_step.tool_name} failed",
            "error": latest_verification.get("reason") or latest_response.get("error") or f"{current_step.tool_name} failed",
            "response": latest_response,
            "verification": latest_verification,
            "evidence": latest_verification.get("evidence") or latest_response.get("evidence") or [],
            "trace_events": trace_events,
        }

    def _resolve_arguments(
        self,
        step: PlanStep,
        arguments: Dict[str, Any],
        previous_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        resolved = dict(arguments)
        source_step = resolved.pop("use_first_match_from", None)
        target_key = resolved.pop("use_first_match_as", "")
        match_type = str(resolved.pop("use_first_match_type", "") or "").lower()
        match_index = max(int(resolved.pop("match_index", 0) or 0), 0)
        append_path = resolved.pop("append_path", None)
        if source_step and source_step in previous_results:
            source_result = previous_results[source_step].get("response", {}).get("result", {}) or {}
            matches = source_result.get("matches", [])
            if match_type:
                matches = [match for match in matches if str(match.get("type", "")).lower() == match_type]
            if matches:
                selected = matches[min(match_index, len(matches) - 1)]
                if match_index == 0:
                    resolution = self._select_match_resolution(
                        matches,
                        str(source_result.get("query") or step.verification.target or ""),
                    )
                    if resolution.get("status") == "selected" and resolution.get("match"):
                        selected = resolution["match"]
                selected_path = selected.get("path")
                if selected_path:
                    if append_path:
                        selected_path = self._join_path(selected_path, str(append_path))
                    if not target_key:
                        if step.tool_name in {"move_path", "copy_path"}:
                            target_key = "source"
                        elif step.tool_name == "open_application":
                            target_key = "name"
                        else:
                            target_key = "path"
                    resolved[target_key] = [selected_path] if target_key == "roots" else selected_path
            else:
                selected_path = source_result.get("path") or source_result.get("opened")
                selected_type = str(source_result.get("type", "")).lower()
                if selected_path and (not match_type or match_type == selected_type):
                    if append_path:
                        selected_path = self._join_path(str(selected_path), str(append_path))
                    if not target_key:
                        if step.tool_name in {"move_path", "copy_path"}:
                            target_key = "source"
                        elif step.tool_name == "open_application":
                            target_key = "name"
                        else:
                            target_key = "path"
                    resolved[target_key] = [selected_path] if target_key == "roots" else selected_path
        return resolved

    def _prepare_step_arguments(
        self,
        step: PlanStep,
        previous_results: Dict[str, Dict[str, Any]],
        plan: ExecutionPlan,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        arguments = dict(step.inputs.get("arguments") or {})
        clarification = self._maybe_build_clarification(step, previous_results, plan)
        if clarification:
            return {}, clarification
        return self._resolve_arguments(step, arguments, previous_results), None

    def _maybe_build_clarification(
        self,
        step: PlanStep,
        previous_results: Dict[str, Dict[str, Any]],
        plan: ExecutionPlan,
    ) -> Optional[Dict[str, Any]]:
        arguments = step.inputs.get("arguments") or {}
        source_step = arguments.get("use_first_match_from")
        if not source_step or source_step not in previous_results:
            return None

        match_index = int(arguments.get("match_index", 0) or 0)
        if match_index > 0:
            return None

        source_result = previous_results[source_step].get("response", {}).get("result", {}) or {}
        matches = list(source_result.get("matches") or [])
        match_type = str(arguments.get("use_first_match_type", "") or "").lower()
        if match_type:
            matches = [match for match in matches if str(match.get("type", "")).lower() == match_type]
        if len(matches) <= 1:
            return None

        query = str(
            source_result.get("query")
            or source_result.get("target")
            or step.verification.target
            or ""
        )
        resolution = self._select_match_resolution(matches, query)
        if resolution.get("status") != "clarification_required":
            return None

        resume_context = self._build_resume_context_from_step(step, plan)
        options = [
            self._build_clarification_option(match, index)
            for index, match in enumerate((resolution.get("options") or [])[:5])
        ]
        question = self._build_clarification_question(
            query=query,
            match_type=match_type or "path",
            options=options,
        )
        return {
            "status": "required",
            "reason": resolution.get("reason", "Clarification required before continuing."),
            "question": question,
            "options": options,
            "original_request": step.inputs.get("message", ""),
            "task_type": "desktop",
            "resume_context": resume_context,
        }

    def _select_match_resolution(
        self,
        matches: List[Dict[str, Any]],
        query: str,
    ) -> Dict[str, Any]:
        exact_matches = [match for match in matches if self._match_is_exact(match, query)]
        if len(exact_matches) == 1:
            return {"status": "selected", "match": exact_matches[0]}
        if len(exact_matches) > 1:
            return {
                "status": "clarification_required",
                "reason": f"Found multiple exact matches for {query}.",
                "options": exact_matches,
            }

        ordered = sorted(matches, key=lambda item: self._match_resolution_sort_key(item, query), reverse=True)
        if len(ordered) == 1:
            return {"status": "selected", "match": ordered[0]}

        first = ordered[0]
        second = ordered[1]
        first_score = int(first.get("score", 0) or 0)
        second_score = int(second.get("score", 0) or 0)
        if first_score >= second_score + 15:
            return {"status": "selected", "match": first}

        return {
            "status": "clarification_required",
            "reason": f"Found multiple similar matches for {query}.",
            "options": ordered[:5],
        }

    def _match_resolution_sort_key(self, match: Dict[str, Any], query: str) -> Tuple[int, int, int, str]:
        score = int(match.get("score", 0) or 0)
        exact = int(self._match_is_exact(match, query))
        depth = -int(match.get("depth", self._path_depth(str(match.get("path", "") or ""))))
        path = str(match.get("path", "") or "")
        return (score, exact, depth, path)

    def _build_clarification_option(self, match: Dict[str, Any], index: int) -> Dict[str, Any]:
        path = str(match.get("path", "") or "")
        return {
            "index": index + 1,
            "label": path,
            "value": path,
            "path": path,
            "type": match.get("type", "path"),
            "score": int(match.get("score", 0) or 0),
            "match_index": index,
            "exact_name": bool(match.get("exact_name") or match.get("exact_stem") or False),
            "root": match.get("root"),
            "depth": match.get("depth", self._path_depth(path)),
        }

    def _build_clarification_question(
        self,
        *,
        query: str,
        match_type: str,
        options: List[Dict[str, Any]],
    ) -> str:
        label = "folder" if match_type == "folder" else match_type
        lines = [
            f"I found multiple exact {label} matches for \"{query}\".",
            "Reply with 1, 2, or paste the full path:",
        ]
        for option in options[:5]:
            lines.append(f"{option['index']}. {option['path']}")
        return "\n".join(lines)

    def _build_step_approval_state(
        self,
        step: PlanStep,
        resolved_arguments: Dict[str, Any],
        plan: ExecutionPlan,
    ) -> Dict[str, Any]:
        target = self._format_action_target(step.tool_name, resolved_arguments)
        reason = f"I need your approval before I {target}."
        return {
            "status": "required",
            "reason": reason,
            "affected_steps": [step.step_id],
            "safety_level": step.safety_level,
            "workflow_name": plan.workflow_name,
            "resolved_target": target,
            "resume_context": self._build_resume_context_from_step(step, plan, resolved_arguments=resolved_arguments),
        }

    def _build_resume_context_from_step(
        self,
        step: PlanStep,
        plan: ExecutionPlan,
        *,
        resolved_arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        arguments = dict(step.inputs.get("arguments") or {})
        if step.tool_name == "open_application":
            later_search = next(
                (
                    candidate
                    for candidate in plan.steps
                    if step.step_id in candidate.depends_on and candidate.tool_name == "search_system"
                ),
                None,
            )
            if later_search:
                return {
                    "kind": "scoped_folder_search",
                    "inner_target": (later_search.inputs.get("arguments") or {}).get("query", ""),
                }
            return {"kind": "open_folder"}

        if step.tool_name == "read_file":
            if resolved_arguments and resolved_arguments.get("path"):
                return {
                    "kind": "read_file_path",
                    "path": resolved_arguments.get("path"),
                }
            return {"kind": "read_file"}

        if step.tool_name == "write_file":
            if resolved_arguments and resolved_arguments.get("path"):
                return {
                    "kind": "write_file_path",
                    "path": resolved_arguments.get("path"),
                    "content": resolved_arguments.get("content", ""),
                    "append": bool(resolved_arguments.get("append", False)),
                }
            file_name = str(arguments.get("append_path", "") or "").strip()
            if not file_name and arguments.get("path"):
                file_name = os.path.basename(str(arguments.get("path")))
            return {
                "kind": "write_file",
                "file_name": file_name,
                "content": arguments.get("content", ""),
                "append": bool(arguments.get("append", False)),
            }
        if step.tool_name == "create_folder":
            return {"kind": "create_folder_path", "path": (resolved_arguments or {}).get("path", arguments.get("path", ""))}
        if step.tool_name in {"move_path", "copy_path"}:
            return {
                "kind": step.tool_name,
                "source": (resolved_arguments or {}).get("source", arguments.get("source", "")),
                "destination": (resolved_arguments or {}).get("destination", arguments.get("destination", "")),
            }
        return {"kind": step.tool_name}

    def _format_action_target(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name == "read_file":
            return f"read the file `{arguments.get('path', '')}`"
        if tool_name == "write_file":
            return f"create or update the file `{arguments.get('path', '')}`"
        if tool_name == "create_folder":
            return f"create the folder `{arguments.get('path', '')}`"
        if tool_name == "move_path":
            return f"move `{arguments.get('source', '')}` to `{arguments.get('destination', '')}`"
        if tool_name == "copy_path":
            return f"copy `{arguments.get('source', '')}` to `{arguments.get('destination', '')}`"
        if tool_name == "delete_path":
            return f"delete `{arguments.get('path', '')}`"
        return f"run `{tool_name}`"

    def _match_is_exact(self, match: Dict[str, Any], query: str) -> bool:
        query_normalized = self._normalize_lookup_value(query)
        if not query_normalized:
            return False
        if match.get("exact_name") or match.get("exact_stem"):
            return True
        name = self._normalize_lookup_value(str(match.get("name", "") or ""))
        stem = self._normalize_lookup_value(os.path.splitext(str(match.get("name", "") or ""))[0])
        return name == query_normalized or stem == query_normalized

    def _normalize_lookup_value(self, value: str) -> str:
        candidate = self._sanitize_folder_phrase(str(value or ""))
        return candidate.strip().strip('"').strip("'").casefold()

    def _path_depth(self, path: str) -> int:
        normalized = os.path.normpath(path or "")
        return len([part for part in re.split(r"[\\/]+", normalized.rstrip("\\/")) if part])

    async def _verify_step(self, step: PlanStep, arguments: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = step.tool_name
        evidence = list(response.get("evidence") or [])
        observed_state = dict(response.get("observed_state") or {})

        if not response.get("success"):
            return {"verified": False, "reason": response.get("error") or f"{tool_name} failed.", "observed_state": observed_state, "evidence": evidence}

        if tool_name == "open_application":
            target = arguments.get("name") or step.verification.target
            opened_type = response.get("result", {}).get("type")
            if opened_type == "folder":
                target_path = os.path.normpath(str(target))
                target_name = (
                    ntpath.basename(target_path)
                    if re.match(r"^[A-Za-z]:\\", target_path) or "\\" in target_path
                    else os.path.basename(target_path)
                ).lower()
                active = await desktop_bridge.execute_skill("get_active_window", {}, safe_mode=False)
                windows = await desktop_bridge.execute_skill("list_windows", {}, safe_mode=False)
                ocr = await desktop_bridge.execute_skill("read_screen_text", {}, safe_mode=False)
                evidence.extend(active.get("evidence") or [])
                evidence.extend(windows.get("evidence") or [])
                evidence.extend(ocr.get("evidence") or [])
                active_title = str(active.get("result", {}).get("title", "") or "")
                window_titles = [str(window.get("title", "") or "") for window in windows.get("result", {}).get("windows", [])]
                ocr_text = str(ocr.get("result", {}).get("text", "") or "")
                explorer_matches = [
                    os.path.normpath(str(path))
                    for path in observed_state.get("matching_explorer_paths", []) or []
                    if path
                ]
                exact_match = target_path in explorer_matches
                title_match = bool(target_name) and (
                    target_name in active_title.lower() or any(target_name in title.lower() for title in window_titles)
                )
                ocr_match = bool(target_name) and target_name in ocr_text.lower()
                verified = exact_match or title_match or ocr_match
                observed_state.update(
                    {
                        "target_path": target_path,
                        "active_window": active_title,
                        "window_count": len(window_titles),
                        "title_match": title_match,
                        "ocr_match": ocr_match,
                        "exact_explorer_match": exact_match,
                    }
                )
                return {
                    "verified": verified,
                    "reason": (
                        f"Verified that the folder target opened at {target_path}."
                        if verified
                        else f"Verified that the folder target did not open as expected for {target_path}."
                    ),
                    "observed_state": observed_state,
                    "evidence": evidence,
                }
            if opened_type == "file":
                path_exists = bool(observed_state.get("exists", True))
                return {
                    "verified": path_exists,
                    "reason": f"Verified that the file target {'opened' if path_exists else 'did not open as expected'}.",
                    "observed_state": observed_state,
                    "evidence": evidence,
                }
            process_check = await desktop_bridge.execute_skill("is_app_running", {"name": target}, safe_mode=False)
            windows = await desktop_bridge.execute_skill("list_windows", {}, safe_mode=False)
            active = await desktop_bridge.execute_skill("get_active_window", {}, safe_mode=False)
            evidence.extend(process_check.get("evidence") or [])
            evidence.extend(windows.get("evidence") or [])
            evidence.extend(active.get("evidence") or [])
            titles = [window.get("title", "") for window in windows.get("result", {}).get("windows", [])]
            active_title = active.get("result", {}).get("title", "")
            verified = bool(process_check.get("result", {}).get("is_running")) or any(str(target).lower() in title.lower() for title in titles) or any(token.lower() in active_title.lower() for token in str(target).split())
            observed_state.update({"active_window": active_title, "window_count": len(titles)})
            return {"verified": verified, "reason": f"Verified that {target} {'opened' if verified else 'did not open as expected'}.", "observed_state": observed_state, "evidence": evidence}

        if tool_name in {"focus_window", "maximize_window", "minimize_window"}:
            active = await desktop_bridge.execute_skill("get_active_window", {}, safe_mode=False)
            evidence.extend(active.get("evidence") or [])
            active_title = active.get("result", {}).get("title", "")
            target = arguments.get("title") or step.verification.target
            verified = tool_name != "focus_window" or str(target).lower() in active_title.lower()
            observed_state["active_window"] = active_title
            return {"verified": verified, "reason": f"Window action {'verified' if verified else 'not verified'} for {target}.", "observed_state": observed_state, "evidence": evidence}

        if tool_name in {"move_path", "copy_path", "create_folder"}:
            target_path = arguments.get("destination") or arguments.get("path") or step.verification.target
            info = await desktop_bridge.execute_skill("get_file_info", {"path": target_path}, safe_mode=False)
            evidence.extend(info.get("evidence") or [])
            verified = info.get("success", False)
            observed_state["target_path"] = target_path
            return {"verified": verified, "reason": f"Path verification {'passed' if verified else 'failed'} for {target_path}.", "observed_state": observed_state, "evidence": evidence}

        if tool_name == "write_file":
            target_path = arguments.get("path") or step.verification.target
            info = await desktop_bridge.execute_skill("get_file_info", {"path": target_path}, safe_mode=False)
            evidence.extend(info.get("evidence") or [])
            verified = info.get("success", False)
            observed_state["target_path"] = target_path
            return {"verified": verified, "reason": f"File write verification {'passed' if verified else 'failed'} for {target_path}.", "observed_state": observed_state, "evidence": evidence}

        if tool_name == "read_file":
            file_content = response.get("result", {}).get("content", "")
            lines_returned = response.get("result", {}).get("lines_returned", 0)
            verified = bool(file_content) or lines_returned > 0
            observed_state["lines_returned"] = lines_returned
            return {"verified": verified, "reason": f"Read {lines_returned} lines from file." if verified else "File read returned no content.", "observed_state": observed_state, "evidence": evidence}

        if tool_name == "search_system":
            matches = response.get("result", {}).get("matches", [])
            match_type = str(step.verification.expected.get("match_type", "") or "").lower()
            if match_type:
                matches = [match for match in matches if str(match.get("type", "")).lower() == match_type]
            count = len(matches)
            expected = int(step.verification.expected.get("count_at_least", 0) or 0)
            verified = count >= expected if expected else True
            observed_state["result_count"] = count
            if match_type:
                observed_state["match_type"] = match_type
            label = f"{match_type} result(s)" if match_type else "result(s)"
            return {"verified": verified, "reason": f"Search returned {count} {label}.", "observed_state": observed_state, "evidence": evidence}

        if tool_name == "take_screenshot":
            verified = bool(response.get("result", {}).get("image_base64"))
            return {"verified": verified, "reason": "Screenshot captured successfully." if verified else "Screenshot capture did not return image data.", "observed_state": observed_state, "evidence": evidence}

        if tool_name in {"read_screen_text", "type_text", "press_key", "press_hotkey"} and step.verification.method in {"ocr", "browser", "composite"}:
            ocr = await desktop_bridge.execute_skill("read_screen_text", {}, safe_mode=False)
            active = await desktop_bridge.execute_skill("get_active_window", {}, safe_mode=False)
            evidence.extend(ocr.get("evidence") or [])
            evidence.extend(active.get("evidence") or [])
            ocr_text = ocr.get("result", {}).get("text", "")
            active_title = active.get("result", {}).get("title", "")
            tokens = step.verification.expected.get("contains_any_tokens") or step.verification.expected.get("title_or_ocr_contains_any_tokens") or []
            verified = not tokens or any(token.lower() in ocr_text.lower() or token.lower() in active_title.lower() for token in tokens)
            observed_state.update({"active_window": active_title, "ocr_excerpt": ocr_text[:200]})
            return {"verified": verified, "reason": "Input verification succeeded." if verified else "Could not verify the desktop input result.", "observed_state": observed_state, "evidence": evidence}

        return {"verified": True, "reason": f"{tool_name} completed successfully.", "observed_state": observed_state, "evidence": evidence}

    async def _recover_step(
        self,
        step: PlanStep,
        arguments: Dict[str, Any],
        response: Dict[str, Any],
        verification: Dict[str, Any],
        profile: Dict[str, Any],
        previous_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        tool_name = step.tool_name
        if tool_name == "open_application":
            source_step = step.inputs.get("arguments", {}).get("use_first_match_from")
            if source_step and source_step in previous_results:
                original_args = step.inputs.get("arguments", {})
                current_index = max(int(original_args.get("match_index", 0) or 0), 0)
                all_matches = previous_results[source_step].get("response", {}).get("result", {}).get("matches", [])
                match_type = str(original_args.get("use_first_match_type", "") or "").lower()
                if match_type:
                    all_matches = [match for match in all_matches if str(match.get("type", "")).lower() == match_type]
                if current_index + 1 < len(all_matches):
                    recovered = step.model_copy(deep=True)
                    recovered.inputs.setdefault("arguments", {})
                    recovered.inputs["arguments"]["match_index"] = current_index + 1
                    return {
                        "recovered": True,
                        "message": f"Retrying with the next {match_type or 'search'} match after the first path did not verify.",
                        "step": recovered,
                    }

            target = str(arguments.get("name", "")).lower()
            fallbacks = []
            if any(browser in target for browser in ("browser", "chrome", "edge", "firefox")):
                fallbacks = [profile.get("preferred_browser"), "chrome", "edge", "firefox"]
            elif any(editor in target for editor in ("code", "editor", "vscode", "pycharm", "notepad")):
                fallbacks = [profile.get("preferred_editor"), "code", "vscode", "notepad++", "notepad"]
            elif any(term in target for term in ("terminal", "powershell", "cmd", "wt", "bash")):
                fallbacks = [profile.get("preferred_terminal"), "wt", "powershell", "cmd"]
            fallbacks = [fallback for fallback in fallbacks if fallback and fallback.lower() != target]
            if fallbacks:
                recovered = step.model_copy(deep=True)
                recovered.inputs["arguments"] = {"name": fallbacks[0]}
                recovered.verification.target = fallbacks[0]
                return {"recovered": True, "message": f"Retrying with fallback target {fallbacks[0]}.", "step": recovered}

            raw_target = str(arguments.get("name", ""))
            folder_hint = self._extract_open_folder_target(raw_target) or os.path.basename(raw_target.rstrip("\\/"))
            if folder_hint:
                search_result = await desktop_bridge.execute_skill(
                    "search_system",
                    {"query": folder_hint, "max_results": 10},
                    safe_mode=False,
                )
                matches = search_result.get("result", {}).get("matches", [])
                folder_matches = [match for match in matches if str(match.get("type", "")).lower() == "folder"]
                if folder_matches:
                    recovered = step.model_copy(deep=True)
                    recovered.inputs["arguments"] = {"name": folder_matches[0].get("path")}
                    recovered.verification.target = folder_matches[0].get("path", folder_hint)
                    return {
                        "recovered": True,
                        "message": f"Found matching folder {folder_matches[0].get('path')} and will open it.",
                        "step": recovered,
                    }

        if tool_name == "focus_window":
            windows = await desktop_bridge.execute_skill("list_windows", {}, safe_mode=False)
            target = str(arguments.get("title", "")).lower()
            for window in windows.get("result", {}).get("windows", []):
                title = window.get("title", "")
                if target and target in title.lower():
                    recovered = step.model_copy(deep=True)
                    recovered.inputs["arguments"] = {"title": title}
                    recovered.verification.target = title
                    return {"recovered": True, "message": f"Retrying focus with matched title {title}.", "step": recovered}

        if tool_name == "search_system":
            recovered = step.model_copy(deep=True)
            args = dict(arguments)
            args["max_results"] = max(int(args.get("max_results", 10)), 25)
            args["max_depth"] = max(int(args.get("max_depth", 4)), 8)
            recovered.inputs["arguments"] = args
            return {"recovered": True, "message": "Broadening the search depth and result limit before retrying.", "step": recovered}

        if tool_name == "move_path":
            destination = arguments.get("destination")
            if destination:
                await desktop_bridge.execute_skill("create_folder", {"path": destination}, safe_mode=False)
                recovered = step.model_copy(deep=True)
                recovered.inputs["arguments"] = dict(arguments)
                return {"recovered": True, "message": f"Ensuring destination folder exists before retrying move to {destination}.", "step": recovered}

        if tool_name in {"type_text", "press_key", "press_hotkey"}:
            active = await desktop_bridge.execute_skill("get_active_window", {}, safe_mode=False)
            active_title = active.get("result", {}).get("title", "")
            if active_title:
                await desktop_bridge.execute_skill("focus_window", {"title": active_title}, safe_mode=False)
                return {"recovered": True, "message": f"Refocusing {active_title} before retrying input.", "step": step.model_copy(deep=True)}

        return {"recovered": False, "message": verification.get("reason") or response.get("error") or "No recovery strategy succeeded.", "step": step}

    def _build_summary(self, completed_steps: List[Dict[str, Any]], success: bool) -> str:
        lines = [f"Desktop assistant {'completed' if success else 'partially completed'} the request."]
        for step in completed_steps:
            prefix = "[OK]" if step.get("success") else "[FAIL]"
            lines.append(f"{prefix} {step.get('message') or step.get('error') or step.get('tool_name', 'desktop step')}")

            if step.get("tool_name") == "read_file" and step.get("success"):
                result = step.get("response", {}).get("result", {})
                content = result.get("content", "")
                total_lines = result.get("total_lines", 0)
                returned_lines = result.get("lines_returned", 0)
                file_path = result.get("path", "")
                if content:
                    if total_lines > returned_lines:
                        lines.append(f"\n--- File: {os.path.basename(file_path)} ({returned_lines}/{total_lines} lines) ---")
                    else:
                        lines.append(f"\n--- File: {os.path.basename(file_path)} ({total_lines} lines) ---")
                    lines.append(content.rstrip())
                    lines.append("--- End of file ---")
        return "\n".join(lines)

    def _build_paused_summary(self, completed_steps: List[Dict[str, Any]], prompt: str) -> str:
        base = self._build_summary(completed_steps, False) if completed_steps else "Desktop assistant paused the request."
        return f"{base}\n\n{prompt}".strip()

    def _format_clarification_prompt(self, clarification_state: Dict[str, Any]) -> str:
        question = clarification_state.get("question") or clarification_state.get("reason") or "Clarification required."
        options = clarification_state.get("options") or []
        if not options or "\n" in question:
            return question
        lines = [question]
        for option in options[:5]:
            lines.append(f"{option.get('index')}. {option.get('path') or option.get('label')}")
        return "\n".join(lines)

    def _learn_from_success(self, user_id: str, plan: ExecutionPlan, completed_steps: List[Dict[str, Any]]) -> None:
        favorite_apps: List[str] = []
        common_folders: List[str] = []
        preferred_browser = ""
        preferred_editor = ""
        preferred_terminal = ""
        for step in completed_steps:
            if not step.get("success"):
                continue
            tool_name = step.get("tool_name")
            result = step.get("response", {}).get("result", {})
            if tool_name == "open_application":
                app_name = str(result.get("opened") or result.get("path") or "")
                if app_name:
                    favorite_apps.append(app_name)
                    lower_app = app_name.lower()
                    if any(browser in lower_app for browser in ("chrome", "edge", "firefox", "brave", "opera")):
                        preferred_browser = app_name
                    if any(editor in lower_app for editor in ("code", "vscode", "pycharm", "notepad++", "notepad")):
                        preferred_editor = app_name
                    if any(term in lower_app for term in ("powershell", "cmd", "terminal", "wt", "bash")):
                        preferred_terminal = app_name
            if tool_name in {"move_path", "copy_path", "create_folder", "write_file"}:
                destination = result.get("destination") or result.get("path")
                if destination:
                    common_folders.append(os.path.dirname(destination) if os.path.isfile(destination) else destination)

        updates: Dict[str, Any] = {}
        if favorite_apps:
            updates["favorite_apps"] = favorite_apps
        if common_folders:
            updates["common_folders"] = common_folders
        if preferred_browser:
            updates["preferred_browser"] = preferred_browser
        if preferred_editor:
            updates["preferred_editor"] = preferred_editor
        if preferred_terminal:
            updates["preferred_terminal"] = preferred_terminal
        if plan.workflow_name:
            updates["named_routines"] = [plan.workflow_name]
        if updates:
            self.memory.update_user_profile(user_id, **updates)

        app_names = [step.get("response", {}).get("result", {}).get("opened") for step in completed_steps if step.get("tool_name") == "open_application"]
        self.memory.learn_from_behavior(
            user_id,
            {
                "task_type": "desktop",
                "skills_used": [step.get("tool_name") for step in completed_steps if step.get("tool_name")],
                "actions_performed": {"app": next((name for name in app_names if name), "")},
                "app_name": next((name for name in app_names if name), ""),
                "destination_folder": common_folders[0] if common_folders else "",
            },
        )

    def _extract_search_query(self, user_message: str) -> str:
        quoted = re.findall(r'"([^"]+)"', user_message)
        if quoted:
            return quoted[0]
        match = re.search(r"search(?: for)?\s+(.+)", user_message, re.IGNORECASE)
        return match.group(1).strip() if match else user_message.strip()

    def _extract_filename_hint(self, user_message: str) -> str:
        quoted = re.findall(r'"([^"]+)"', user_message)
        if quoted:
            return quoted[0]
        match = re.search(r"([A-Za-z0-9_\-]+\.[A-Za-z0-9]+)", user_message)
        if match:
            return match.group(1)
        tokens = re.findall(r"[A-Za-z0-9_\-.]+", user_message)
        return " ".join(tokens[:4]).strip()

    def _extract_destination(self, user_message: str, profile: Dict[str, Any]) -> str:
        quoted = re.findall(r'"([^"]+)"', user_message)
        if len(quoted) >= 2:
            return quoted[-1]
        match = re.search(r"\b(?:to|into|in)\s+([A-Za-z]:\\[^,\n]+|~[/\\][^,\n]+)", user_message)
        if match:
            return os.path.expandvars(os.path.expanduser(match.group(1).strip()))
        common_folders = profile.get("common_folders") or []
        return common_folders[0] if common_folders else os.path.join(os.path.expanduser("~"), "Downloads")

    def _extract_location_hint(self, user_message: str) -> Optional[List[str]]:
        """Extract drive letters or well-known folder references as search roots."""
        msg_lower = user_message.lower()

        drive_patterns = [
            r"\b(?:in|on|from|at)\s+(?:the\s+)?([a-z])\s+drive\b",
            r"\b(?:in|on|from|at)\s+(?:the\s+)?drive\s+([a-z])\b",
            r"\b(?:in|on|from|at)\s+([a-z]):[\\\/]",
            r"\b([a-z]):\s*[\\\/]",
        ]
        for pattern in drive_patterns:
            match = re.search(pattern, msg_lower)
            if match:
                drive_letter = match.group(1).upper()
                drive_root = f"{drive_letter}:\\"
                if os.path.exists(drive_root):
                    return [drive_root]

        home = os.path.expanduser("~")
        well_known = {
            "documents": os.path.join(home, "Documents"),
            "downloads": os.path.join(home, "Downloads"),
            "desktop": os.path.join(home, "Desktop"),
            "pictures": os.path.join(home, "Pictures"),
            "music": os.path.join(home, "Music"),
            "videos": os.path.join(home, "Videos"),
        }
        for keyword, path in well_known.items():
            if re.search(rf"\b(?:in|on|from|at)\s+(?:the\s+|my\s+)?{keyword}\b", msg_lower):
                if os.path.isdir(path):
                    return [path]
        return None

    def _extract_file_read_request(self, user_message: str) -> Optional[Dict[str, str]]:
        """Detect when the user wants to read/view file contents."""
        msg_lower = user_message.lower()
        read_triggers = (
            "read", "show me", "display", "view", "get the content",
            "fetch data", "what's in", "what is in", "open and read",
            "show the content", "show content", "print", "cat ",
        )
        if not any(trigger in msg_lower for trigger in read_triggers):
            return None

        quoted = re.findall(r'"([^"]+)"', user_message)
        if quoted:
            file_candidate = next(
                (q for q in quoted if re.search(r"\.[A-Za-z0-9]{1,8}$", q)), ""
            )
            if file_candidate:
                return {"target": file_candidate}

        patterns = [
            r"(?:read|show|display|view|get|fetch|cat)\s+(?:the\s+)?(?:contents?\s+of\s+)?(?:the\s+)?(?:file\s+)?\"?([^\s\"]+\.[A-Za-z0-9]{1,8})\"?",
            r"(?:what(?:'s| is)\s+(?:in|inside)\s+(?:the\s+)?(?:file\s+)?)\"?([^\s\"]+\.[A-Za-z0-9]{1,8})\"?",
            r"(?:read|show|display|get|fetch|view)\s+(?:data|content|text|info)\s+from\s+(?:the\s+)?(?:file\s+)?\"?([^\s\"]+?)\"?(?:\s+(?:in|on|from|at)\s+|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if match:
                target = match.group(1).strip().strip("\"'")
                if target and len(target) > 1:
                    return {"target": target}

        name_pattern = re.search(
            r"(?:read|show|display|view|get|fetch)\s+(?:the\s+)?(?:file\s+)?(.+?)(?:\s+file)?(?:\s+(?:in|on|from|at)\s+|$)",
            user_message, re.IGNORECASE,
        )
        if name_pattern:
            target = self._sanitize_folder_phrase(name_pattern.group(1))
            if target and len(target) > 1:
                return {"target": target}
        return None

    def _extract_scoped_folder_search(self, user_message: str) -> Optional[Dict[str, str]]:
        patterns = [
            r"(?:open|launch|start)\s+(?:the\s+)?(.+?)\s+folder\s+and\s+(?:search|find|locate|look\s+for)\s+(?:the\s+)?(.+?)\s+folder(?:\s+(?:inside|in)\s+(?:that|it|there))?",
            r"(?:open|launch|start)\s+(?:the\s+)?(.+?)\s+folder.*?(?:search|find|locate|look\s+for)\s+(?:the\s+)?(.+?)\s+folder\s+(?:in|inside)\s+(?:that|it|there)",
        ]
        for pattern in patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if not match:
                continue
            outer_target = self._sanitize_folder_phrase(match.group(1))
            inner_target = self._sanitize_folder_phrase(match.group(2))
            if outer_target and inner_target:
                return {"outer": outer_target, "inner": inner_target}
        return None

    def _extract_file_write_request(self, user_message: str) -> Optional[Dict[str, str]]:
        quoted = re.findall(r'"([^"]+)"', user_message)
        content = ""
        file_name = ""
        directory = ""

        pattern = re.search(
            r"(?:create|make|write|save)\s+(?:a\s+)?file(?:\s+named)?\s+([^\n]+?)\s+(?:in|inside|under|at)\s+([^\n]+?)(?:\s+with\s+content\s+(.+))?$",
            user_message,
            re.IGNORECASE,
        )
        if pattern:
            file_name = pattern.group(1).strip().strip("\"'")
            directory = pattern.group(2).strip().strip("\"'")
            content = (pattern.group(3) or "").strip().strip("\"'")

        if quoted:
            file_candidate = next((item for item in quoted if re.search(r"\.[A-Za-z0-9]{1,8}$", item)), "")
            if file_candidate and not file_name:
                file_name = file_candidate
            if len(quoted) >= 2 and not directory:
                directory = quoted[1] if quoted[1] != file_name else ""
            if len(quoted) >= 3 and not content:
                content = quoted[-1]

        if not file_name or not directory:
            return None

        file_name = os.path.basename(file_name)
        directory = self._sanitize_folder_phrase(directory)
        return {"file_name": file_name, "directory": directory, "content": content}

    def _sanitize_folder_phrase(self, value: str) -> str:
        candidate = (value or "").strip().strip('"').strip("'").strip()
        candidate = re.sub(r"^(my|the)\s+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+(please|for me)$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+(in|inside)\s+(that|it|there)$", "", candidate, flags=re.IGNORECASE)
        return candidate.strip()

    def _join_path(self, base_path: str, child_name: str) -> str:
        if re.match(r"^[A-Za-z]:\\", base_path) or "\\" in base_path:
            return ntpath.normpath(ntpath.join(base_path, child_name))
        return os.path.normpath(os.path.join(base_path, child_name))

    def _extract_open_folder_target(self, user_message: str) -> str:
        patterns = [
            r"(?:open|launch|start)\s+(?:the\s+)?(.+?)\s+(?:folder|directory)\b",
            r"(?:open|launch|start)\s+(?:folder|directory)\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if not match:
                continue
            candidate = self._sanitize_folder_phrase(match.group(1))
            if candidate:
                return candidate
        return ""

    def _looks_like_path(self, value: str) -> bool:
        return bool(re.search(r"[A-Za-z]:\\|[~/\\\\/]", value))

    def _serialize_completed_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Strip rich runtime objects before returning desktop artifacts."""
        return {
            key: jsonable_encoder(value)
            for key, value in step.items()
            if key != "trace_events"
        }


desktop_execution_service = DesktopExecutionService()
