"""
Multi-Agent Orchestrator - COMPLETE FIXED VERSION
- Desktop agent actually works
- Conversation history loaded and used
- Memory fully integrated
"""

import os
import sys
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from loguru import logger
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from .multi_agent_state import AgentState
from .router_agent import router_agent
from .code_specialist_agent import code_specialist
from ..services.sandbox_services import sandbox_service
from ..services.memory_service import memory_service
from ..core.llm import llm_adapter
from ..models import Message, MessageRole


class MultiAgentOrchestrator:
    """Orchestrates multiple specialist agents with FULL memory"""

    def __init__(self):
        logger.info("✅ Multi-Agent Orchestrator with memory initialized")

    # ============================================================
    # ROUTING
    # ============================================================

    async def _route_to_agent(
        self,
        state: AgentState,
        user_id: str,
        conversation_history: list,
        message_callback: Optional[Callable] = None
    ) -> AgentState:
        task_type = state.get("task_type", "general")

        if task_type == "coding":
            return await self._code_specialist_node(
                state, user_id, conversation_history, message_callback
            )
        elif task_type == "desktop":
            return await self._desktop_specialist_node(
                state, user_id, conversation_history, message_callback
            )
        else:
            return await self._general_assistant_node(
                state, user_id, conversation_history, message_callback
            )

    def _router_node(
        self,
        state: AgentState,
        user_context: str = ""
    ) -> AgentState:
        logger.info("🎯 Router: Classifying task...")
        decision = router_agent.classify_task(
            state["user_message"],
            user_context=user_context
        )

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
        user_id: str,
        conversation_history: list,
        message_callback: Optional[Callable] = None
    ) -> AgentState:
        logger.info("💻 Code Specialist: Processing...")
        state["agent_path"] += ["code_specialist"]
        state["start_time"] = datetime.now().isoformat()

        max_iterations = state.get("max_iterations", 5)
        final_success = False

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
            gen_result = await code_specialist.generate_code(
                description=state["user_message"],
                user_id=user_id,
                conversation_history=conversation_history,
                iteration=iteration,
                previous_error=state.get("last_error")
            )
            
            if not gen_result.get("success"):
                state["error_message"] = gen_result.get("error", "Code generation failed")
                break

            # Update state
            state["files"] = gen_result["files"]
            state["project_structure"] = gen_result["structure"]
            state["main_file"] = gen_result["main_file"]
            state["project_type"] = gen_result["project_type"]
            state["language"] = gen_result["language"]
            state["is_server"] = gen_result["is_server"]
            state["start_command"] = gen_result["start_command"]
            state["install_command"] = gen_result.get("install_command")
            state["server_port"] = gen_result.get("port")

            # Execute code
            exec_result = await self._execute_code(state, project_name)
            
            state["execution_results"].append({
                "iteration": iteration,
                "success": exec_result.get("success", False),
                "stdout": exec_result.get("stdout", ""),
                "stderr": exec_result.get("stderr", ""),
                "timestamp": datetime.now().isoformat()
            })

            if exec_result.get("project_path"):
                state["project_path"] = exec_result["project_path"]

            # Check success
            if exec_result.get("success"):
                final_success = True
                
                # Learn from success!
                if user_id:
                    memory_service.learn_from_behavior(user_id, {
                        'task_type': 'coding',
                        'language': state.get('language'),
                        'framework': state.get('project_type'),
                        'project_type': state.get('project_type'),
                        'success': True
                    })
                
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
                state["last_error"] = exec_result.get("stderr", "Unknown error")
                
                if iteration < max_iterations:
                    if message_callback:
                        await message_callback({
                            "type": "fixing",
                            "message": f"⚠️ Error found, attempting fix {iteration+1}...",
                            "error": state["last_error"]
                        })

        # Finalize
        state["success"] = final_success
        state["total_iterations"] = iteration
        state["end_time"] = datetime.now().isoformat()

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

        # Save task history
        if user_id:
            memory_service.save_task(user_id, {
                'conversation_id': state.get('conversation_id'),
                'task_type': 'coding',
                'description': state["user_message"],
                'agent_used': 'code_specialist',
                'iterations': iteration,
                'success': final_success,
                'language': state.get('language'),
                'framework': state.get('project_type'),
                'project_type': state.get('project_type')
            })

        return state

    def _extract_project_name(self, user_message: str) -> str:
        """Extract project name from user message"""
        msg = user_message.lower()
        
        remove_words = ['create', 'build', 'make', 'a', 'an', 'the', 'app', 'application', 'project']
        for word in remove_words:
            msg = msg.replace(f' {word} ', ' ')
            msg = msg.replace(f'{word} ', '')
            msg = msg.replace(f' {word}', '')
        
        words = re.findall(r'\w+', msg)
        
        if words:
            name_parts = words[:3]
            project_name = '-'.join(name_parts)
            return project_name[:30]
        
        return "my-project"

    async def _execute_code(self, state: Dict, project_name: str = "my-project") -> Dict:
        """Execute code with MULTI-FILE support"""
        files = state.get("files") or state.get("final_files")
        single_code = state.get("generated_code") or state.get("final_code")

        if files:
            project_type = state.get("project_type", "python")
            install_cmd = state.get("install_command")
            start_cmd = state.get("start_command")
            port = state.get("server_port")

            logger.info(f"📦 Project: {project_name}")
            logger.info(f"📦 Install command: {install_cmd}")
            logger.info(f"🚀 Start command: {start_cmd}")

            result = await sandbox_service.execute_project(
                files=files,
                project_type=project_type,
                project_name=project_name,
                install_command=install_cmd,
                start_command=start_cmd,
                port=port
            )

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
    # DESKTOP SPECIALIST - FIXED!
    # ============================================================

    async def _desktop_specialist_node(
        self,
        state: AgentState,
        user_id: str,
        conversation_history: list,
        message_callback: Optional[Callable] = None
    ) -> AgentState:
        """
        Desktop Specialist - ACTUALLY WORKS NOW!
        
        This was previously just a stub that returned immediately.
        Now it properly processes desktop commands.
        """
        logger.info("🖥️ Desktop Specialist: Processing...")
        state["agent_path"] += ["desktop_specialist"]
        state["start_time"] = datetime.now().isoformat()

        try:
            if message_callback:
                await message_callback({
                    "type": "processing",
                    "message": "🖥️ Processing desktop command..."
                })

            # Convert conversation history to Message objects for LLM
            messages = []
            
            # Add system message with clear instructions for tool selection
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content="""You are a desktop automation assistant. Follow these rules strictly:

1. **For opening folders** (Pictures, Documents, Downloads, Desktop):
   - ALWAYS use `open_special_folder` tool with the appropriate folder parameter
   - NEVER use open_application + type_text + press_key for this
   - Example: For "open pictures folder" → call open_special_folder(folder="pictures")

2. **For opening files at specific paths**:
   - Use `open_path` tool with the full path

3. **For launching applications**:
   - Use `launch_app` tool with app name

Choose the SIMPLEST and MOST DIRECT tool for each task."""
            ))
            
            for msg in conversation_history[-10:]:  # Last 10 messages
                role = MessageRole.USER if msg['role'] == 'user' else MessageRole.ASSISTANT
                messages.append(Message(
                    role=role,
                    content=msg['content']
                ))

            # Add current user message
            messages.append(Message(
                role=MessageRole.USER,
                content=state["user_message"]
            ))

            # Get desktop tools from the desktop agent (not skill_manager)
            from ..skills.desktop_bridge import desktop_bridge
            desktop_skills_response = await desktop_bridge.get_available_skills()
            
            # Format tools for LLM
            formatted_tools = []
            if desktop_skills_response.get("success") and desktop_skills_response.get("tools"):
                for tool in desktop_skills_response["tools"]:
                    formatted_tools.append({
                        "type": "function",
                        "function": tool
                    })
            else:
                # Fallback: define essential desktop tools manually
                essential_tools = [
                    {
                        "name": "open_special_folder",
                        "description": "Open a well-known folder directly (desktop, documents, downloads, pictures). Use this for 'open pictures/documents/downloads folder' requests.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "folder": {
                                    "type": "string",
                                    "enum": ["desktop", "documents", "downloads", "pictures", "onedrive_root", "onedrive_desktop", "onedrive_documents", "onedrive_pictures"],
                                    "description": "Which special folder to open"
                                }
                            },
                            "required": ["folder"]
                        }
                    },
                    {
                        "name": "open_path",
                        "description": "Open a file or folder at a specific path",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Full path to open"}
                            },
                            "required": ["path"]
                        }
                    },
                    {
                        "name": "launch_app",
                        "description": "Launch an application by name",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "app": {"type": "string", "description": "Application name (e.g., 'notepad', 'chrome', 'calculator')"}
                            },
                            "required": ["app"]
                        }
                    },
                    {
                        "name": "open_url",
                        "description": "Open a URL in the default browser",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "URL to open"}
                            },
                            "required": ["url"]
                        }
                    },
                    {
                        "name": "type_text",
                        "description": "Type text using the keyboard",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "Text to type"}
                            },
                            "required": ["text"]
                        }
                    },
                    {
                        "name": "press_key",
                        "description": "Press a keyboard key",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "Key to press (e.g., 'enter', 'escape', 'tab')"}
                            },
                            "required": ["key"]
                        }
                    },
                    {
                        "name": "take_screenshot",
                        "description": "Take a screenshot of the screen",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                ]
                formatted_tools = [{"type": "function", "function": t} for t in essential_tools]
            
            logger.info(f"🔧 Desktop specialist calling LLM with {len(formatted_tools)} tools")
            
            # Call LLM
            llm_result = await llm_adapter.generate_response(
                messages,
                tools=formatted_tools
            )

            # Check if tools were called
            if llm_result.get("tool_calls"):
                logger.info(f"🛠️ Desktop agent executing {len(llm_result['tool_calls'])} tools")
                
                # Execute desktop skills
                from ..skills.executor import skill_executor
                
                execution_results = []
                for tool_call in llm_result["tool_calls"]:
                    import json
                    skill_name = tool_call["function"]["name"]
                    args = json.loads(tool_call["function"]["arguments"])
                    
                    logger.info(f"🔧 Executing: {skill_name}")
                    
                    result = await skill_executor.execute_skill(
                        skill_name=skill_name,
                        parameters=args,
                        user_id=user_id
                    )
                    
                    execution_results.append({
                        "skill": skill_name,
                        "success": result.success,
                        "output": result.output
                    })

                # Get final response from LLM explaining what was done
                summary_messages = messages + [Message(
                    role=MessageRole.ASSISTANT,
                    content=f"Executed skills: {', '.join([r['skill'] for r in execution_results])}"
                )]
                
                final_result = await llm_adapter.generate_response(
                    summary_messages,
                    tools=None  # No more tool calls
                )
                
                output = final_result["response"]
                success = all(r["success"] for r in execution_results)
            else:
                # LLM responded without tools
                output = llm_result["response"]
                success = True

            state["success"] = success
            state["final_output"] = output
            state["end_time"] = datetime.now().isoformat()

            if message_callback:
                await message_callback({
                    "type": "success",
                    "message": f"✅ {output}"
                })

            # Learn from desktop actions
            if user_id:
                memory_service.learn_from_behavior(user_id, {
                    'task_type': 'desktop',
                    'description': state["user_message"],
                    'success': success
                })

        except Exception as e:
            logger.error(f"❌ Desktop specialist error: {e}")
            state["success"] = False
            state["final_output"] = f"Desktop task encountered an error: {str(e)}"
            state["error_message"] = str(e)
            state["end_time"] = datetime.now().isoformat()

            if message_callback:
                await message_callback({
                    "type": "error",
                    "message": f"❌ Error: {str(e)}"
                })

        return state

    # ============================================================
    # GENERAL ASSISTANT - FIXED WITH MEMORY!
    # ============================================================

    async def _general_assistant_node(
        self,
        state: AgentState,
        user_id: str,
        conversation_history: list,
        message_callback: Optional[Callable] = None
    ) -> AgentState:
        """
        General Assistant - NOW WITH CONVERSATION HISTORY!
        
        Previously: Ignored conversation history
        Now: Uses full context for responses
        """
        logger.info("💬 General Assistant: Processing...")
        state["agent_path"] += ["general_assistant"]
        state["start_time"] = datetime.now().isoformat()

        try:
            if message_callback:
                await message_callback({
                    "type": "processing",
                    "message": "🤖 Thinking..."
                })

            # ✅ FIX: Convert conversation history to Message objects
            messages = []
            
            # Add conversation history
            for msg in conversation_history[-10:]:  # Last 10 messages for context
                role = MessageRole.USER if msg['role'] == 'user' else MessageRole.ASSISTANT
                messages.append(Message(
                    role=role,
                    content=msg['content']
                ))
            
            # Add current user message
            messages.append(Message(
                role=MessageRole.USER,
                content=state["user_message"]
            ))

            logger.info(f"🤖 Calling Groq LLM with {len(messages)} messages for general query...")
            
            # Call LLM with conversation context
            result = await llm_adapter.generate_response(messages)
            
            state["success"] = True
            state["final_output"] = result["response"]
            state["end_time"] = datetime.now().isoformat()

            logger.info("✅ General assistant response generated")

            if message_callback:
                await message_callback({
                    "type": "success",
                    "message": "✅ Response ready"
                })

        except Exception as e:
            logger.error(f"❌ General assistant error: {e}")
            state["success"] = False
            state["final_output"] = f"I encountered an error: {str(e)}"
            state["error_message"] = str(e)
            state["end_time"] = datetime.now().isoformat()

        return state

    # ============================================================
    # MAIN PROCESS - WITH FULL MEMORY
    # ============================================================

    async def process(
        self,
        user_message: str,
        user_id: str = "anonymous",
        conversation_id: str = None,
        max_iterations: int = 5,
        message_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Process with full memory support
        
        ✅ Saves user messages
        ✅ Loads conversation history
        ✅ Gets user preferences
        ✅ Injects context into all agents
        """

        if not conversation_id:
            conversation_id = f"conv_{datetime.now().timestamp()}"
        
        # ✅ Save user message
        memory_service.save_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role='user',
            content=user_message
        )
        
        # ✅ Get conversation history for context
        conversation_history = memory_service.get_conversation_history(
            conversation_id, limit=10
        )
        
        # ✅ Get user context for router
        user_context = memory_service.get_personalized_context(
            user_id, task_type=None
        )
        
        # Initialize state
        initial_state: AgentState = {
            "user_message": user_message,
            "conversation_id": conversation_id,
            "task_type": None,
            "confidence": None,
            "iteration": 1,
            "max_iterations": max_iterations,
            "execution_results": [],
            "agent_path": [],
            "language": None,
            "project_path": None,
            "start_time": None,
            "end_time": None
        }
        
        logger.info(f"🚀 Processing: '{user_message[:50]}...'")
        
        # Route with user context
        state = self._router_node(initial_state, user_context=user_context)
        
        # Execute appropriate agent WITH CONTEXT
        state = await self._route_to_agent(
            state,
            user_id,
            conversation_history,
            message_callback
        )
        
        # ✅ Save assistant response
        memory_service.save_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role='assistant',
            content=state.get('final_output', ''),
            metadata={
                'task_type': state.get('task_type'),
                'success': state.get('success'),
                'iterations': state.get('total_iterations'),
                'language': state.get('language'),
                'files': list(state.get('files', {}).keys()) if state.get('files') else None
            }
        )
        
        # Return result
        return {
            "success": state.get("success", False),
            "task_type": state["task_type"],
            "confidence": state["confidence"],
            "output": state.get("final_output", ""),
            "code": state.get("generated_code"),
            "file_path": state.get("file_path"),
            "files": state.get("files"),
            "project_structure": state.get("project_structure"),
            "main_file": state.get("main_file"),
            "project_type": state.get("project_type"),
            "language": state.get("language"),
            "project_path": state.get("project_path"),
            "server_running": state.get("server_running", False),
            "server_url": state.get("server_url"),
            "server_port": state.get("server_port"),
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