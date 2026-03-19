"""
Reusable workflow library for high-confidence assistant routines.

These workflows give the planner deterministic, user-personalized defaults for
common tasks so the model does not need to improvise the entire flow.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from app.agents.orchestration_models import (
    PlanStep,
    RecoveryPolicy,
    VerificationRequirement,
)
from app.services.enhanced_memory_service import enhanced_memory_service


class WorkflowLibraryService:
    """Match built-in or saved workflows and emit explicit execution steps."""

    def __init__(self) -> None:
        self.memory = enhanced_memory_service

    def _profile_defaults(self, user_id: str) -> Dict[str, Any]:
        profile = self.memory.get_user_profile(user_id)
        workspace = os.getenv("WORKSPACE_PATH", os.path.abspath(os.path.join(".", "workspace")))
        return {
            "browser": profile.get("preferred_browser") or "chrome",
            "editor": profile.get("preferred_editor") or "code",
            "terminal": profile.get("preferred_terminal") or "powershell",
            "workspace_path": workspace,
            "profile": profile,
        }

    def _make_step(
        self,
        *,
        index: int,
        agent_type: str,
        goal: str,
        message: str,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
        approval_level: str = "none",
        safety_level: str = "safe",
        success_criteria: str = "",
        verification_method: str = "none",
        verification_target: str = "",
        verification_expected: Optional[Dict[str, Any]] = None,
        verification_description: str = "",
        recovery_strategy: str = "",
        alternate_tools: Optional[List[str]] = None,
        retry_budget: int = 0,
        depends_on: Optional[List[str]] = None,
    ) -> PlanStep:
        return PlanStep(
            step_id=f"step-{index}",
            agent_type=agent_type,  # type: ignore[arg-type]
            goal=goal,
            inputs={
                "message": message,
                "arguments": arguments or {},
            },
            depends_on=depends_on or [],
            approval_level=approval_level,  # type: ignore[arg-type]
            safety_level=safety_level,  # type: ignore[arg-type]
            tool_name=tool_name,
            success_criteria=success_criteria,
            fallback_strategy=recovery_strategy,
            verification=VerificationRequirement(
                method=verification_method,  # type: ignore[arg-type]
                target=verification_target,
                expected=verification_expected or {},
                description=verification_description,
            ),
            recovery=RecoveryPolicy(
                strategy=recovery_strategy,
                alternate_tools=alternate_tools or [],
                max_retries=retry_budget,
            ),
            retry_budget=retry_budget,
        )

    def _extract_search_query(self, user_message: str) -> str:
        quoted = re.findall(r'"([^"]+)"', user_message)
        if quoted:
            return quoted[0]
        match = re.search(r"search(?: for)?\s+(.+)", user_message, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return user_message.strip()

    def _extract_destination(self, user_message: str, defaults: Dict[str, Any]) -> str:
        quoted = re.findall(r'"([^"]+)"', user_message)
        if len(quoted) >= 2:
            return quoted[-1]
        match = re.search(r"\b(?:to|into|in)\s+([A-Za-z]:\\[^,\n]+|~[/\\][^,\n]+)", user_message)
        if match:
            return match.group(1).strip()
        profile = defaults.get("profile", {})
        common_folders = profile.get("common_folders") or []
        if common_folders:
            return common_folders[0]
        return os.path.join(os.path.expanduser("~"), "Downloads")

    def _open_coding_setup(self, user_message: str, user_id: str) -> Dict[str, Any]:
        defaults = self._profile_defaults(user_id)
        editor = defaults["editor"]
        terminal = defaults["terminal"]
        browser = defaults["browser"]
        workspace = defaults["workspace_path"]

        steps = [
            self._make_step(
                index=1,
                agent_type="desktop",
                goal="Open the preferred coding editor.",
                message=f"Open {editor}.",
                tool_name="open_application",
                arguments={"name": editor},
                success_criteria="The editor process or window is visible.",
                verification_method="composite",
                verification_target=editor,
                verification_expected={"process_or_window": True},
                verification_description="Confirm the preferred editor actually launched.",
                recovery_strategy="Retry with common editor aliases if the preferred editor fails to launch.",
                alternate_tools=["open_application", "list_windows", "is_app_running"],
                retry_budget=1,
            ),
            self._make_step(
                index=2,
                agent_type="desktop",
                goal="Open the preferred terminal.",
                message=f"Open {terminal}.",
                tool_name="open_application",
                arguments={"name": terminal},
                success_criteria="The terminal process or window is visible.",
                verification_method="composite",
                verification_target=terminal,
                verification_expected={"process_or_window": True},
                verification_description="Confirm the preferred terminal launched.",
                recovery_strategy="Retry with terminal fallbacks such as wt, PowerShell, or cmd.",
                alternate_tools=["open_application", "list_windows", "is_app_running"],
                retry_budget=1,
                depends_on=["step-1"],
            ),
            self._make_step(
                index=3,
                agent_type="desktop",
                goal="Open the preferred browser for coding references.",
                message=f"Open {browser}.",
                tool_name="open_application",
                arguments={"name": browser},
                success_criteria="The browser process or window is visible.",
                verification_method="browser",
                verification_target=browser,
                verification_expected={"process_or_window": True},
                verification_description="Confirm the preferred browser launched.",
                recovery_strategy="Retry with browser fallbacks such as Chrome, Edge, or Firefox.",
                alternate_tools=["open_application", "list_windows", "is_app_running"],
                retry_budget=1,
                depends_on=["step-2"],
            ),
            self._make_step(
                index=4,
                agent_type="desktop",
                goal="Open the coding workspace folder for quick navigation.",
                message=f"Open the folder {workspace}.",
                tool_name="open_application",
                arguments={"name": workspace},
                success_criteria="The workspace folder exists and opens in Explorer.",
                verification_method="file",
                verification_target=workspace,
                verification_expected={"exists": True},
                verification_description="Confirm the workspace path exists.",
                recovery_strategy="If the configured workspace path is unavailable, search for the workspace folder and open the best match.",
                alternate_tools=["search_system", "open_application"],
                retry_budget=1,
                depends_on=["step-2"],
            ),
        ]

        return {
            "workflow_key": "open_coding_setup",
            "workflow_name": "Open Coding Setup",
            "workflow_source": "builtin",
            "summary": "Open the user's personalized coding environment with their editor, terminal, browser, and workspace.",
            "steps": steps,
            "metadata": {"workspace_path": workspace},
        }

    def _open_browser_search(self, user_message: str, user_id: str) -> Dict[str, Any]:
        defaults = self._profile_defaults(user_id)
        browser = defaults["browser"]
        query = self._extract_search_query(user_message)

        steps = [
            self._make_step(
                index=1,
                agent_type="desktop",
                goal="Open the preferred browser.",
                message=f"Open {browser}.",
                tool_name="open_application",
                arguments={"name": browser},
                success_criteria="The browser is open and ready for input.",
                verification_method="browser",
                verification_target=browser,
                verification_expected={"process_or_window": True},
                verification_description="Confirm the browser opened successfully.",
                recovery_strategy="Retry with browser fallbacks if the preferred browser does not open.",
                alternate_tools=["open_application", "list_windows", "is_app_running"],
                retry_budget=1,
            ),
            self._make_step(
                index=2,
                agent_type="desktop",
                goal="Search the requested query in the browser.",
                message=f"Type {query} in the browser and press Enter.",
                tool_name="type_text",
                arguments={"text": query},
                success_criteria="The query is entered into the browser UI.",
                verification_method="ocr",
                verification_target=query,
                verification_expected={"contains_any_tokens": query.split()[:3]},
                verification_description="Use OCR or the browser title to confirm the query is visible.",
                recovery_strategy="If typing fails, refocus the browser window and retry the search.",
                alternate_tools=["focus_window", "type_text", "press_key", "read_screen_text"],
                retry_budget=1,
                depends_on=["step-1"],
            ),
            self._make_step(
                index=3,
                agent_type="desktop",
                goal="Submit the browser search.",
                message="Press Enter in the browser.",
                tool_name="press_key",
                arguments={"key": "enter"},
                success_criteria="The browser begins loading or the active window title changes.",
                verification_method="browser",
                verification_target=query,
                verification_expected={"title_or_ocr_contains_any_tokens": query.split()[:3]},
                verification_description="Confirm the browser navigated to a search results page.",
                recovery_strategy="Refocus the browser and retry Enter, then fall back to browser search recovery if needed.",
                alternate_tools=["focus_window", "press_key", "read_screen_text", "get_active_window"],
                retry_budget=1,
                depends_on=["step-2"],
            ),
        ]

        return {
            "workflow_key": "open_browser_search",
            "workflow_name": "Open Browser And Search",
            "workflow_source": "builtin",
            "summary": "Open the user's preferred browser and run a verified search query.",
            "steps": steps,
            "metadata": {"query": query, "browser": browser},
        }

    def _download_and_move(self, user_message: str, user_id: str) -> Dict[str, Any]:
        defaults = self._profile_defaults(user_id)
        destination = self._extract_destination(user_message, defaults)
        steps = [
            self._make_step(
                index=1,
                agent_type="web_autonomous",
                goal="Download the requested file through the browser.",
                message=user_message,
                success_criteria="The requested file is downloaded or the browser reaches the correct download page.",
                verification_method="browser",
                verification_target="download",
                verification_description="The autonomous web agent should confirm a download attempt.",
                recovery_strategy="If direct download fails, open the page and extract the best next action.",
                retry_budget=1,
            ),
            self._make_step(
                index=2,
                agent_type="desktop",
                goal="Locate the downloaded file and move it to the destination folder.",
                message=f"Find the downloaded file from this task and move it to {destination}.",
                tool_name="",
                arguments={},
                success_criteria="The downloaded file is found and then moved into the requested destination folder.",
                verification_method="file",
                verification_target=destination,
                verification_expected={"exists": True},
                verification_description="Confirm the destination folder exists and a matching file lands there.",
                recovery_strategy="Broaden the search in Downloads and create the destination folder if needed before retrying the move.",
                alternate_tools=["search_system", "create_folder", "move_path", "get_file_info"],
                retry_budget=1,
                depends_on=["step-1"],
            ),
        ]
        return {
            "workflow_key": "download_file_and_move",
            "workflow_name": "Download File And Move It",
            "workflow_source": "builtin",
            "summary": "Download a file and verify that it is moved to the requested destination.",
            "steps": steps,
            "metadata": {"destination": destination},
        }

    def _send_report_mail(self, user_message: str, user_id: str) -> Dict[str, Any]:
        steps = [
            self._make_step(
                index=1,
                agent_type="email",
                goal="Draft the requested report email without sending it.",
                message=f"Create a draft report email from this request but do not send it yet: {user_message}",
                success_criteria="A Gmail draft is created with a subject, recipient, and report body.",
                verification_method="none",
                recovery_strategy="Ask for missing recipient or report details if drafting fails.",
            ),
            self._make_step(
                index=2,
                agent_type="email",
                goal="Send the drafted report email after explicit approval.",
                message="send it",
                approval_level="confirm",
                safety_level="confirm",
                success_criteria="The previously drafted email is sent successfully.",
                verification_method="none",
                recovery_strategy="Keep the draft and return the draft id if sending fails.",
                retry_budget=0,
                depends_on=["step-1"],
            ),
        ]
        return {
            "workflow_key": "send_report_mail",
            "workflow_name": "Send Report Mail",
            "workflow_source": "builtin",
            "summary": "Draft a report email automatically, then require approval before sending it.",
            "steps": steps,
            "metadata": {},
        }

    def match_workflow(self, user_message: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Return a built-in or saved workflow match for the user request."""
        message_lower = user_message.lower()

        if any(phrase in message_lower for phrase in ("coding setup", "developer setup", "coding environment", "dev setup")):
            return self._open_coding_setup(user_message, user_id)

        if "open browser and search" in message_lower or "search this in browser" in message_lower:
            return self._open_browser_search(user_message, user_id)

        if "download" in message_lower and "move" in message_lower:
            return self._download_and_move(user_message, user_id)

        if any(phrase in message_lower for phrase in ("send report mail", "send report email", "mail this report")):
            return self._send_report_mail(user_message, user_id)

        saved = self.memory.get_saved_workflows(user_id, limit=20)
        for workflow in saved:
            for trigger in workflow.get("triggers", []):
                if trigger and trigger.lower() in message_lower:
                    return {
                        "workflow_key": workflow["workflow_key"],
                        "workflow_name": workflow["workflow_name"],
                        "workflow_source": "saved",
                        "summary": workflow.get("description") or f"Run the saved routine {workflow['workflow_name']}.",
                        "steps": [],
                        "metadata": {
                            "saved_workflow": workflow,
                        },
                    }

        return None


workflow_library_service = WorkflowLibraryService()
