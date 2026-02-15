"""
Multi-Agent Orchestrator - FIXED VERSION
- Passes project_name to sandbox for workspace saving
- Correct install_command vs start_command separation
- Proper project_path handling
"""

import os
import sys
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from loguru import logger
import re

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from .multi_agent_state import AgentState
from .router_agent import router_agent
from .code_specialist_agent import code_specialist
from ..services.sandbox_services import sandbox_service


class MultiAgentOrchestrator:
    """Orchestrates multiple specialist agents with MULTI-FILE support"""

    def __init__(self):
        logger.info("✅ Multi-Agent Orchestrator initialized")

    # ============================================================
    # ROUTING
    # ============================================================

    async def _route_to_agent(
        self,
        state: AgentState,
        message_callback: Optional[Callable] = None
    ) -> AgentState:
        task_type = state.get("task_type", "general")

        if task_type == "coding":
            return await self._code_specialist_node(state, message_callback)
        elif task_type == "desktop":
            return self._desktop_specialist_node(state)
        else:
            return self._general_assistant_node(state)

    def _router_node(self, state: AgentState) -> AgentState:
        logger.info("🎯 Router: Classifying task...")
        decision = router_agent.classify_task(state["user_message"])

        state["task_type"] = decision["task_type"]
        state["confidence"] = decision["confidence"]
        state["agent_path"] = ["router"]

        logger.info(
            f"📍 Routed to: {decision['next_agent']} ({decision['task_type']})"
        )
        return state

    # ============================================================
    # CODE SPECIALIST
    # ============================================================

    async def _code_specialist_node(
        self,
        state: AgentState,
        message_callback: Optional[Callable] = None
    ) -> AgentState:
        logger.info("💻 Code Specialist: Processing...")
        state["agent_path"] += ["code_specialist"]
        state["start_time"] = datetime.now().isoformat()

        max_iterations = state.get("max_iterations", 5)
        final_success = False

        # FIX: Extract project name from user message
        project_name = self._extract_project_name(state["user_message"])

        for iteration in range(1, max_iterations + 1):
            state["iteration"] = iteration
            logger.info(f"🔄 Iteration {iteration}/{max_iterations}")

            if message_callback:
                await message_callback({
                    "type": "iteration",
                    "message": f"🔄 Iteration {iteration}/{max_iterations}",
                    "iteration": iteration,
                    "total": max_iterations
                })

            # Generate code
            gen_result = await self._generate_code(state, message_callback)
            if not gen_result.get("success"):
                state["error_message"] = gen_result.get("error", "Code generation failed")
                break

            # Execute code
            exec_result = await self._execute_code(state, project_name)  # FIX: Pass project_name
            
            # Store result
            state["execution_results"].append({
                "iteration": iteration,
                "success": exec_result.get("success", False),
                "stdout": exec_result.get("stdout", ""),
                "stderr": exec_result.get("stderr", ""),
                "timestamp": datetime.now().isoformat()
            })

            # FIX: Save project_path from execution result
            if exec_result.get("project_path"):
                state["project_path"] = exec_result["project_path"]

            # Check if successful
            if exec_result.get("success"):
                final_success = True
                
                if message_callback:
                    msg = "✅ Code executed successfully!"
                    if exec_result.get("server_url"):
                        msg += f"\n🌐 Live preview: {exec_result['server_url']}"
                    if exec_result.get("project_path"):
                        msg += f"\n📁 Saved to: {exec_result['project_path']}"
                    
                    await message_callback({
                        "type": "success",
                        "message": msg
                    })
                break
            else:
                if iteration < max_iterations:
                    if message_callback:
                        await message_callback({
                            "type": "fixing",
                            "message": f"⚠️ Error found, attempting fix {iteration+1}...",
                            "error": exec_result.get("stderr", "Unknown error")
                        })

        # Finalize state
        state["success"] = final_success
        state["total_iterations"] = iteration
        state["end_time"] = datetime.now().isoformat()

        # Set final output
        if final_success:
            files = state.get("files") or {}
            file_count = len(files)
            project_type = state.get("project_type", "project")
            
            output_msg = f"✅ Successfully created {project_type} project with {file_count} files"
            
            if state.get("server_url"):
                output_msg += f"\n\n🌐 Live Preview: {state['server_url']}"
            
            if state.get("project_path"):
                output_msg += f"\n📁 Project saved to: {state['project_path']}"
            
            state["final_output"] = output_msg
        else:
            state["final_output"] = f"❌ Failed after {iteration} iterations"
            if state.get("error_message"):
                state["final_output"] += f"\nError: {state['error_message']}"

        return state

    def _extract_project_name(self, user_message: str) -> str:
        """
        Extract project name from user message
        Examples:
        "create a react todo app" -> "todo-app"
        "build a flask API" -> "flask-api"
        "make calculator in python" -> "calculator"
        """
        # Convert to lowercase
        msg = user_message.lower()
        
        # Remove common words
        remove_words = ['create', 'build', 'make', 'a', 'an', 'the', 'app', 'application', 'project']
        for word in remove_words:
            msg = msg.replace(f' {word} ', ' ')
            msg = msg.replace(f'{word} ', '')
            msg = msg.replace(f' {word}', '')
        
        # Clean and get first few words
        words = re.findall(r'\w+', msg)
        
        if words:
            # Take first 2-3 meaningful words
            name_parts = words[:3]
            project_name = '-'.join(name_parts)
            return project_name[:30]  # Limit length
        
        return "my-project"

    async def _generate_code(
        self,
        state: Dict,
        callback=None
    ) -> Dict:
        """Generate code using Code Specialist"""
        iteration = state["iteration"]
        description = state["user_message"]

        if callback:
            if iteration == 1:
                await callback({
                    "type": "generating",
                    "message": "🎨 Generating complete project structure..."
                })
            else:
                await callback({
                    "type": "fixing",
                    "message": f"🔧 Fixing errors (iteration {iteration})..."
                })

        previous_error = None
        if iteration > 1 and state["execution_results"]:
            last_result = state["execution_results"][-1]
            previous_error = last_result.get("stderr", "")

        result = await code_specialist.generate_code(
            description=description,
            context=None,
            iteration=iteration,
            previous_error=previous_error
        )

        if not result["success"]:
            return result

        # Update state with MULTI-FILE support
        state["files"] = result["files"]
        state["project_structure"] = result["structure"]
        state["main_file"] = result["main_file"]
        state["project_type"] = result["project_type"]
        state["language"] = result["language"]
        state["is_server"] = result["is_server"]
        state["start_command"] = result["start_command"]
        state["install_command"] = result.get("install_command")  # FIX: Save install command
        state["server_port"] = result.get("port")

        # Legacy
        state["generated_code"] = result.get("raw_output", "")

        if callback:
            file_count = len(result["files"])
            await callback({
                "type": "generation_complete",
                "message": f"✅ Generated {file_count} files for {result['project_type']} project"
            })

        return result

    async def _execute_code(self, state: Dict, project_name: str = "my-project") -> Dict:
        """
        Execute code with MULTI-FILE support
        
        FIX: Passes project_name for workspace saving
        FIX: Separates install_command from start_command
        """
        files = state.get("files") or state.get("final_files")
        single_code = state.get("generated_code") or state.get("final_code")

        if files:
            # Multi-file project execution
            project_type = state.get("project_type", "python")
            install_cmd = state.get("install_command")  # FIX: Use install_command
            start_cmd = state.get("start_command")
            port = state.get("server_port")

            logger.info(f"📦 Project: {project_name}")
            logger.info(f"📦 Install command: {install_cmd}")
            logger.info(f"🚀 Start command: {start_cmd}")

            result = await sandbox_service.execute_project(
                files=files,
                project_type=project_type,
                project_name=project_name,  # FIX: Pass project name
                install_command=install_cmd,  # FIX: Separate install command
                start_command=start_cmd,
                port=port
            )

            # Update state with server info and project path
            if result.get("server_started"):
                state["server_running"] = True
                state["server_url"] = result["server_url"]
                state["server_port"] = result["server_port"]
            
            if result.get("project_path"):
                state["project_path"] = result["project_path"]

            return result

        elif single_code:
            language = state.get("language", "python")
            return await sandbox_service.execute_python(single_code)

        return {
            "success": False,
            "error": "No code to execute",
            "stdout": "",
            "stderr": "No code provided",
            "exit_code": 1
        }

    # ============================================================
    # OTHER SPECIALISTS
    # ============================================================

    def _desktop_specialist_node(self, state: AgentState) -> AgentState:
        logger.info("🖥️ Desktop Specialist: Processing...")
        state["agent_path"] += ["desktop_specialist"]
        state["success"] = True
        state["final_output"] = "Desktop task (using existing skills)"
        state["end_time"] = datetime.now().isoformat()
        return state

    def _general_assistant_node(self, state: AgentState) -> AgentState:
        logger.info("💬 General Assistant: Processing...")
        state["agent_path"] += ["general_assistant"]
        state["success"] = True
        state["final_output"] = "General query (using existing LLM)"
        state["end_time"] = datetime.now().isoformat()
        return state

    # ============================================================
    # MAIN PROCESS
    # ============================================================

    async def process(
        self,
        user_message: str,
        conversation_id: str = None,
        max_iterations: int = 5,
        message_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:

        initial_state: AgentState = {
            "user_message": user_message,
            "conversation_id": conversation_id or f"conv_{datetime.now().timestamp()}",
            "task_type": None,
            "confidence": None,
            "iteration": 1,
            "max_iterations": max_iterations,
            "execution_results": [],
            "agent_path": [],
            "language": None,
            "project_path": None,  # FIX: Initialize
            "start_time": None,
            "end_time": None
        }

        logger.info(f"🚀 Processing: '{user_message[:50]}...'")

        state = self._router_node(initial_state)
        state = await self._route_to_agent(state, message_callback)

        final_success = state.get("success", False)

        # FINAL RESPONSE WITH ALL DATA
        return {
            "success": final_success,
            "task_type": state["task_type"],
            "confidence": state["confidence"],
            "output": state.get("final_output", ""),

            # Legacy single file
            "code": state.get("generated_code"),
            "file_path": state.get("file_path"),

            # Multi-file (NEW)
            "files": state.get("files"),
            "project_structure": state.get("project_structure"),
            "main_file": state.get("main_file"),

            # Project info
            "project_type": state.get("project_type"),
            "language": state.get("language"),
            "project_path": state.get("project_path"),  # FIX: Include project path

            # Server info
            "server_running": state.get("server_running", False),
            "server_url": state.get("server_url"),
            "server_port": state.get("server_port"),

            # Metadata
            "metadata": {
                "total_iterations": state.get("total_iterations", 0),
                "execution_results": state["execution_results"],
                "start_time": state.get("start_time"),
                "end_time": state.get("end_time")
            },
            "agent_path": state["agent_path"],
            "error": state.get("error_message")
        }


# Global orchestrator instance
orchestrator = MultiAgentOrchestrator()