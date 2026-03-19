"""
LangGraph Multi-Agent Orchestrator - SonarBot
Persistent memory across conversations and restarts.
All agents: coding, desktop, web, general
"""
from typing import Dict, Any, TypedDict, List, Annotated, Optional, Callable
from datetime import datetime, timezone, timedelta
import operator
import re
import uuid
from loguru import logger

from langgraph.graph import StateGraph, END

from app.agents.router_agent import router_agent
from app.agents.orchestration_models import (
    AgentHandoff,
    ApprovalRequest,
    ExecutionPlan,
    ExecutionTraceEvent,
    PlanStep,
    TaskAnalysis,
    TaskEnvelope,
)
from app.services.context_builder import context_builder
from app.services.enhanced_memory_service import enhanced_memory_service
from app.core.llm import llm_adapter
from app.models import Message, MessageRole


# ===== STATE DEFINITION =====

class AgentState(TypedDict):
    """Shared state across all graph nodes"""
    # Input
    user_message: str
    user_id: str
    conversation_id: str
    
    # Context
    user_context: str
    conversation_history: List[Dict]
    
    # Routing
    task_type: str
    confidence: float
    routing_reason: str
    
    # Agent outputs
    agent_path: List[str]
    current_output: str
    
    # Execution
    iteration: int
    max_iterations: int
    errors: List[str]
    
    # Final
    final_output: str
    success: bool
    metadata: Dict[str, Any]
    
    # Code specific
    code: str
    files: Dict[str, str]
    language: str
    
    # Desktop specific
    desktop_action: str
    desktop_result: Dict
    
    # Web autonomous specific
    web_screenshots: List[str]
    web_actions: List[Dict]
    web_current_url: str
    web_permission_needed: Dict


class LangGraphOrchestrator:
    """LangGraph orchestrator with ALL agent types"""
    
    def __init__(self):
        self.context_builder = context_builder
        self.memory_service = enhanced_memory_service
        self.llm = llm_adapter
        self.graph = self._build_graph()
        logger.info("✅ LangGraph Orchestrator initialized")
    
    def _build_graph(self) -> StateGraph:
        """Build agent graph with ALL 6 agent types + cross-agent routing"""
        workflow = StateGraph(AgentState)
        
        # ALL NODES: code, desktop, web, web_autonomous, email, calendar, general + cross-agent check
        workflow.add_node("load_context", self._load_context_node)
        workflow.add_node("route", self._route_node)
        workflow.add_node("code_agent", self._code_agent_node)
        workflow.add_node("desktop_agent", self._desktop_agent_node)
        workflow.add_node("web_agent", self._web_agent_node)
        workflow.add_node("web_autonomous_agent", self._web_autonomous_agent_node)
        workflow.add_node("email_agent", self._email_agent_node)
        workflow.add_node("calendar_agent", self._calendar_agent_node)
        workflow.add_node("general_agent", self._general_agent_node)
        workflow.add_node("cross_agent_check", self._cross_agent_check_node)
        workflow.add_node("save_memory", self._save_memory_node)
        
        # Flow
        workflow.set_entry_point("load_context")
        workflow.add_edge("load_context", "route")
        
        # Routing for ALL 7 types
        workflow.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "coding": "code_agent",
                "desktop": "desktop_agent",
                "web": "web_agent",
                "web_autonomous": "web_autonomous_agent",
                "email": "email_agent",
                "calendar": "calendar_agent",
                "general": "general_agent"
            }
        )
        
        # All agents → cross-agent check (may chain to another agent or save)
        workflow.add_edge("code_agent", "cross_agent_check")
        workflow.add_edge("desktop_agent", "cross_agent_check")
        workflow.add_edge("web_agent", "cross_agent_check")
        workflow.add_edge("web_autonomous_agent", "cross_agent_check")
        workflow.add_edge("email_agent", "cross_agent_check")
        workflow.add_edge("calendar_agent", "cross_agent_check")
        workflow.add_edge("general_agent", "cross_agent_check")
        
        # Cross-agent check decides: chain to another agent or save
        workflow.add_conditional_edges(
            "cross_agent_check",
            self._cross_agent_decision,
            {
                "calendar": "calendar_agent",
                "email": "email_agent",
                "web_autonomous": "web_autonomous_agent",
                "done": "save_memory"
            }
        )
        
        workflow.add_edge("save_memory", END)
        
        return workflow.compile()
    
    # ===== NODE IMPLEMENTATIONS =====
    
    async def _load_context_node(self, state: AgentState) -> AgentState:
        """Load user context from ALL memory sources (cross-conversation)"""
        logger.info("📚 Loading context...")
        
        try:
            # Build personalized context (SQL + Qdrant, cross-conversation)
            user_context = self.context_builder.build_user_context(
                user_id=state['user_id'],
                current_message=state['user_message'],
                conversation_id=state['conversation_id']
            )
            
            # Load current conversation history from SQL
            history = self.memory_service.get_conversation_history(
                conversation_id=state['conversation_id'],
                limit=10
            )
            
            # Always load recent cross-conversation messages for this user
            # so chat threads/topics (same user, different thread IDs) share context
            all_recent = self.memory_service.get_all_user_messages(
                user_id=state['user_id'],
                limit=10
            )
            if all_recent and not history:
                # New thread — seed with recent user messages from other threads
                history = all_recent[-5:]
            elif all_recent and history:
                # Existing thread — prepend cross-thread context before current history
                cross_msgs = [m for m in all_recent if m.get('conversation_id') != state['conversation_id']]
                if cross_msgs:
                    history = cross_msgs[-3:] + history  # last 3 from other threads + current
            
            state['user_context'] = user_context
            state['conversation_history'] = history
            state['agent_path'] = ['context_loader']
            
            logger.info(f"✅ Loaded context ({len(user_context)} chars, {len(history)} history msgs)")
        
        except Exception as e:
            logger.error(f"❌ Context load error: {e}")
            state['user_context'] = ""
            state['conversation_history'] = []
            state['agent_path'] = ['context_loader']
        
        return state
    
    async def _route_node(self, state: AgentState) -> AgentState:
        """Route to appropriate agent"""
        logger.info("🎯 Routing task...")
        
        try:
            # Classify with user context + conversation history
            result = router_agent.classify_task(
                user_message=state['user_message'],
                user_context=state.get('user_context', ''),
                conversation_history=state.get('conversation_history', [])
            )
            
            state['task_type'] = result['task_type']
            state['confidence'] = result['confidence']
            state['routing_reason'] = result['reasoning']
            state['agent_path'].append('router')
            
            logger.info(f"📍 Routed to: {result['task_type']} ({result['confidence']:.0%})")
        
        except Exception as e:
            logger.error(f"❌ Routing error: {e}")
            state['task_type'] = 'general'
            state['confidence'] = 0.5
            state['routing_reason'] = f"Error: {str(e)}"
        
        return state
    
    def _route_decision(self, state: AgentState) -> str:
        """Route to correct agent (with per-user permission checks)"""
        task_type = state.get('task_type', 'general')
        user_id = state.get('user_id', '')
        
        routing_map = {
            'coding': 'coding',
            'code': 'coding',
            'desktop': 'desktop',
            'web': 'web',
            'web_autonomous': 'web_autonomous',
            'email': 'email',
            'calendar': 'calendar',
            'general': 'general'
        }
        
        route = routing_map.get(task_type, 'general')
        
        # Ensure user permissions exist (auto-creates on first use)
        from app.services.permission_service import permission_service
        permission_service.get_permissions(user_id)
        
        return route
    
    async def _code_agent_node(self, state: AgentState) -> AgentState:
        """Code specialist - generates code AND saves files to workspace"""
        logger.info("💻 Code Agent processing...")
        
        try:
            from app.agents.code_specialist_agent import code_specialist
            from app.services.sandbox_services import sandbox_service
            
            # Convert history to dicts
            history_dicts = []
            for msg in state.get('conversation_history', []):
                if isinstance(msg, dict):
                    history_dicts.append({
                        'role': msg.get('role', 'user'),
                        'content': msg.get('content', '')
                    })
            
            # Generate code
            result = await code_specialist.generate_code(
                description=state['user_message'],
                user_id=state['user_id'],
                conversation_history=history_dicts,
                iteration=state.get('iteration', 1),
                previous_error=state.get('errors', [])[-1] if state.get('errors') else None,
                context=state.get('user_context', '')
            )
            
            # Extract results
            files = result.get('files', {})
            project_type = result.get('project_type', 'unknown')
            project_name = result.get('project_name', 'generated_project')
            
            state['code'] = result.get('code', '')
            state['files'] = files
            state['language'] = result.get('language', '')
            state['agent_path'].append('code_specialist')
            state['success'] = result.get('success', True)
            
            # ✅ ACTUALLY SAVE FILES TO WORKSPACE
            if files and result.get('success', True):
                try:
                    # Try sandbox execution (saves to workspace + runs code)
                    sandbox_result = await sandbox_service.execute_project(
                        files=files,
                        project_type=project_type,
                        project_name=project_name,
                        install_command=result.get('install_command'),
                        start_command=result.get('start_command'),
                        port=result.get('port')
                    )
                    
                    project_path = sandbox_result.get('project_path', '')
                    server_url = sandbox_result.get('server_url', '')
                    server_running = sandbox_result.get('server_started', False)
                    
                    # Build rich output message
                    output_parts = []
                    if result.get('raw_output'):
                        output_parts.append(result['raw_output'])
                    
                    if project_path:
                        output_parts.append(f"\n\n📁 **Project saved to:** {project_path}")
                    if server_running and server_url:
                        output_parts.append(f"🌐 **Live preview:** {server_url}")
                    if sandbox_result.get('stdout'):
                        output_parts.append(f"\n**Output:**\n```\n{sandbox_result['stdout']}\n```")
                    if sandbox_result.get('stderr') and not sandbox_result.get('success'):
                        output_parts.append(f"\n**Errors:**\n```\n{sandbox_result['stderr']}\n```")
                    
                    state['current_output'] = '\n'.join(output_parts)
                    
                    # Pass extra metadata
                    state['metadata'] = {
                        'project_path': project_path,
                        'server_url': server_url,
                        'server_running': server_running,
                        'project_type': project_type,
                        'sandbox_success': sandbox_result.get('success', False)
                    }
                    
                    logger.info(f"✅ Project saved to workspace: {project_path}")
                    
                except Exception as sandbox_err:
                    logger.warning(f"⚠️ Sandbox execution failed, saving files locally: {sandbox_err}")
                    # Fallback: save files directly to workspace
                    try:
                        project_path = sandbox_service._save_to_workspace(files, project_name)
                        output_parts = []
                        if result.get('raw_output'):
                            output_parts.append(result['raw_output'])
                        if project_path:
                            output_parts.append(f"\n\n📁 **Project saved to:** {project_path}")
                        output_parts.append("\n⚠️ Sandbox execution unavailable - files saved to workspace only.")
                        state['current_output'] = '\n'.join(output_parts)
                        state['metadata'] = {'project_path': project_path}
                    except Exception as save_err:
                        logger.error(f"❌ Failed to save files: {save_err}")
                        state['current_output'] = result.get('raw_output', 'Code generated but could not be saved.')
            else:
                state['current_output'] = result.get('raw_output', result.get('explanation', ''))
            
            state['final_output'] = state['current_output']
            
            logger.info("✅ Code generation complete")
        
        except Exception as e:
            logger.error(f"❌ Code agent error: {e}")
            state['current_output'] = f"Code generation failed: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Code agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _desktop_agent_node(self, state: AgentState) -> AgentState:
        """Desktop specialist - routes to host desktop bridge OR virtual desktop based on permissions"""
        logger.info("🖥️ Desktop Agent processing...")
        
        user_id = state.get('user_id', '')
        
        # Check desktop access tier
        from app.services.permission_service import permission_service
        perms = permission_service.get_permissions(user_id)
        desktop_access = perms.get('desktop_access', 'none')
        
        if desktop_access == 'virtual':
            return await self._virtual_desktop_handler(state)
        
        # Host desktop (default for local users)
        try:
            from app.skills.desktop_bridge import desktop_bridge
            
            # Step 1: Check if desktop agent is reachable
            desktop_available = await desktop_bridge.check_connection()
            
            if not desktop_available:
                # Desktop agent not running - provide helpful error
                state['current_output'] = (
                    "❌ **Desktop Agent is not running!**\n\n"
                    "To use desktop control features, please start the Desktop Agent:\n\n"
                    "1. Open a new terminal\n"
                    "2. Navigate to `desktop-agent/` folder\n"
                    "3. Run: `python desktop_agent.py`\n\n"
                    "The Desktop Agent must run on your host machine (not in Docker) "
                    "to control your actual desktop."
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('desktop_specialist')
                state['success'] = False
                state['desktop_action'] = 'agent_unavailable'
                state['desktop_result'] = {'status': 'desktop_agent_not_running'}
                return state
            
            # Step 2: Use LLM to parse user intent into desktop actions
            messages = []
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content="""You are a Desktop Control Agent. Parse the user's request into ONE OR MORE desktop actions.

Available skills and their arguments:
- take_screenshot: {"region": "x,y,width,height"}
- mouse_move: {"x": int, "y": int}
- mouse_click: {"x": int, "y": int, "button": "left|right|middle", "clicks": 1}
- mouse_scroll: {"amount": int}
- type_text: {"text": "string"}
- press_key: {"key": "string"}
- press_hotkey: {"keys": "ctrl+c"}
- open_application: {"name": "app_name"}
- list_windows: {}
- focus_window: {"title": "window_title"}
- minimize_window: {"title": "window_title"}
- maximize_window: {"title": "window_title"}
- read_screen_text: {}

Respond EXACTLY in this format (one action per line):
ACTION: skill_name | {"arg1": "value1", "arg2": "value2"}
ACTION: skill_name | {"arg1": "value1"}
EXPLANATION: Brief description of what you're doing

Examples:
User: "open chrome"
ACTION: open_application | {"name": "chrome"}
EXPLANATION: Opening Google Chrome browser

User: "take a screenshot"
ACTION: take_screenshot | {}
EXPLANATION: Taking a screenshot of your desktop

User: "type hello world in notepad"
ACTION: open_application | {"name": "notepad"}
ACTION: type_text | {"text": "hello world"}
EXPLANATION: Opening Notepad and typing hello world"""
            ))
            
            messages.append(Message(
                role=MessageRole.USER,
                content=state['user_message']
            ))
            
            # Get LLM to parse the intent
            llm_result = await self.llm.generate_response(messages)
            llm_response = llm_result.get('response', '')
            
            # Step 3: Parse LLM response into actions and execute them
            import json as json_module
            actions = []
            explanation = ""
            
            for line in llm_response.split('\n'):
                line = line.strip()
                if line.startswith('ACTION:'):
                    try:
                        parts = line[7:].strip().split('|', 1)
                        skill_name = parts[0].strip()
                        args = json_module.loads(parts[1].strip()) if len(parts) > 1 else {}
                        actions.append((skill_name, args))
                    except Exception as parse_err:
                        logger.warning(f"⚠️ Could not parse action line: {line} - {parse_err}")
                elif line.startswith('EXPLANATION:'):
                    explanation = line[12:].strip()
            
            if not actions:
                # LLM didn't produce parseable actions, try a simple fallback
                msg_lower = state['user_message'].lower()
                if any(kw in msg_lower for kw in ['screenshot', 'screen shot', 'capture screen']):
                    actions = [('take_screenshot', {})]
                    explanation = 'Taking a screenshot'
                elif any(kw in msg_lower for kw in ['open ', 'launch ', 'start ']):
                    for kw in ['open ', 'launch ', 'start ']:
                        if kw in msg_lower:
                            app_name = msg_lower.split(kw, 1)[1].strip().split()[0] if msg_lower.split(kw, 1)[1].strip() else ''
                            if app_name:
                                actions = [('open_application', {'name': app_name})]
                                explanation = f'Opening {app_name}'
                            break
                elif 'type ' in msg_lower:
                    text = state['user_message'].split('type ', 1)[1].strip() if 'type ' in state['user_message'].lower() else ''
                    if text:
                        actions = [('type_text', {'text': text})]
                        explanation = 'Typing text'
                elif any(kw in msg_lower for kw in ['click', 'mouse']):
                    actions = [('mouse_click', {'button': 'left'})]
                    explanation = 'Clicking mouse'
            
            # Step 4: Execute each action via desktop bridge
            results = []
            all_success = True
            
            for skill_name, args in actions:
                logger.info(f"🔧 Executing desktop action: {skill_name} with args: {args}")
                action_result = await desktop_bridge.execute_skill(skill_name, args, safe_mode=False)
                results.append({
                    'skill': skill_name,
                    'args': args,
                    'result': action_result
                })
                if not action_result.get('success', False):
                    all_success = False
                    logger.warning(f"⚠️ Action {skill_name} failed: {action_result.get('error', 'unknown')}")
            
            # Step 5: Build response
            output_parts = []
            if explanation:
                output_parts.append(f"🖥️ **{explanation}**\n")
            
            for r in results:
                skill = r['skill']
                res = r['result']
                if res.get('success'):
                    result_data = res.get('result', {})
                    if skill == 'take_screenshot':
                        output_parts.append("✅ Screenshot captured successfully")
                    elif skill == 'open_application':
                        output_parts.append(f"✅ Application launched: {r['args'].get('name', 'unknown')}")
                    elif skill == 'type_text':
                        output_parts.append("✅ Typed text successfully")
                    elif skill == 'press_key':
                        output_parts.append(f"✅ Key pressed: {r['args'].get('key', '')}")
                    elif skill == 'press_hotkey':
                        output_parts.append(f"✅ Hotkey pressed: {r['args'].get('keys', '')}")
                    elif skill in {'mouse_click', 'mouse_move', 'mouse_scroll'}:
                        output_parts.append(f"✅ Mouse action completed: {skill.replace('_', ' ')}")
                    elif skill == 'list_windows':
                        if isinstance(result_data, dict):
                            windows = result_data.get('windows', [])
                            output_parts.append(f"✅ Found {len(windows)} windows")
                            for w in windows[:10]:
                                if isinstance(w, dict):
                                    output_parts.append(f"  - {w.get('title', 'Unknown')}")
                    elif skill in {'focus_window', 'minimize_window', 'maximize_window'}:
                        output_parts.append(f"✅ Window action completed: {skill.replace('_', ' ')}")
                    elif skill == 'read_screen_text':
                        output_parts.append("✅ Screen text read successfully")
                    else:
                        output_parts.append(f"✅ {skill} executed successfully")
                else:
                    error_msg = res.get('error', 'Unknown error')
                    output_parts.append(f"❌ {skill} failed: {error_msg}")
            
            if not actions:
                output_parts.append("⚠️ Could not determine the desktop action from your request. Try being more specific, e.g. 'open chrome', 'take a screenshot', 'type hello world'.")
            
            state['current_output'] = '\n'.join(output_parts)
            state['final_output'] = state['current_output']
            state['agent_path'].append('desktop_specialist')
            state['success'] = all_success
            state['desktop_action'] = 'executed'
            state['desktop_result'] = {'actions': len(actions), 'results': [{'skill': r['skill'], 'success': r['result'].get('success')} for r in results]}
            
            logger.info(f"✅ Desktop actions complete: {len(actions)} actions, success={all_success}")
        
        except Exception as e:
            logger.error(f"❌ Desktop agent error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state['current_output'] = f"Desktop control error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Desktop agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _virtual_desktop_handler(self, state: AgentState) -> AgentState:
        """Handle desktop actions in a virtual Xvfb sandbox for remote users."""
        logger.info("🖥️ Virtual Desktop handler for remote user...")
        user_id = state.get('user_id', '')
        
        try:
            from app.services.virtual_desktop_service import virtual_desktop_service
            
            session = await virtual_desktop_service.get_or_create(user_id)
            msg_lower = state['user_message'].lower()
            
            # Simple action parsing for virtual desktop
            if any(kw in msg_lower for kw in ['screenshot', 'screen shot', 'capture']):
                result = await virtual_desktop_service.take_screenshot(user_id)
                if result.get('success'):
                    state['current_output'] = (
                        f"✅ **Virtual desktop screenshot captured** (display {session.display_str})\n\n"
                        "📸 Screenshot attached."
                    )
                    state['metadata'] = {
                        'screenshot_base64': result.get('screenshot_base64', ''),
                        'virtual_desktop': True,
                    }
                else:
                    state['current_output'] = f"❌ Screenshot failed: {result.get('error', 'unknown')}"
            elif any(kw in msg_lower for kw in ['open ', 'launch ', 'start ']):
                for kw in ['open ', 'launch ', 'start ']:
                    if kw in msg_lower:
                        app_name = msg_lower.split(kw, 1)[1].strip().split()[0]
                        break
                result = await virtual_desktop_service.execute_in_session(
                    user_id, f"{app_name} &"
                )
                state['current_output'] = (
                    f"🖥️ **Launched `{app_name}` in your virtual desktop** (display {session.display_str})"
                )
            else:
                # Generic command execution in virtual desktop
                result = await virtual_desktop_service.execute_in_session(
                    user_id, state['user_message']
                )
                stdout = result.get('stdout', '').strip()
                stderr = result.get('stderr', '').strip()
                output_parts = [f"🖥️ **Virtual Desktop** (display {session.display_str})"]
                if stdout:
                    output_parts.append(f"```\n{stdout}\n```")
                if stderr:
                    output_parts.append(f"**Stderr:**\n```\n{stderr}\n```")
                if not stdout and not stderr:
                    output_parts.append("Command executed (no output).")
                state['current_output'] = '\n'.join(output_parts)
            
            state['final_output'] = state['current_output']
            state['agent_path'].append('virtual_desktop')
            state['success'] = True
            
        except RuntimeError as e:
            # Xvfb not installed
            state['current_output'] = f"❌ {str(e)}"
            state['final_output'] = state['current_output']
            state['success'] = False
        except Exception as e:
            logger.error(f"❌ Virtual desktop error: {e}")
            state['current_output'] = f"Virtual desktop error: {str(e)}"
            state['final_output'] = state['current_output']
            state['success'] = False
        
        return state
    
    async def _web_agent_node(self, state: AgentState) -> AgentState:
        """✅ NEW: Web specialist"""
        logger.info("🌐 Web Agent processing...")
        
        try:
            # Build Message objects
            messages = []
            
            if state.get('user_context'):
                messages.append(Message(
                    role=MessageRole.SYSTEM,
                    content=state['user_context']
                ))
            
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content="You are a Web Agent that can scrape websites and fetch data. Provide clear instructions or results."
            ))
            
            for msg in state.get('conversation_history', [])[-3:]:
                if isinstance(msg, dict):
                    role = MessageRole.USER if msg.get('role') == 'user' else MessageRole.ASSISTANT
                    messages.append(Message(role=role, content=msg.get('content', '')))
            
            messages.append(Message(
                role=MessageRole.USER,
                content=state['user_message']
            ))
            
            result = await self.llm.generate_response(messages)
            
            state['current_output'] = result['response']
            state['final_output'] = result['response']
            state['agent_path'].append('web_specialist')
            state['success'] = True
            
            logger.info("✅ Web response complete")
        
        except Exception as e:
            logger.error(f"❌ Web agent error: {e}")
            state['current_output'] = f"Web task error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Web agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _web_autonomous_agent_node(self, state: AgentState) -> AgentState:
        """
        Autonomous Web Agent — Perplexity Comet-style browser automation.
        
        Capabilities:
        - Navigate to any URL and understand page content
        - Take screenshots and read DOM to comprehend pages
        - Execute multi-step browsing tasks autonomously
        - Ask for user permission before sensitive actions
        - Extract and summarize information from web pages
        - Integrate with memory for personalized web browsing
        """
        logger.info("🌐 Web Autonomous Agent processing...")
        
        try:
            from app.services.web_agent_service import web_agent_service
            
            user_id = state['user_id']
            user_message = state['user_message']
            conversation_history = state.get('conversation_history', [])
            user_context = state.get('user_context', '')
            
            # Progress callback — forward to message_callback if available
            callback = state.get('metadata', {}).get('_message_callback')
            
            # Execute the autonomous web task
            result = await web_agent_service.execute_task(
                user_message=user_message,
                user_id=user_id,
                conversation_history=[
                    msg for msg in conversation_history
                    if isinstance(msg, dict)
                ],
                user_context=user_context,
                message_callback=callback,
            )
            
            # Set outputs
            state['current_output'] = result.get('output', 'Web task completed.')
            state['final_output'] = state['current_output']
            state['agent_path'].append('web_autonomous_agent')
            state['success'] = result.get('success', False)
            state['web_screenshots'] = result.get('screenshots', [])
            state['web_actions'] = result.get('actions_taken', [])
            state['web_current_url'] = result.get('current_url', '')
            state['web_permission_needed'] = result.get('permission_needed') or {}
            
            # Store metadata for frontend
            state['metadata'] = {
                **state.get('metadata', {}),
                'web_screenshots': result.get('screenshots', [])[-1:],  # last screenshot
                'web_actions_count': len(result.get('actions_taken', [])),
                'web_current_url': result.get('current_url', ''),
                'web_autonomous': True,
            }
            
            # Learn from web browsing behavior
            if user_id and result.get('success'):
                self.memory_service.learn_from_behavior(user_id, {
                    'task_type': 'web_autonomous',
                    'success': True,
                    'actions_count': len(result.get('actions_taken', [])),
                    'url_visited': result.get('current_url', ''),
                })
            
            logger.info(f"✅ Web autonomous complete: {len(result.get('actions_taken', []))} actions")
        
        except Exception as e:
            logger.error(f"❌ Web autonomous agent error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state['current_output'] = f"🌐 Web agent error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Web autonomous error: {str(e)}")
            state['success'] = False
        
        return state

    def _format_recent_conversation_history(
        self,
        conversation_history: list,
        limit: int = 6,
        max_chars: int = 500,
    ) -> str:
        """Build a compact recent-history block for follow-up specialist prompts."""
        if not conversation_history:
            return ""

        lines = []
        for msg in conversation_history[-limit:]:
            role = msg.get('role', 'user') if isinstance(msg, dict) else 'user'
            content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
            if len(content) > max_chars:
                content = content[:max_chars] + "..."
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _extract_latest_draft_id(self, conversation_history: list) -> str:
        """Extract the most recent Gmail draft id from prior assistant messages."""
        if not conversation_history:
            return ""

        for msg in reversed(conversation_history):
            content = msg.get('content', '') if isinstance(msg, dict) else str(msg)
            match = re.search(r"Draft ID:\s*(\S+)", content, re.IGNORECASE)
            if match:
                return match.group(1).strip('_').strip('*')
        return ""

    def _is_email_send_confirmation(self, user_message: str) -> bool:
        """Detect short follow-ups that mean 'send the previously drafted email'."""
        normalized = user_message.strip().lower()
        exact_phrases = {
            "send it",
            "yes send",
            "send the email",
            "send the draft",
            "go ahead",
            "go ahead and send",
            "yes, send the email",
        }
        return normalized in exact_phrases

    def _is_explicit_send_email_request(self, user_message: str) -> bool:
        """Detect a first-turn request that clearly asks to send, not just draft, an email."""
        message_lower = user_message.lower()
        return any(
            phrase in message_lower
            for phrase in [
                "send email",
                "send an email",
                "send the email",
                "send mail",
            ]
        )
    
    async def _email_agent_node(self, state: AgentState) -> AgentState:
        """Email specialist - Gmail operations via LLM intent parsing."""
        logger.info("Email Agent processing...")

        try:
            from app.services.gmail_service import gmail_service
            from app.services.google_auth_service import google_auth_service

            user_id = state['user_id']
            user_message = state['user_message']
            conversation_history = state.get('conversation_history', [])
            history_text = self._format_recent_conversation_history(conversation_history)
            approval_override = bool(state.get('metadata', {}).get('approval_override'))
            recent_draft_id = self._extract_latest_draft_id(conversation_history)

            if not google_auth_service.is_connected(user_id):
                state['current_output'] = (
                    "Email features require a connected Google account.\n\n"
                    "Connect Google from the settings panel, then I can:\n"
                    "- Read your inbox\n"
                    "- Send emails with confirmation\n"
                    "- Search emails\n"
                    "- Check unread count\n"
                    "- Archive or trash messages"
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('email_specialist')
                state['success'] = False
                return state

            action = ""
            args = {}
            explanation = ""

            if self._is_email_send_confirmation(user_message) and recent_draft_id:
                action = 'SEND_DRAFT'
                explanation = "Sending the previously composed draft."
            else:
                messages = [
                    Message(
                        role=MessageRole.SYSTEM,
                        content="""You are an Email Agent. Parse the user's request into a Gmail action.

Available actions:
- LIST_EMAILS: List inbox emails. Args: {"query": "", "max_results": 10}
- READ_EMAIL: Read specific email. Args: {"message_id": "..."}
- SEARCH_EMAILS: Search with query. Args: {"query": "from:alice subject:report", "max_results": 10}
- COMPOSE_EMAIL: Prepare an email. Args: {"to": "email@example.com", "subject": "...", "body": "..."}
- SEND_DRAFT: Send a previously composed draft. Args: {"draft_id": "..."}
- UNREAD_COUNT: Check unread count. Args: {}
- MARK_READ: Mark email as read. Args: {"message_id": "..."}
- ARCHIVE: Archive email. Args: {"message_id": "..."}
- TRASH: Trash email. Args: {"message_id": "..."}

CRITICAL RULES:
1. For COMPOSE_EMAIL: create a professional email body with complete to, subject, and body fields.
2. If APPROVAL_GRANTED is true and the user explicitly asked to send the email, still return COMPOSE_EMAIL with complete fields so the system can send it immediately.
3. For SEND_DRAFT: when user says "send it", "yes send", "go ahead", "send the email", or "send the draft", use SEND_DRAFT. The system will extract the draft id from history.
4. For SEARCH: use Gmail query syntax (from:, to:, subject:, is:unread, after:, before:, has:attachment, in:sent, in:inbox).
5. If user just says "check email" or "any new email", use LIST_EMAILS with query "is:unread".
6. If user asks about "last sent email", "emails I sent", or "my sent mail", use SEARCH_EMAILS with query "in:sent" and max_results 1-5.
7. For READ_EMAIL: only use a real message_id from a previous LIST_EMAILS or SEARCH_EMAILS result. Never invent or guess it.
8. If user asks about a specific email but you do not have its message_id, use SEARCH_EMAILS first to find it.
9. Keep Gmail, inbox, email, and mail requests in EMAIL. Do not treat them like generic web browsing.

Respond EXACTLY in this format:
ACTION: <action_name>
ARGS: <json_args>
EXPLANATION: <brief description>""",
                    ),
                    Message(
                        role=MessageRole.USER,
                        content=(
                            f"APPROVAL_GRANTED: {approval_override}\n\n"
                            f"CONVERSATION HISTORY:\n{history_text}\n\n"
                            f"CURRENT REQUEST: {user_message}"
                        )
                        if history_text
                        else f"APPROVAL_GRANTED: {approval_override}\nCURRENT REQUEST: {user_message}",
                    ),
                ]

                llm_result = await self.llm.generate_response(messages)
                llm_response = llm_result.get('response', '')

                import json as json_module

                for line in llm_response.split('\n'):
                    line = line.strip()
                    if line.startswith('ACTION:'):
                        action = line.split(':', 1)[1].strip().upper()
                    elif line.startswith('ARGS:'):
                        try:
                            args = json_module.loads(line.split(':', 1)[1].strip())
                        except Exception:
                            args = {}
                    elif line.startswith('EXPLANATION:'):
                        explanation = line.split(':', 1)[1].strip()

            output = ""

            if action in {'LIST_EMAILS', 'SEARCH_EMAILS'}:
                query = args.get('query', '')
                max_results = args.get('max_results', 10)
                emails = gmail_service.list_emails(user_id, query=query, max_results=max_results)

                if emails:
                    output = f"Found {len(emails)} emails"
                    if query:
                        output += f" (query: {query})"
                    output += "\n\n"
                    for index, email in enumerate(emails, 1):
                        unread = "[unread] " if email['is_unread'] else ""
                        output += f"{index}. {unread}{email['subject']}\n"
                        output += f"   From: {email['from']} | {email['date']}\n"
                        output += f"   {email['snippet'][:100]}\n\n"
                else:
                    output = "No emails found matching your criteria."

            elif action == 'READ_EMAIL':
                msg_id = args.get('message_id', '')
                if msg_id and len(msg_id) > 5 and ' ' not in msg_id and not any(
                    word in msg_id.lower() for word in ['last', 'sent', 'first', 'recent', 'email', 'mail', 'message']
                ):
                    email = gmail_service.read_email(user_id, msg_id)
                    output = (
                        f"{email['subject']}\n"
                        f"From: {email['from']}\n"
                        f"To: {email['to']}\n"
                        f"Date: {email['date']}\n\n"
                        f"{email['body'][:2000]}"
                    )
                    if email['attachments']:
                        output += f"\n\nAttachments: {', '.join(a['filename'] for a in email['attachments'])}"
                else:
                    logger.warning(f"Invalid message_id '{msg_id}', falling back to sent-mail lookup")
                    emails = gmail_service.list_emails(user_id, query='in:sent', max_results=1)
                    if emails:
                        first = emails[0]
                        email = gmail_service.read_email(user_id, first['id'])
                        output = (
                            "Your last sent email:\n\n"
                            f"{email['subject']}\n"
                            f"From: {email['from']}\n"
                            f"To: {email['to']}\n"
                            f"Date: {email['date']}\n\n"
                            f"{email['body'][:2000]}"
                        )
                    else:
                        output = "No sent emails found."

            elif action == 'COMPOSE_EMAIL':
                to = args.get('to', '')
                subject = args.get('subject', '')
                body = args.get('body', '')
                should_send_direct = approval_override and self._is_explicit_send_email_request(user_message)

                if to and subject:
                    if should_send_direct:
                        result = gmail_service.send_email_direct(
                            user_id=user_id,
                            to=to,
                            subject=subject,
                            body=body,
                        )
                        output = (
                            "Email sent successfully.\n\n"
                            f"To: {to}\n"
                            f"Subject: {subject}\n"
                            f"Message ID: {result.get('message_id', 'sent')}"
                        )
                    else:
                        draft = gmail_service.compose_draft(
                            user_id=user_id,
                            to=to,
                            subject=subject,
                            body=body,
                        )
                        output = (
                            "Email draft created.\n\n"
                            f"To: {to}\n"
                            f"Subject: {subject}\n"
                            f"Body:\n{body}\n\n"
                            "This email has not been sent yet. Say \"send it\" to send the draft.\n\n"
                            f"Draft ID: {draft['draft_id']}"
                        )
                else:
                    output = "Missing required fields. Please provide the recipient, subject, and what you want to say."

            elif action == 'SEND_DRAFT':
                draft_id = recent_draft_id
                if not draft_id:
                    llm_draft_id = args.get('draft_id', '')
                    if llm_draft_id and len(llm_draft_id) > 5 and ' ' not in llm_draft_id:
                        draft_id = llm_draft_id

                if draft_id:
                    result = gmail_service.send_draft(user_id, draft_id)
                    output = f"Email sent successfully.\n\nMessage ID: {result.get('message_id', 'sent')}"
                else:
                    output = "Could not find a draft to send. Please compose an email first."

            elif action == 'UNREAD_COUNT':
                count = gmail_service.get_unread_count(user_id)
                output = f"You have {count} unread email{'s' if count != 1 else ''}."

            elif action == 'MARK_READ':
                msg_id = args.get('message_id', '')
                if msg_id:
                    gmail_service.mark_as_read(user_id, msg_id)
                    output = "Email marked as read."
                else:
                    output = "No message ID provided."

            elif action == 'ARCHIVE':
                msg_id = args.get('message_id', '')
                if msg_id:
                    gmail_service.archive_email(user_id, msg_id)
                    output = "Email archived."
                else:
                    output = "No message ID provided."

            elif action == 'TRASH':
                msg_id = args.get('message_id', '')
                if msg_id:
                    gmail_service.trash_email(user_id, msg_id)
                    output = "Email moved to trash."
                else:
                    output = "No message ID provided."

            else:
                count = gmail_service.get_unread_count(user_id)
                emails = gmail_service.list_emails(user_id, query="is:unread", max_results=5)
                output = f"You have {count} unread emails.\n\n"
                if emails:
                    for index, email in enumerate(emails, 1):
                        output += f"{index}. {email['subject']} from {email['from']}\n"

            if explanation:
                output = f"*{explanation}*\n\n{output}"

            state['current_output'] = output
            state['final_output'] = output
            state['agent_path'].append('email_specialist')
            state['success'] = True

            logger.info(f"Email action complete: {action or 'DEFAULT'}")

        except PermissionError as exc:
            state['current_output'] = f"Permission error: {str(exc)}"
            state['final_output'] = state['current_output']
            state['agent_path'].append('email_specialist')
            state['success'] = False
        except Exception as exc:
            logger.error(f"Email agent error: {exc}")
            state['current_output'] = f"Email error: {str(exc)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Email agent error: {str(exc)}")
            state['success'] = False

        return state

    async def _calendar_agent_node(self, state: AgentState) -> AgentState:
        """Calendar specialist - Google Calendar and reminder operations."""
        logger.info("Calendar Agent processing...")

        try:
            from app.services.calendar_service import calendar_service
            from app.services.scheduler_service import scheduler_service
            from app.services.google_auth_service import google_auth_service

            user_id = state['user_id']
            user_message = state['user_message']
            conversation_history = state.get('conversation_history', [])
            history_text = self._format_recent_conversation_history(conversation_history)
            message_lower = user_message.lower().strip()

            if not google_auth_service.is_connected(user_id):
                state['current_output'] = (
                    "Calendar features require a connected Google account.\n\n"
                    "Connect Google from the settings panel, then I can:\n"
                    "- Show your schedule\n"
                    "- Create events\n"
                    "- Set reminders\n"
                    "- Check free and busy times"
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('calendar_specialist')
                state['success'] = False
                return state

            action = ""
            args = {}
            explanation = ""

            if any(phrase in message_lower for phrase in [
                "what's on my calendar today",
                "what is on my calendar today",
                "today's schedule",
                "my schedule today",
                "calendar today",
            ]):
                action = 'TODAY_EVENTS'
                explanation = "Checking today's schedule."
            elif any(phrase in message_lower for phrase in [
                "list reminders",
                "show reminders",
                "my reminders",
                "scheduled jobs",
            ]):
                action = 'LIST_REMINDERS'
                explanation = "Listing your active reminders and scheduled jobs."
            else:
                messages = [
                    Message(
                        role=MessageRole.SYSTEM,
                        content="""You are a Calendar Agent. Parse the user's request into a calendar action.

Available actions:
- LIST_EVENTS: List upcoming events. Args: {"days": 7, "max_results": 10}
- TODAY_EVENTS: Show today's schedule. Args: {}
- CREATE_EVENT: Create a new event. Args: {"summary": "Meeting", "start_time": "2026-03-10T09:00:00", "end_time": "2026-03-10T10:00:00", "description": "", "location": "", "attendees": ["email@example.com"], "reminder_minutes": 15, "time_zone": "Asia/Kolkata"}
- UPDATE_EVENT: Update event. Args: {"event_id": "...", "updates": {"summary": "New title"}}
- DELETE_EVENT: Delete event. Args: {"event_id": "..."}
- SET_REMINDER: Set a one-time reminder. Args: {"description": "Take medicine", "run_at": "2026-03-08T09:00:00"}
- LIST_REMINDERS: Show active reminders. Args: {}

IMPORTANT RULES:
1. For CREATE_EVENT: always include both start_time and end_time in ISO format without timezone offset. Use time_zone for the location timezone and default it to Asia/Kolkata.
2. If the user says "tomorrow at 3pm" or similar relative time phrases, calculate the actual future date.
3. For SET_REMINDER: run_at must be a future ISO datetime.
4. Use conversation history for follow-up requests like "schedule it", "add it to calendar", or "set the reminder".
5. Keep Google Calendar, meetings, schedules, and reminders in CALENDAR. Do not treat them like generic web browsing.
6. If the user asks for reminders or scheduled jobs, prefer LIST_REMINDERS or SET_REMINDER instead of creating a calendar event.

Respond EXACTLY:
ACTION: <action_name>
ARGS: <json_args>
EXPLANATION: Brief description""",
                    ),
                    Message(
                        role=MessageRole.USER,
                        content=(
                            f"Current date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                            f"CONVERSATION HISTORY:\n{history_text}\n\n"
                            f"CURRENT REQUEST: {user_message}"
                        )
                        if history_text
                        else f"Current date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\nUser says: {user_message}",
                    ),
                ]

                llm_result = await self.llm.generate_response(messages)
                llm_response = llm_result.get('response', '')

                import json as json_module

                for line in llm_response.split('\n'):
                    line = line.strip()
                    if line.startswith('ACTION:'):
                        action = line.split(':', 1)[1].strip().upper()
                    elif line.startswith('ARGS:'):
                        try:
                            args = json_module.loads(line.split(':', 1)[1].strip())
                        except Exception:
                            args = {}
                    elif line.startswith('EXPLANATION:'):
                        explanation = line.split(':', 1)[1].strip()

            output = ""

            if action == 'LIST_EVENTS':
                days = args.get('days', 7)
                max_results = args.get('max_results', 10)
                now = datetime.now(timezone.utc)
                events = calendar_service.list_events(
                    user_id,
                    time_min=now,
                    time_max=now + timedelta(days=days),
                    max_results=max_results,
                )

                if events:
                    output = f"{len(events)} events in the next {days} days:\n\n"
                    for index, event in enumerate(events, 1):
                        output += f"{index}. {event['summary']}\n"
                        if event['location']:
                            output += f"   Location: {event['location']}\n"
                        output += f"   {event['start']} -> {event['end']}\n"
                        if event['attendees']:
                            output += f"   Attendees: {', '.join(a['email'] for a in event['attendees'][:3])}\n"
                        output += "\n"
                else:
                    output = f"No events in the next {days} days."

            elif action == 'TODAY_EVENTS':
                events = calendar_service.get_today_events(user_id)
                if events:
                    output = f"Today's schedule ({len(events)} events):\n\n"
                    for index, event in enumerate(events, 1):
                        output += f"{index}. {event['summary']} - {event['start']} to {event['end']}\n"
                        if event['location']:
                            output += f"   Location: {event['location']}\n"
                else:
                    output = "No events scheduled for today."

            elif action == 'CREATE_EVENT':
                summary = args.get('summary', '')
                start = args.get('start_time', '')
                end = args.get('end_time', '')

                if summary and start and end:
                    event = calendar_service.create_event(
                        user_id=user_id,
                        summary=summary,
                        start_time=start,
                        end_time=end,
                        description=args.get('description', ''),
                        location=args.get('location', ''),
                        attendees=args.get('attendees'),
                        reminder_minutes=args.get('reminder_minutes', 15),
                        time_zone=args.get('time_zone', 'Asia/Kolkata'),
                    )
                    output = (
                        "Event created.\n\n"
                        f"{event['summary']}\n"
                        f"{event['start']} -> {event['end']}\n"
                        f"Open in Google Calendar: {event['html_link']}"
                    )
                else:
                    output = "Missing information. Please provide the event title, start time, and end time."

            elif action == 'UPDATE_EVENT':
                event_id = args.get('event_id', '')
                updates = args.get('updates', {})
                if event_id and updates:
                    result = calendar_service.update_event(user_id=user_id, event_id=event_id, updates=updates)
                    output = f"Event updated successfully: {result.get('summary', event_id)}"
                else:
                    output = "Missing event id or update details."

            elif action == 'DELETE_EVENT':
                event_id = args.get('event_id', '')
                if event_id:
                    calendar_service.delete_event(user_id, event_id)
                    output = "Event deleted."
                else:
                    output = "No event ID provided."

            elif action == 'SET_REMINDER':
                description = args.get('description', '')
                run_at_str = args.get('run_at', '')
                if description and run_at_str:
                    run_at = datetime.fromisoformat(run_at_str)
                    if run_at.tzinfo is None:
                        run_at = run_at.replace(tzinfo=timezone.utc)
                    scheduler_service.add_reminder(
                        user_id=user_id,
                        description=description,
                        run_at=run_at,
                    )
                    output = f"Reminder set.\n\n{description}\n{run_at.strftime('%Y-%m-%d %H:%M')}"
                else:
                    output = "Please provide both what to remind you about and when."

            elif action == 'LIST_REMINDERS':
                jobs = scheduler_service.list_jobs(user_id)
                if jobs:
                    output = f"{len(jobs)} active reminders or jobs:\n\n"
                    for job in jobs:
                        output += f"- {job['description']} ({job['type']}) - next: {job['next_run'] or 'N/A'}\n"
                else:
                    output = "No active reminders or scheduled jobs."

            else:
                events = calendar_service.get_today_events(user_id)
                if events:
                    output = "Today's schedule:\n\n"
                    for index, event in enumerate(events, 1):
                        output += f"{index}. {event['summary']} - {event['start']}\n"
                else:
                    output = "Nothing is on your calendar today."

            if explanation:
                output = f"*{explanation}*\n\n{output}"

            state['current_output'] = output
            state['final_output'] = output
            state['agent_path'].append('calendar_specialist')
            state['success'] = True

            logger.info(f"Calendar action complete: {action or 'DEFAULT'}")

        except PermissionError as exc:
            state['current_output'] = f"Permission error: {str(exc)}"
            state['final_output'] = state['current_output']
            state['agent_path'].append('calendar_specialist')
            state['success'] = False
        except Exception as exc:
            logger.error(f"Calendar agent error: {exc}")
            state['current_output'] = f"Calendar error: {str(exc)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Calendar agent error: {str(exc)}")
            state['success'] = False

        return state

    async def _general_agent_node(self, state: AgentState) -> AgentState:
        """General assistant"""
        logger.info("💬 General Agent processing...")
        
        # If a security guard or rate limiter already set the output, skip processing
        blocked_tags = {'security_guard', 'rate_limiter'}
        if blocked_tags & set(state.get('agent_path', [])) and state.get('final_output'):
            return state
        
        try:
            messages = []
            
            if state.get('user_context'):
                messages.append(Message(
                    role=MessageRole.SYSTEM,
                    content=state['user_context']
                ))
            
            for msg in state.get('conversation_history', [])[-3:]:
                if isinstance(msg, dict):
                    role = MessageRole.USER if msg.get('role') == 'user' else MessageRole.ASSISTANT
                    messages.append(Message(role=role, content=msg.get('content', '')))
            
            messages.append(Message(
                role=MessageRole.USER,
                content=state['user_message']
            ))
            
            result = await self.llm.generate_response(messages)
            
            state['current_output'] = result['response']
            state['final_output'] = result['response']
            state['agent_path'].append('general_assistant')
            state['success'] = True
            
            logger.info("✅ General response complete")
        
        except Exception as e:
            logger.error(f"❌ General agent error: {e}")
            state['current_output'] = f"I encountered an error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"General agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    # ===== CROSS-AGENT ROUTING =====
    
    async def _cross_agent_check_node(self, state: AgentState) -> AgentState:
        """Detect if current agent's output requires another agent to act.
        E.g., email mentions a meeting → trigger calendar agent."""
        
        # Only check once to avoid infinite loops
        if state.get('metadata', {}).get('_cross_agent_done'):
            return state
        
        current_output = state.get('current_output', '')
        user_message = state.get('user_message', '').lower()
        agent_path = state.get('agent_path', [])
        
        cross_target = None
        cross_context = None
        
        # Email → Calendar: detect meeting/event references
        if 'email_specialist' in agent_path and 'calendar_specialist' not in agent_path:
            calendar_keywords = ['meeting', 'appointment', 'schedule', 'event', 'calendar',
                                'invite', 'rsvp', 'conference', 'call at', 'session']
            combined = f"{user_message} {current_output.lower()}"
            if any(kw in combined for kw in calendar_keywords):
                # Check if user explicitly wants calendar action
                if any(phrase in user_message for phrase in [
                    'add to calendar', 'create event', 'schedule', 'add event',
                    'put on calendar', 'block time', 'set reminder'
                ]):
                    cross_target = 'calendar'
                    cross_context = f"Based on this email context, create a calendar event: {current_output[:500]}"
        
        # Calendar → Email: detect "invite" or "send" in calendar context
        if 'calendar_specialist' in agent_path and 'email_specialist' not in agent_path:
            if any(phrase in user_message for phrase in [
                'send invite', 'email attendees', 'notify', 'send confirmation'
            ]):
                cross_target = 'email'
                cross_context = f"Send an email about this calendar event: {current_output[:500]}"
        
        # General/Email/Calendar → Web Autonomous: detect web lookup needs
        if 'web_autonomous_agent' not in agent_path:
            web_triggers = [
                'look it up', 'search online', 'check the web', 'find online',
                'browse for', 'google it', 'search for more', 'find the link'
            ]
            if any(phrase in user_message for phrase in web_triggers):
                cross_target = 'web_autonomous'
                cross_context = f"Search the web based on this context: {current_output[:500]}"
        
        if cross_target and cross_context:
            logger.info(f"🔗 Cross-agent routing: → {cross_target}")
            state['metadata'] = {**state.get('metadata', {}), '_cross_agent_done': True,
                                 '_cross_target': cross_target, '_cross_context': cross_context}
            # Prepend original output context so the next agent can use it
            state['user_message'] = cross_context
        else:
            state['metadata'] = {**state.get('metadata', {}), '_cross_agent_done': True}
        
        return state
    
    def _cross_agent_decision(self, state: AgentState) -> str:
        """Route to another agent or finish."""
        target = state.get('metadata', {}).get('_cross_target')
        if target in ('calendar', 'email', 'web_autonomous'):
            logger.info(f"🔗 Chaining to {target} agent")
            # Clear the target so we don't loop
            state['metadata'].pop('_cross_target', None)
            return target
        return "done"
    
    async def _save_memory_node(self, state: AgentState) -> AgentState:
        """Save to BOTH SQL and Vector memory with fact extraction"""
        logger.info("💾 Saving to memory...")
        
        try:
            user_message = state['user_message']
            assistant_response = state.get('final_output', '')
            user_id = state['user_id']
            conversation_id = state['conversation_id']
            
            # 1. Save user message to SQL + Vector
            self.memory_service.save_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role='user',
                content=user_message,
                metadata={'context_used': bool(state.get('user_context'))}
            )
            
            # 2. Save assistant response to SQL + Vector
            self.memory_service.save_message(
                conversation_id=conversation_id,
                user_id=user_id,
                role='assistant',
                content=assistant_response,
                metadata={
                    'task_type': state.get('task_type'),
                    'agent_path': state.get('agent_path', []),
                    'success': state.get('success', True)
                }
            )
            
            # 3. Save combined exchange for better semantic retrieval + extract facts
            self.memory_service.save_conversation_exchange(
                conversation_id=conversation_id,
                user_id=user_id,
                user_message=user_message,
                assistant_response=assistant_response,
                metadata={'task_type': state.get('task_type')}
            )
            
            # 4. Learn from behavior (SQL preferences)
            if state.get('task_type') == 'coding' and state.get('success'):
                self.memory_service.learn_from_behavior(
                    user_id=user_id,
                    task_data={
                        'task_type': 'coding',
                        'language': state.get('language'),
                        'success': True
                    }
                )
            
            state['agent_path'].append('memory_saver')
            logger.info("✅ Saved to memory")
        
        except Exception as e:
            logger.error(f"❌ Memory save error: {e}")
        
        return state
    
    def _build_initial_state(
        self,
        user_message: str,
        user_id: str,
        conversation_id: str,
        max_iterations: int,
        message_callback: Optional[Callable] = None,
    ) -> AgentState:
        """Build a fresh orchestration state for the new planner/executor flow."""
        initial_state: AgentState = {
            'user_message': user_message,
            'user_id': user_id,
            'conversation_id': conversation_id,
            'user_context': '',
            'conversation_history': [],
            'task_type': 'general',
            'confidence': 0.5,
            'routing_reason': '',
            'agent_path': [],
            'current_output': '',
            'iteration': 1,
            'max_iterations': max_iterations,
            'errors': [],
            'final_output': '',
            'success': False,
            'metadata': {
                'original_user_message': user_message,
            },
            'code': '',
            'files': {},
            'language': '',
            'desktop_action': '',
            'desktop_result': {},
            'web_screenshots': [],
            'web_actions': [],
            'web_current_url': '',
            'web_permission_needed': {},
        }
        if message_callback:
            initial_state['metadata']['_message_callback'] = message_callback
        return initial_state

    def _detect_channel(self, user_id: str) -> str:
        """Infer request channel from user identity."""
        if user_id.startswith("telegram_"):
            return "telegram"
        if user_id.startswith("web_"):
            return "web"
        return "api"

    async def _emit_progress(
        self,
        message_callback: Optional[Callable],
        event_type: str,
        message: str,
        **data: Any,
    ) -> None:
        """Forward orchestration lifecycle events to transport layers."""
        if not message_callback:
            return
        payload = {"type": event_type, "message": message}
        payload.update(data)
        try:
            await message_callback(payload)
        except Exception as exc:
            logger.warning(f"⚠️ Progress callback failed for {event_type}: {exc}")

    def _assess_approval(self, user_message: str, task_type: str) -> ApprovalRequest:
        """Apply guarded auto-run rules at the orchestrator layer."""
        message_lower = user_message.lower()

        destructive_keywords = [
            "delete", "remove", "erase", "format", "shutdown", "reboot",
            "kill process", "trash", "send email", "purchase", "buy",
            "checkout", "payment", "submit", "post publicly", "deploy to production",
            "git push", "git commit", "revoke", "archive email",
        ]
        desktop_sensitive = ["type password", "enter password", "close all", "delete file"]

        requires_approval = any(keyword in message_lower for keyword in destructive_keywords)
        if task_type == "desktop" and any(keyword in message_lower for keyword in desktop_sensitive):
            requires_approval = True

        if requires_approval:
            return ApprovalRequest(
                required=True,
                approval_level="confirm",
                reason="The request includes a destructive or externally committed action.",
            )

        return ApprovalRequest(required=False, approval_level="none", reason="")

    def _build_task_analysis(
        self,
        envelope: TaskEnvelope,
        state: AgentState,
        approval_override: bool = False,
    ) -> TaskAnalysis:
        """Normalize routing, permissions, and risk into a single analysis object."""
        from app.services.permission_service import permission_service

        routing = router_agent.classify_task(
            user_message=envelope.user_message,
            user_context=state.get('user_context', ''),
            conversation_history=state.get('conversation_history', []),
        )
        task_type = routing.get('task_type', 'general')
        approval = self._assess_approval(envelope.user_message, task_type)
        if approval_override:
            approval = ApprovalRequest(required=False, approval_level="none", reason="")

        allowed, access_reason = permission_service.check_agent_access(envelope.user_id, task_type)
        rate_allowed, rate_reason = permission_service.check_rate_limit(envelope.user_id)

        blocked = False
        blocked_reason = ""
        if not rate_allowed:
            blocked = True
            blocked_reason = rate_reason
        elif not allowed:
            blocked = True
            blocked_reason = access_reason

        risk_level = "low"
        if approval.required:
            risk_level = "high"
        elif task_type in {"desktop", "email", "calendar", "web_autonomous"}:
            risk_level = "medium"

        return TaskAnalysis(
            task_type=task_type,
            confidence=routing.get('confidence', 0.0),
            reasoning=routing.get('reasoning', ''),
            risk_level=risk_level,
            required_capabilities=[task_type],
            blocked=blocked,
            blocked_reason=blocked_reason,
            approval=approval,
        )

    def _requires_research_step(self, user_message: str, task_type: str) -> bool:
        """Detect when a coding request should explicitly gather web context first."""
        if task_type != "coding":
            return False
        research_keywords = [
            "research", "docs", "documentation", "latest", "compare",
            "find the best", "look up", "search online", "github", "website",
            "api reference", "read about",
        ]
        message_lower = user_message.lower()
        return any(keyword in message_lower for keyword in research_keywords)

    def _build_execution_plan(
        self,
        envelope: TaskEnvelope,
        analysis: TaskAnalysis,
    ) -> ExecutionPlan:
        """Create an explicit step-by-step plan before execution starts."""
        steps: List[PlanStep] = []

        def _make_step(
            index: int,
            agent_type: str,
            goal: str,
            message: str,
            depends_on: Optional[List[str]] = None,
            approval_level: str = "none",
            success_criteria: str = "",
            fallback_strategy: str = "",
        ) -> PlanStep:
            return PlanStep(
                step_id=f"step-{index}",
                agent_type=agent_type,  # type: ignore[arg-type]
                goal=goal,
                inputs={"message": message},
                depends_on=depends_on or [],
                approval_level=approval_level,  # type: ignore[arg-type]
                success_criteria=success_criteria,
                fallback_strategy=fallback_strategy,
            )

        if not analysis.blocked:
            if self._requires_research_step(envelope.user_message, analysis.task_type):
                steps.append(_make_step(
                    1,
                    "web_autonomous",
                    "Research the requested implementation on the web before coding.",
                    f"Research documentation and implementation guidance for: {envelope.user_message}",
                    approval_level="none",
                    success_criteria="Relevant references or findings are gathered.",
                    fallback_strategy="Proceed with implementation using existing context if research is unavailable.",
                ))
                steps.append(_make_step(
                    2,
                    "coding",
                    "Implement the requested solution using the gathered context.",
                    envelope.user_message,
                    depends_on=["step-1"],
                    approval_level=analysis.approval.approval_level if analysis.approval.required else "none",
                    success_criteria="Code, files, and execution artifacts are produced.",
                    fallback_strategy="Return a concrete blocking error with partial output if implementation fails.",
                ))
            else:
                steps.append(_make_step(
                    1,
                    analysis.task_type,
                    f"Execute the user's {analysis.task_type.replace('_', ' ')} request.",
                    envelope.user_message,
                    approval_level=analysis.approval.approval_level if analysis.approval.required else "none",
                    success_criteria="The specialist completes the request or returns a clear blocking error.",
                    fallback_strategy="Escalate to the general agent with the failure context if needed.",
                ))

        if analysis.approval.required:
            analysis.approval.affected_steps = [
                step.step_id for step in steps if step.approval_level != "none"
            ]

        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            task_type=analysis.task_type,  # type: ignore[arg-type]
            summary=f"Analyze the request, then execute it through the {analysis.task_type} specialist flow.",
            steps=steps,
            requires_approval=analysis.approval.required,
            approval_request=analysis.approval,
        )

    def _extract_artifacts(self, state: AgentState) -> Dict[str, Any]:
        """Collect serializable artifacts from the current state."""
        metadata = state.get('metadata', {})
        safe_metadata = {
            key: value
            for key, value in metadata.items()
            if not callable(value) and not key.startswith('_')
        }
        return {
            'files': state.get('files') or {},
            'language': state.get('language') or '',
            'project_path': safe_metadata.get('project_path', ''),
            'project_type': safe_metadata.get('project_type', ''),
            'server_running': safe_metadata.get('server_running', False),
            'server_url': safe_metadata.get('server_url', ''),
            'web_screenshots': state.get('web_screenshots', []),
            'web_actions': state.get('web_actions', []),
            'web_current_url': state.get('web_current_url', ''),
            'desktop_action': state.get('desktop_action', ''),
            'desktop_result': state.get('desktop_result', {}),
        }

    async def _execute_plan_step(self, step: PlanStep, state: AgentState) -> AgentState:
        """Dispatch a single plan step to the correct specialist node."""
        step_message = step.inputs.get("message", state.get('user_message', ''))
        state['user_message'] = step_message
        state['task_type'] = step.agent_type

        handlers = {
            'coding': self._code_agent_node,
            'desktop': self._desktop_agent_node,
            'web': self._web_agent_node,
            'web_autonomous': self._web_autonomous_agent_node,
            'email': self._email_agent_node,
            'calendar': self._calendar_agent_node,
            'general': self._general_agent_node,
        }
        handler = handlers.get(step.agent_type, self._general_agent_node)
        return await handler(state)

    def _build_handoff_step(
        self,
        current_step: PlanStep,
        target_agent: str,
        handoff_context: str,
        plan: ExecutionPlan,
    ) -> PlanStep:
        """Create a follow-up step after a specialist requests a handoff."""
        return PlanStep(
            step_id=f"step-{len(plan.steps) + 1}",
            agent_type=target_agent,  # type: ignore[arg-type]
            goal=f"Continue execution via {target_agent.replace('_', ' ')} handoff.",
            inputs={"message": handoff_context},
            depends_on=[current_step.step_id],
            approval_level="none",
            success_criteria="The downstream specialist completes the requested follow-up.",
            fallback_strategy="Return the prior result and report that the handoff could not be completed.",
        )

    async def _execute_plan(
        self,
        state: AgentState,
        plan: ExecutionPlan,
        message_callback: Optional[Callable] = None,
    ) -> tuple[AgentState, List[ExecutionTraceEvent], Dict[str, Any]]:
        """Run the explicit plan, capturing step traces and orchestrator-managed handoffs."""
        execution_trace: List[ExecutionTraceEvent] = []
        approval_state = {"status": "not_required", "reason": ""}
        completed_steps: set[str] = set()
        step_index = 0

        while step_index < len(plan.steps):
            step = plan.steps[step_index]
            if any(dep not in completed_steps for dep in step.depends_on):
                step_index += 1
                continue

            if step.approval_level != "none":
                step.status = "blocked"
                approval_state = {
                    "status": "required",
                    "reason": plan.approval_request.reason if plan.approval_request else "Approval required.",
                    "affected_steps": plan.approval_request.affected_steps if plan.approval_request else [step.step_id],
                }
                execution_trace.append(ExecutionTraceEvent(
                    event_type="approval_required",
                    phase="execution",
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    success=False,
                    message=approval_state["reason"],
                    data={"approval_state": approval_state},
                ))
                await self._emit_progress(
                    message_callback,
                    "approval_required",
                    approval_state["reason"],
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    approval_state=approval_state,
                )
                break

            step.status = "running"
            execution_trace.append(ExecutionTraceEvent(
                event_type="step_started",
                phase="execution",
                step_id=step.step_id,
                agent_type=step.agent_type,
                success=None,
                message=step.goal,
                data={"inputs": step.inputs},
            ))
            await self._emit_progress(
                message_callback,
                "step_started",
                step.goal,
                step_id=step.step_id,
                agent_type=step.agent_type,
                step=step.model_dump(),
            )

            state = await self._execute_plan_step(step, state)
            step.status = "completed" if state.get('success') else "failed"

            artifacts = self._extract_artifacts(state)
            execution_trace.append(ExecutionTraceEvent(
                event_type="step_completed",
                phase="execution",
                step_id=step.step_id,
                agent_type=step.agent_type,
                success=state.get('success', False),
                message=state.get('current_output', '')[:500],
                data={"artifacts": artifacts},
            ))
            await self._emit_progress(
                message_callback,
                "step_completed",
                state.get('current_output', '')[:500] or f"Completed {step.agent_type}",
                step_id=step.step_id,
                agent_type=step.agent_type,
                success=state.get('success', False),
                artifacts=artifacts,
                step=step.model_dump(),
            )

            if not state.get('success', False):
                break

            completed_steps.add(step.step_id)

            # Allow specialists to request another specialist through the orchestrator.
            state['metadata'].pop('_cross_agent_done', None)
            state['metadata'].pop('_cross_target', None)
            state['metadata'].pop('_cross_context', None)
            state = await self._cross_agent_check_node(state)
            cross_target = state.get('metadata', {}).get('_cross_target')
            cross_context = state.get('metadata', {}).get('_cross_context')

            if cross_target and cross_context:
                handoff_step = self._build_handoff_step(step, cross_target, cross_context, plan)
                plan.steps.append(handoff_step)
                handoff = AgentHandoff(
                    from_agent=step.agent_type,
                    to_agent=cross_target,  # type: ignore[arg-type]
                    reason="Specialist requested a follow-up action.",
                    context=cross_context,
                )
                execution_trace.append(ExecutionTraceEvent(
                    event_type="handoff",
                    phase="execution",
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    success=True,
                    message=f"Handoff to {cross_target}",
                    data={"handoff": handoff.model_dump(), "new_step": handoff_step.model_dump()},
                ))
                await self._emit_progress(
                    message_callback,
                    "handoff",
                    f"Routing follow-up work to {cross_target.replace('_', ' ')}.",
                    handoff=handoff.model_dump(),
                    step=handoff_step.model_dump(),
                )
                state['metadata'].pop('_cross_target', None)
                state['metadata'].pop('_cross_context', None)

            step_index += 1

        return state, execution_trace, approval_state

    async def _persist_interaction(
        self,
        envelope: TaskEnvelope,
        response_text: str,
        task_type: str,
        agent_path: List[str],
        success: bool,
        execution_trace: List[ExecutionTraceEvent],
    ) -> None:
        """Persist the user request and assistant response once per orchestrated turn."""
        try:
            trace_payload = [event.model_dump() for event in execution_trace]
            self.memory_service.save_message(
                conversation_id=envelope.conversation_id,
                user_id=envelope.user_id,
                role='user',
                content=envelope.user_message,
                metadata={'channel': envelope.channel},
            )
            self.memory_service.save_message(
                conversation_id=envelope.conversation_id,
                user_id=envelope.user_id,
                role='assistant',
                content=response_text,
                metadata={
                    'task_type': task_type,
                    'agent_path': agent_path,
                    'success': success,
                    'execution_trace': trace_payload,
                },
            )
            self.memory_service.save_conversation_exchange(
                conversation_id=envelope.conversation_id,
                user_id=envelope.user_id,
                user_message=envelope.user_message,
                assistant_response=response_text,
                metadata={'task_type': task_type},
            )
            self.memory_service.save_task(
                envelope.user_id,
                {
                    'conversation_id': envelope.conversation_id,
                    'task_type': task_type,
                    'description': envelope.user_message,
                    'agent_used': 'planner_executor',
                    'iterations': len([event for event in execution_trace if event.event_type == 'step_completed']),
                    'success': success,
                }
            )
        except Exception as exc:
            logger.error(f"❌ Unified persistence error: {exc}")

    # ===== PUBLIC INTERFACE =====
    
    # ===== PUBLIC INTERFACE =====
    
    async def process(
        self,
        user_message: str,
        user_id: str,
        conversation_id: str,
        max_iterations: int = 3,
        message_callback: Optional[Callable] = None,
        approval_override: bool = False,
    ) -> Dict[str, Any]:
        """Process a request through the unified planner/executor architecture."""
        logger.info(f"🚀 Processing: '{user_message[:50]}...'")

        state = self._build_initial_state(
            user_message=user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
            message_callback=message_callback,
        )
        state['metadata']['approval_override'] = approval_override
        envelope = TaskEnvelope(
            user_message=user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            channel=self._detect_channel(user_id),
        )

        try:
            await self._emit_progress(
                message_callback,
                "analysis_started",
                "Analyzing the request and building execution context.",
                channel=envelope.channel,
            )

            state = await self._load_context_node(state)
            analysis = self._build_task_analysis(
                envelope,
                state,
                approval_override=approval_override,
            )
            state['task_type'] = analysis.task_type
            state['confidence'] = analysis.confidence
            state['routing_reason'] = analysis.reasoning

            plan = self._build_execution_plan(envelope, analysis)
            await self._emit_progress(
                message_callback,
                "plan_ready",
                plan.summary,
                plan=plan.model_dump(),
                task_type=analysis.task_type,
                confidence=analysis.confidence,
            )

            execution_trace: List[ExecutionTraceEvent] = [
                ExecutionTraceEvent(
                    event_type="analysis_completed",
                    phase="analysis",
                    message=analysis.reasoning or f"Detected {analysis.task_type} task.",
                    agent_type=analysis.task_type,
                    success=not analysis.blocked,
                    data={"analysis": analysis.model_dump()},
                )
            ]

            approval_state = {
                "status": "not_required",
                "reason": "",
                "affected_steps": [],
            }

            if analysis.blocked:
                state['success'] = False
                state['final_output'] = analysis.blocked_reason
            else:
                state, execution_events, approval_state = await self._execute_plan(
                    state,
                    plan,
                    message_callback=message_callback,
                )
                execution_trace.extend(execution_events)

                if approval_state["status"] == "required":
                    from app.services.approval_service import approval_service

                    approval_request = approval_service.create_request(
                        user_id=envelope.user_id,
                        conversation_id=envelope.conversation_id,
                        user_message=envelope.user_message,
                        reason=approval_state["reason"],
                        channel=envelope.channel,
                        affected_steps=approval_state.get("affected_steps", []),
                        task_type=analysis.task_type,
                    )
                    approval_state["approval_id"] = approval_request.approval_id
                    state['success'] = False
                    state['final_output'] = (
                        "Approval is required before I continue.\n\n"
                        f"Reason: {approval_state['reason']}"
                    )
                else:
                    state['final_output'] = state.get('final_output') or state.get('current_output', '')

            artifacts = self._extract_artifacts(state)
            safe_metadata = {
                key: value
                for key, value in state.get('metadata', {}).items()
                if not callable(value) and not key.startswith('_')
            }

            response = {
                'success': state.get('success', False),
                'output': state.get('final_output', ''),
                'task_type': analysis.task_type,
                'confidence': analysis.confidence,
                'agent_path': state.get('agent_path', []),
                'code': state.get('code'),
                'files': state.get('files'),
                'language': state.get('language'),
                'file_path': artifacts.get('project_path', ''),
                'project_structure': None,
                'main_file': None,
                'project_type': artifacts.get('project_type', ''),
                'server_running': artifacts.get('server_running', False),
                'server_url': artifacts.get('server_url', ''),
                'server_port': None,
                'plan': plan.model_dump(),
                'execution_trace': [event.model_dump() for event in execution_trace],
                'approval_state': approval_state,
                'artifacts': artifacts,
                'metadata': {
                    'channel': envelope.channel,
                    'routing_reason': analysis.reasoning,
                    'risk_level': analysis.risk_level,
                    'iterations': len([event for event in execution_trace if event.event_type == 'step_completed']),
                    'errors': state.get('errors', []),
                    'web_screenshots': state.get('web_screenshots', []),
                    'web_actions_count': len(state.get('web_actions', [])),
                    'web_current_url': state.get('web_current_url', ''),
                    **safe_metadata,
                },
            }

            await self._persist_interaction(
                envelope=envelope,
                response_text=response['output'],
                task_type=analysis.task_type,
                agent_path=response['agent_path'],
                success=response['success'],
                execution_trace=execution_trace,
            )
            await self._emit_progress(
                message_callback,
                "final",
                response['output'][:500] if response['output'] else "Execution complete.",
                result=response,
            )

            logger.info(f"✅ Completed with {len(response['agent_path'])} agent hops")
            return response

        except Exception as e:
            logger.error(f"❌ Graph execution error: {e}")
            return {
                'success': False,
                'output': f"System error: {str(e)}",
                'task_type': 'general',
                'confidence': 0.0,
                'agent_path': ['error'],
                'plan': None,
                'execution_trace': [],
                'approval_state': {'status': 'not_required', 'reason': '', 'affected_steps': []},
                'artifacts': {},
                'metadata': {'error': str(e)},
            }


# Global instance
langgraph_orchestrator = LangGraphOrchestrator()


# """
# LangGraph Multi-Agent Orchestrator
# State graph-based orchestration with memory and reflection
# """
# from typing import Dict, Any, TypedDict, List, Annotated
# from datetime import datetime, timezone
# import operator
# from loguru import logger

# from langgraph.graph import StateGraph, END
# from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# from app.agents.router_agent import router_agent
# from app.services.context_builder import context_builder
# from app.services.memory_service import memory_service
# from app.core.llm import llm_adapter


# # ===== STATE DEFINITION =====

# class AgentState(TypedDict):
#     """
#     Shared state across all graph nodes
#     """
#     # Input
#     user_message: str
#     user_id: str
#     conversation_id: str
    
#     # Context (built before routing)
#     user_context: str  # Personalized context from memory
#     conversation_history: List[Dict]  # Recent messages
    
#     # Routing
#     task_type: str
#     confidence: float
#     routing_reason: str
    
#     # Agent outputs
#     agent_path: Annotated[List[str], operator.add]  # Track which agents ran
#     current_output: str
    
#     # Execution tracking
#     iteration: int
#     max_iterations: int
#     errors: Annotated[List[str], operator.add]
    
#     # Final output
#     final_output: str
#     success: bool
#     metadata: Dict[str, Any]
    
#     # Code generation specific
#     code: str
#     files: Dict[str, str]
#     language: str
    
#     # Reflection
#     needs_improvement: bool
#     improvement_suggestions: List[str]


# # ===== GRAPH NODES =====

# class LangGraphOrchestrator:
#     """
#     LangGraph-based multi-agent orchestrator with memory
#     """
    
#     def __init__(self):
#         self.context_builder = context_builder
#         self.memory_service = memory_service
#         self.llm = llm_adapter
        
#         # Build the graph
#         self.graph = self._build_graph()
        
#         logger.info("✅ LangGraph Orchestrator initialized")
    
#     def _build_graph(self) -> StateGraph:
#         """Build the agent state graph"""
        
#         # Create graph
#         workflow = StateGraph(AgentState)
        
#         # Add nodes
#         workflow.add_node("load_context", self._load_context_node)
#         workflow.add_node("route", self._route_node)
#         workflow.add_node("code_agent", self._code_agent_node)
#         workflow.add_node("desktop_agent", self._desktop_agent_node)
#         workflow.add_node("general_agent", self._general_agent_node)
#         workflow.add_node("reflect", self._reflect_node)
#         workflow.add_node("save_memory", self._save_memory_node)
        
#         # Define edges
#         workflow.set_entry_point("load_context")
        
#         # Context → Router
#         workflow.add_edge("load_context", "route")
        
#         # Router → Specialists (conditional)
#         workflow.add_conditional_edges(
#             "route",
#             self._route_decision,
#             {
#                 "coding": "code_agent",
#                 "desktop": "desktop_agent",
#                 "general": "general_agent"
#             }
#         )
        
#         # Specialists → Reflect
#         workflow.add_edge("code_agent", "reflect")
#         workflow.add_edge("desktop_agent", "reflect")
#         workflow.add_edge("general_agent", "reflect")
        
#         # Reflect → Save Memory or Loop (conditional)
#         workflow.add_conditional_edges(
#             "reflect",
#             self._reflect_decision,
#             {
#                 "save": "save_memory",
#                 "improve": "route"  # Loop back for improvement
#             }
#         )
        
#         # Save Memory → END
#         workflow.add_edge("save_memory", END)
        
#         return workflow.compile()
    
#     # ===== NODE IMPLEMENTATIONS =====
    
#     async def _load_context_node(self, state: AgentState) -> AgentState:
#         """Load user context and conversation history"""
#         logger.info("📚 Loading context...")
        
#         try:
#             # Build personalized context
#             user_context = self.context_builder.build_user_context(
#                 user_id=state['user_id'],
#                 current_message=state['user_message'],
#                 conversation_id=state['conversation_id']
#             )
            
#             # Load recent conversation
#             conversation_history = self.memory_service.get_conversation_history(
#                 state['conversation_id'], limit=10
#             )
            
#             state['user_context'] = user_context
#             state['conversation_history'] = conversation_history
#             state['agent_path'] = ['context_loader']
            
#             logger.info(f"✅ Loaded context ({len(user_context)} chars)")
        
#         except Exception as e:
#             logger.error(f"❌ Error loading context: {e}")
#             state['errors'] = [f"Context loading error: {str(e)}"]
        
#         return state
    
#     async def _route_node(self, state: AgentState) -> AgentState:
#         """Route to appropriate specialist agent"""
#         logger.info("🎯 Routing task...")
        
#         try:
#             # Classify with user context
#             classification = router_agent.classify_task(
#                 user_message=state['user_message'],
#                 user_context=state['user_context']
#             )
            
#             state['task_type'] = classification['task_type']
#             state['confidence'] = classification['confidence']
#             state['routing_reason'] = classification.get('reasoning', '')
#             state['agent_path'].append('router')
            
#             logger.info(
#                 f"📍 Routed to: {classification['task_type']} "
#                 f"({classification['confidence']:.0%})"
#             )
        
#         except Exception as e:
#             logger.error(f"❌ Routing error: {e}")
#             state['task_type'] = 'general'  # Fallback
#             state['errors'].append(f"Routing error: {str(e)}")
        
#         return state
    
#     def _route_decision(self, state: AgentState) -> str:
#         """Decide which agent to use"""
#         return state.get('task_type', 'general')
    
#     async def _code_agent_node(self, state: AgentState) -> AgentState:
#         """Code generation specialist"""
#         logger.info("💻 Code Agent processing...")
        
#         try:
#             # Import here to avoid circular dependency
#             from app.agents.code_specialist_agent import code_specialist
            
#             # Build messages with context
#             messages = self._build_messages_with_context(state)
            
#             # Call code specialist
#             # (Your existing code specialist logic)
#             result = await code_specialist.generate_code(
#                 description=state['user_message'],
#                 conversation_history=messages
#             )
            
#             state['current_output'] = result.get('explanation', '')
#             state['code'] = result.get('code', '')
#             state['files'] = result.get('files', {})
#             state['language'] = result.get('language', '')
#             state['agent_path'].append('code_specialist')
#             state['success'] = result.get('success', True)
        
#         except Exception as e:
#             logger.error(f"❌ Code agent error: {e}")
#             state['current_output'] = f"Code generation failed: {str(e)}"
#             state['errors'].append(f"Code agent error: {str(e)}")
#             state['success'] = False
        
#         return state
    
#     async def _desktop_agent_node(self, state: AgentState) -> AgentState:
#         """Desktop automation specialist"""
#         logger.info("🖥️ Desktop Agent processing...")
        
#         try:
#             # Build messages with context
#             messages = self._build_messages_with_context(state)
            
#             # Import skills
#             from app.skills.manager import skill_manager
#             from app.skills.executor import skill_executor
            
#             # Get desktop tools
#             tools = skill_manager.get_skills_for_llm()
#             formatted_tools = [{"type": "function", "function": t} for t in tools]
            
#             # Call LLM with tools
#             llm_result = await self.llm.generate_response(
#                 messages, tools=formatted_tools
#             )
            
#             # Execute tools if requested
#             if llm_result.get("tool_calls"):
#                 import json
#                 for tool_call in llm_result["tool_calls"]:
#                     skill_name = tool_call["function"]["name"]
#                     args = json.loads(tool_call["function"]["arguments"])
                    
#                     result = await skill_executor.execute_skill(
#                         skill_name, args, state['user_id']
#                     )
                    
#                     logger.info(f"🔧 Executed: {skill_name}")
            
#             state['current_output'] = llm_result.get('response', '')
#             state['agent_path'].append('desktop_specialist')
#             state['success'] = True
        
#         except Exception as e:
#             logger.error(f"❌ Desktop agent error: {e}")
#             state['current_output'] = f"Desktop automation failed: {str(e)}"
#             state['errors'].append(f"Desktop agent error: {str(e)}")
#             state['success'] = False
        
#         return state
    
#     async def _general_agent_node(self, state: AgentState) -> AgentState:
#         """General conversation agent"""
#         logger.info("💬 General Agent processing...")
        
#         try:
#             # Build messages with context
#             messages = self._build_messages_with_context(state)
            
#             # Call LLM
#             llm_result = await self.llm.generate_response(messages)
            
#             state['current_output'] = llm_result.get('response', '')
#             state['agent_path'].append('general_assistant')
#             state['success'] = True
        
#         except Exception as e:
#             logger.error(f"❌ General agent error: {e}")
#             state['current_output'] = f"Response generation failed: {str(e)}"
#             state['errors'].append(f"General agent error: {str(e)}")
#             state['success'] = False
        
#         return state
    
#     async def _reflect_node(self, state: AgentState) -> AgentState:
#         """Reflect on output quality and decide if improvement needed"""
#         logger.info("🤔 Reflecting on output...")
        
#         try:
#             # Simple reflection logic (can be enhanced with LLM)
#             needs_improvement = False
#             suggestions = []
            
#             # Check for errors
#             if state.get('errors'):
#                 needs_improvement = True
#                 suggestions.append("Fix errors that occurred")
            
#             # Check if iteration limit reached
#             if state.get('iteration', 0) >= state.get('max_iterations', 3):
#                 needs_improvement = False  # Stop iteration
            
#             # Check if output is empty
#             if not state.get('current_output'):
#                 needs_improvement = True
#                 suggestions.append("Generate actual output")
            
#             state['needs_improvement'] = needs_improvement
#             state['improvement_suggestions'] = suggestions
#             state['agent_path'].append('reflection')
            
#             if needs_improvement:
#                 logger.warning(f"⚠️ Needs improvement: {suggestions}")
#                 state['iteration'] = state.get('iteration', 0) + 1
#             else:
#                 logger.info("✅ Output quality acceptable")
#                 state['final_output'] = state['current_output']
        
#         except Exception as e:
#             logger.error(f"❌ Reflection error: {e}")
#             state['needs_improvement'] = False
#             state['final_output'] = state.get('current_output', '')
        
#         return state
    
#     def _reflect_decision(self, state: AgentState) -> str:
#         """Decide whether to save or improve"""
#         if state.get('needs_improvement', False):
#             return "improve"
#         else:
#             return "save"
    
#     async def _save_memory_node(self, state: AgentState) -> AgentState:
#         """Save interaction to memory"""
#         logger.info("💾 Saving to memory...")
        
#         try:
#             # Save user message to SQL
#             self.memory_service.save_message(
#                 conversation_id=state['conversation_id'],
#                 user_id=state['user_id'],
#                 role='user',
#                 content=state['user_message'],
#                 metadata={'context_used': bool(state.get('user_context'))}
#             )
            
#             # Save assistant response to SQL
#             self.memory_service.save_message(
#                 conversation_id=state['conversation_id'],
#                 user_id=state['user_id'],
#                 role='assistant',
#                 content=state.get('final_output', ''),
#                 metadata={
#                     'task_type': state.get('task_type'),
#                     'agent_path': state.get('agent_path', []),
#                     'success': state.get('success', True)
#                 }
#             )
            
#             # Extract and save insights (every 5 messages)
#             messages = self.memory_service.get_conversation_history(
#                 state['conversation_id']
#             )
#             if len(messages) % 5 == 0:
#                 self.context_builder.extract_and_save_insights(
#                     user_id=state['user_id'],
#                     conversation_id=state['conversation_id']
#                 )
            
#             # Learn from behavior
#             if state.get('task_type') == 'coding':
#                 self.memory_service.learn_from_behavior(
#                     user_id=state['user_id'],
#                     task_data={
#                         'task_type': 'coding',
#                         'language': state.get('language'),
#                         'success': state.get('success', True)
#                     }
#                 )
            
#             state['agent_path'].append('memory_saver')
#             logger.info("✅ Saved to memory")
        
#         except Exception as e:
#             logger.error(f"❌ Memory save error: {e}")
#             state['errors'].append(f"Memory save error: {str(e)}")
        
#         return state
    
#     # ===== HELPER METHODS =====
    
#     def _build_messages_with_context(self, state: AgentState) -> List:
#         """Build message list with context for LLM"""
#         from app.models import Message, MessageRole
        
#         messages = []
        
#         # Add system message with context
#         if state.get('user_context'):
#             messages.append(Message(
#                 role=MessageRole.SYSTEM,
#                 content=state['user_context']
#             ))
        
#         # Add conversation history
#         for msg in state.get('conversation_history', [])[-5:]:
#             role = MessageRole.USER if msg['role'] == 'user' else MessageRole.ASSISTANT
#             messages.append(Message(
#                 role=role,
#                 content=msg['content']
#             ))
        
#         # Add current message
#         messages.append(Message(
#             role=MessageRole.USER,
#             content=state['user_message']
#         ))
        
#         return messages
    
#     # ===== PUBLIC INTERFACE =====
    
#     async def process(
#         self,
#         user_message: str,
#         user_id: str,
#         conversation_id: str,
#         max_iterations: int = 3,
#         message_callback: Any = None
#     ) -> Dict:
#         """
#         Process user message through the agent graph
        
#         Args:
#             user_message: User's message
#             user_id: User identifier
#             conversation_id: Conversation ID
#             max_iterations: Max improvement iterations
#             message_callback: Callback for progress updates
            
#         Returns:
#             Final state dict
#         """
#         logger.info(f"🚀 Processing: '{user_message[:50]}...'")
        
#         # Initialize state
#         initial_state = AgentState(
#             user_message=user_message,
#             user_id=user_id,
#             conversation_id=conversation_id,
#             user_context="",
#             conversation_history=[],
#             task_type="general",
#             confidence=0.0,
#             routing_reason="",
#             agent_path=[],
#             current_output="",
#             iteration=0,
#             max_iterations=max_iterations,
#             errors=[],
#             final_output="",
#             success=False,
#             metadata={},
#             code="",
#             files={},
#             language="",
#             needs_improvement=False,
#             improvement_suggestions=[]
#         )
        
#         # Run the graph
#         try:
#             final_state = await self.graph.ainvoke(initial_state)
            
#             # Format response
#             response = {
#                 "success": final_state.get('success', True),
#                 "output": final_state.get('final_output', ''),
#                 "task_type": final_state.get('task_type'),
#                 "confidence": final_state.get('confidence', 0.0),
#                 "agent_path": final_state.get('agent_path', []),
#                 "code": final_state.get('code'),
#                 "files": final_state.get('files'),
#                 "language": final_state.get('language'),
#                 "metadata": {
#                     "iterations": final_state.get('iteration', 0),
#                     "errors": final_state.get('errors', []),
#                     "context_used": bool(final_state.get('user_context'))
#                 }
#             }
            
#             logger.info(f"✅ Completed with {len(final_state.get('agent_path', []))} steps")
#             return response
        
#         except Exception as e:
#             logger.error(f"❌ Graph execution error: {e}")
#             return {
#                 "success": False,
#                 "output": f"System error: {str(e)}",
#                 "task_type": "error",
#                 "confidence": 0.0,
#                 "agent_path": ["error"],
#                 "metadata": {"error": str(e)}
#             }


# # Global instance
# langgraph_orchestrator = LangGraphOrchestrator()


