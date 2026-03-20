"""
LangGraph Multi-Agent Orchestrator - SonarBot
Persistent memory across conversations and restarts.
All agents: coding, desktop, web, general
"""
from typing import Dict, Any, TypedDict, List, Annotated, Optional, Callable
from datetime import datetime, timezone, timedelta
import operator
from loguru import logger

from langgraph.graph import StateGraph, END

from app.agents.router_agent import router_agent
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
            # so Discord threads (same user, different thread IDs) share context
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
- open_url: {"url": "youtube"} — Opens a website name or URL in the system's default browser. Supports well-known names like youtube, google, github, etc.
- open_special_folder: {"folder": "desktop|documents|downloads|pictures|onedrive_root|onedrive_desktop|onedrive_documents|onedrive_pictures"} — Opens a well-known folder directly.
- open_path: {"path": "C:\\path\\folder_or_file"} — Opens any file or folder path directly.
- take_screenshot: {"region": null, "monitor": 1, "format": "base64"}
- mouse_move: {"x": int, "y": int, "duration": 0.3}
- mouse_click: {"x": int, "y": int, "button": "left|right", "clicks": 1}
- type_text: {"text": "string", "interval": 0.05}
- press_key: {"key": "string"}
- press_hotkey: {"keys": ["ctrl", "c"]}
- open_application: {"name": "app_name", "wait": false}
- list_windows: {}
- focus_window: {"title": "window_title"}
- read_screen_text: {"language": "eng", "region": null}

Respond EXACTLY in this format (one action per line):
ACTION: skill_name | {"arg1": "value1", "arg2": "value2"}
ACTION: skill_name | {"arg1": "value1"}
EXPLANATION: Brief description of what you're doing

Examples:
User: "open youtube"
ACTION: open_url | {"url": "youtube"}
EXPLANATION: Opening YouTube in the default browser

User: "open my pictures folder"
ACTION: open_special_folder | {"folder": "pictures"}
EXPLANATION: Opening your pictures folder directly

User: "open chrome"
ACTION: open_application | {"name": "chrome", "wait": false}
EXPLANATION: Opening Google Chrome browser

User: "take a screenshot"
ACTION: take_screenshot | {"monitor": 1, "format": "base64"}
EXPLANATION: Taking a screenshot of your desktop

User: "type hello world in notepad"
ACTION: open_application | {"name": "notepad", "wait": true}
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
                    actions = [('take_screenshot', {'monitor': 1, 'format': 'base64'})]
                    explanation = 'Taking a screenshot'
                elif any(kw in msg_lower for kw in ['open ', 'launch ', 'start ']):
                    for kw in ['open ', 'launch ', 'start ']:
                        if kw in msg_lower:
                            app_name = msg_lower.split(kw, 1)[1].strip().split()[0] if msg_lower.split(kw, 1)[1].strip() else ''
                            if app_name:
                                actions = [('open_application', {'name': app_name, 'wait': False})]
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
                    if skill == 'screenshot':
                        output_parts.append("✅ Screenshot captured successfully")
                    elif skill == 'app_launcher':
                        output_parts.append(f"✅ Application launched: {r['args'].get('app', 'unknown')}")
                    elif skill == 'keyboard_control':
                        action = r['args'].get('action', '')
                        if action == 'type':
                            output_parts.append("✅ Typed text successfully")
                        elif action == 'press':
                            output_parts.append(f"✅ Key pressed: {r['args'].get('key', '')}")
                        elif action == 'hotkey':
                            output_parts.append(f"✅ Hotkey pressed: {'+'.join(r['args'].get('keys', []))}")
                        else:
                            output_parts.append("✅ Keyboard action completed")
                    elif skill == 'mouse_control':
                        output_parts.append(f"✅ Mouse action completed: {r['args'].get('action', 'click')}")
                    elif skill == 'window_manager':
                        action = r['args'].get('action', '')
                        if action == 'list' and isinstance(result_data, dict):
                            windows = result_data.get('windows', [])
                            output_parts.append(f"✅ Found {len(windows)} windows")
                            for w in windows[:10]:
                                if isinstance(w, dict):
                                    output_parts.append(f"  - {w.get('title', 'Unknown')}")
                        else:
                            output_parts.append(f"✅ Window action completed: {action}")
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
    
    async def _email_agent_node(self, state: AgentState) -> AgentState:
        """Email specialist - Gmail operations via LLM intent parsing"""
        logger.info("📧 Email Agent processing...")
        
        try:
            from app.services.gmail_service import gmail_service
            from app.services.google_auth_service import google_auth_service
            
            user_id = state['user_id']
            user_message = state['user_message']
            conversation_history = state.get('conversation_history', [])
            
            # Check if Google is connected
            if not google_auth_service.is_connected(user_id):
                state['current_output'] = (
                    "📧 **Google Account Not Connected**\n\n"
                    "To use email features, please connect your Google account first:\n"
                    "Click **Connect Google** in the settings panel, or say 'connect google'.\n\n"
                    "Once connected, I can:\n"
                    "- Read your inbox\n"
                    "- Send emails (with your approval)\n"
                    "- Search emails\n"
                    "- Check unread count\n"
                    "- Archive/trash messages"
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('email_specialist')
                state['success'] = False
                return state
            
            # Build conversation context so LLM knows about previous drafts
            history_text = ""
            if conversation_history:
                recent = conversation_history[-6:]  # Last 6 messages for context
                for msg in recent:
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    # Truncate long messages but keep draft IDs visible
                    if len(content) > 500:
                        content = content[:500] + "..."
                    history_text += f"{role}: {content}\n"
            
            # Use LLM to parse email intent
            messages = [
                Message(
                    role=MessageRole.SYSTEM,
                    content="""You are an Email Agent. Parse the user's request into a Gmail action.

Available actions:
- LIST_EMAILS: List inbox emails. Args: {"query": "", "max_results": 10}
- READ_EMAIL: Read specific email. Args: {"message_id": "..."}
- SEARCH_EMAILS: Search with query. Args: {"query": "from:alice subject:report", "max_results": 10}
- COMPOSE_EMAIL: Draft an email (NOT send). Args: {"to": "email@example.com", "subject": "...", "body": "..."}
- SEND_DRAFT: Send a previously composed draft. Args: {"draft_id": "..."}
- UNREAD_COUNT: Check unread count. Args: {}
- MARK_READ: Mark email as read. Args: {"message_id": "..."}
- ARCHIVE: Archive email. Args: {"message_id": "..."}
- TRASH: Trash email. Args: {"message_id": "..."}

CRITICAL RULES:
1. For COMPOSE_EMAIL: Create a professional email body. NEVER send directly — always draft first.
2. For SEND_DRAFT: When user says "send it", "yes send", "go ahead", "send the email", "send the draft" — use SEND_DRAFT. You do NOT need to provide the draft_id — the system will extract it automatically from conversation history. Just use ARGS: {}
3. For SEARCH: Use Gmail query syntax (from:, to:, subject:, is:unread, after:, before:, has:attachment, in:sent, in:inbox)
4. If user just says "check email" or "any new email" → LIST_EMAILS with query "is:unread"
5. If user asks about "last sent email", "emails I sent", "my sent mail" → use SEARCH_EMAILS with query "in:sent" and max_results 1-5.
6. For READ_EMAIL: ONLY use a real message_id from a previous LIST_EMAILS/SEARCH_EMAILS result. NEVER invent or guess a message_id.
7. If user asks about a specific email but you don't have its message_id, use SEARCH_EMAILS first to find it.

Examples:
User: "send it" (after composing a draft)
ACTION: SEND_DRAFT
ARGS: {}
EXPLANATION: Sending the previously composed draft

User: "what was the last email I sent"
ACTION: SEARCH_EMAILS
ARGS: {"query": "in:sent", "max_results": 1}
EXPLANATION: Finding the last sent email

Respond EXACTLY in this format:
ACTION: <action_name>
ARGS: <json_args>
EXPLANATION: <brief description>"""
                ),
                Message(
                    role=MessageRole.USER,
                    content=f"CONVERSATION HISTORY:\n{history_text}\n\nCURRENT REQUEST: {user_message}"
                    if history_text else user_message
                )
            ]
            
            llm_result = await self.llm.generate_response(messages)
            llm_response = llm_result.get('response', '')
            
            import json as json_module
            action = ""
            args = {}
            explanation = ""
            
            for line in llm_response.split('\n'):
                line = line.strip()
                if line.startswith('ACTION:'):
                    action = line.split(':', 1)[1].strip().upper()
                elif line.startswith('ARGS:'):
                    try:
                        args = json_module.loads(line.split(':', 1)[1].strip())
                    except:
                        args = {}
                elif line.startswith('EXPLANATION:'):
                    explanation = line.split(':', 1)[1].strip()
            
            # Execute the parsed action
            output = ""
            
            if action == 'LIST_EMAILS' or action == 'SEARCH_EMAILS':
                query = args.get('query', '')
                max_results = args.get('max_results', 10)
                emails = gmail_service.list_emails(user_id, query=query, max_results=max_results)
                
                if emails:
                    output = f"📧 **{len(emails)} emails found**"
                    if query:
                        output += f" (query: {query})"
                    output += "\n\n"
                    for i, email in enumerate(emails, 1):
                        unread = "🔵 " if email['is_unread'] else ""
                        output += f"{i}. {unread}**{email['subject']}**\n"
                        output += f"   From: {email['from']} | {email['date']}\n"
                        output += f"   {email['snippet'][:100]}\n\n"
                else:
                    output = "📭 No emails found matching your criteria."
            
            elif action == 'READ_EMAIL':
                msg_id = args.get('message_id', '')
                # Validate: real Gmail message IDs are hex strings, not words
                if msg_id and len(msg_id) > 5 and ' ' not in msg_id and not any(w in msg_id.lower() for w in ['last', 'sent', 'first', 'recent', 'email', 'mail', 'message']):
                    email = gmail_service.read_email(user_id, msg_id)
                    output = f"📧 **{email['subject']}**\n"
                    output += f"From: {email['from']}\n"
                    output += f"To: {email['to']}\n"
                    output += f"Date: {email['date']}\n\n"
                    output += f"{email['body'][:2000]}"
                    if email['attachments']:
                        output += f"\n\n📎 Attachments: {', '.join(a['filename'] for a in email['attachments'])}"
                else:
                    # Fallback: search for it instead
                    logger.warning(f"⚠️ Invalid message_id '{msg_id}', falling back to search")
                    emails = gmail_service.list_emails(user_id, query='in:sent', max_results=1)
                    if emails:
                        first = emails[0]
                        email = gmail_service.read_email(user_id, first['id'])
                        output = f"📧 **Your last sent email:**\n\n"
                        output += f"**{email['subject']}**\n"
                        output += f"From: {email['from']}\n"
                        output += f"To: {email['to']}\n"
                        output += f"Date: {email['date']}\n\n"
                        output += f"{email['body'][:2000]}"
                    else:
                        output = "📭 No sent emails found."
            
            elif action == 'COMPOSE_EMAIL':
                to = args.get('to', '')
                subject = args.get('subject', '')
                body = args.get('body', '')
                
                if to and subject:
                    draft = gmail_service.compose_draft(
                        user_id=user_id, to=to, subject=subject, body=body
                    )
                    output = (
                        f"📝 **Email Draft Created**\n\n"
                        f"**To:** {to}\n"
                        f"**Subject:** {subject}\n"
                        f"**Body:**\n{body}\n\n"
                        f"---\n"
                        f"⚠️ **This email has NOT been sent yet.** It's saved as a draft.\n"
                        f"Say **\"send it\"** or **\"yes, send the email\"** to send it.\n"
                        f"Say **\"cancel\"** or **\"don't send\"** to discard.\n\n"
                        f"_Draft ID: {draft['draft_id']}_"
                    )
                else:
                    output = "❌ Missing required fields. Please provide: to (email), subject, and what you want to say."
            
            elif action == 'SEND_DRAFT':
                # Always extract draft_id from conversation history (don't rely on LLM)
                import re
                draft_id = ''
                if conversation_history:
                    for msg in reversed(conversation_history):
                        content = msg.get('content', '')
                        match = re.search(r'Draft ID:\s*(\S+)', content)
                        if match:
                            draft_id = match.group(1).strip('_').strip('*')
                            logger.info(f"📧 Found draft_id from history: {draft_id}")
                            break
                
                # Fallback: use LLM-provided draft_id only if it looks like a real ID
                if not draft_id:
                    llm_draft_id = args.get('draft_id', '')
                    if llm_draft_id and len(llm_draft_id) > 5 and ' ' not in llm_draft_id:
                        draft_id = llm_draft_id
                
                if draft_id:
                    result = gmail_service.send_draft(user_id, draft_id)
                    output = f"✅ **Email Sent Successfully!**\n\nMessage ID: {result.get('message_id', 'sent')}"
                else:
                    output = "❌ Could not find a draft to send. Please compose an email first."
            
            elif action == 'UNREAD_COUNT':
                count = gmail_service.get_unread_count(user_id)
                output = f"📬 You have **{count}** unread email{'s' if count != 1 else ''}."
            
            elif action == 'MARK_READ':
                msg_id = args.get('message_id', '')
                if msg_id:
                    gmail_service.mark_as_read(user_id, msg_id)
                    output = "✅ Email marked as read."
                else:
                    output = "❌ No message ID provided."
            
            elif action == 'ARCHIVE':
                msg_id = args.get('message_id', '')
                if msg_id:
                    gmail_service.archive_email(user_id, msg_id)
                    output = "✅ Email archived."
                else:
                    output = "❌ No message ID provided."
            
            elif action == 'TRASH':
                msg_id = args.get('message_id', '')
                if msg_id:
                    gmail_service.trash_email(user_id, msg_id)
                    output = "🗑️ Email moved to trash."
                else:
                    output = "❌ No message ID provided."
            
            else:
                # Default: check unread + show recent
                count = gmail_service.get_unread_count(user_id)
                emails = gmail_service.list_emails(user_id, query="is:unread", max_results=5)
                output = f"📬 You have **{count}** unread emails.\n\n"
                if emails:
                    for i, email in enumerate(emails, 1):
                        output += f"{i}. **{email['subject']}** from {email['from']}\n"
            
            if explanation:
                output = f"*{explanation}*\n\n{output}"
            
            state['current_output'] = output
            state['final_output'] = output
            state['agent_path'].append('email_specialist')
            state['success'] = True
            
            logger.info(f"✅ Email action complete: {action}")
        
        except PermissionError as e:
            state['current_output'] = f"🔒 {str(e)}"
            state['final_output'] = state['current_output']
            state['agent_path'].append('email_specialist')
            state['success'] = False
        except Exception as e:
            logger.error(f"❌ Email agent error: {e}")
            state['current_output'] = f"Email error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Email agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _calendar_agent_node(self, state: AgentState) -> AgentState:
        """Calendar specialist - Google Calendar operations via LLM intent parsing"""
        logger.info("📅 Calendar Agent processing...")
        
        try:
            from app.services.calendar_service import calendar_service
            from app.services.scheduler_service import scheduler_service
            from app.services.google_auth_service import google_auth_service
            
            user_id = state['user_id']
            user_message = state['user_message']
            
            # Check if Google is connected
            if not google_auth_service.is_connected(user_id):
                state['current_output'] = (
                    "📅 **Google Account Not Connected**\n\n"
                    "To use calendar features, please connect your Google account first:\n"
                    "Click **Connect Google** in the settings panel.\n\n"
                    "Once connected, I can:\n"
                    "- Show your schedule\n"
                    "- Create events\n"
                    "- Set reminders\n"
                    "- Check free/busy times"
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('calendar_specialist')
                state['success'] = False
                return state
            
            # Use LLM to parse calendar intent
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

IMPORTANT:
- For CREATE_EVENT: Always include both start_time and end_time in ISO format (without timezone offset — the time_zone field handles it). Default time_zone is "Asia/Kolkata".
- If user says "tomorrow at 3pm", calculate the actual date.
- For SET_REMINDER: run_at should be a future datetime in ISO format.
- Current date context will be in the user message.

Respond EXACTLY:
ACTION: <action_name>
ARGS: <json_args>
EXPLANATION: Brief description"""
                ),
                Message(
                    role=MessageRole.USER,
                    content=f"Current date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. User says: {user_message}"
                )
            ]
            
            llm_result = await self.llm.generate_response(messages)
            llm_response = llm_result.get('response', '')
            
            import json as json_module
            action = ""
            args = {}
            explanation = ""
            
            for line in llm_response.split('\n'):
                line = line.strip()
                if line.startswith('ACTION:'):
                    action = line.split(':', 1)[1].strip().upper()
                elif line.startswith('ARGS:'):
                    try:
                        args = json_module.loads(line.split(':', 1)[1].strip())
                    except:
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
                    max_results=max_results
                )
                
                if events:
                    output = f"📅 **{len(events)} events in the next {days} days:**\n\n"
                    for i, evt in enumerate(events, 1):
                        output += f"{i}. **{evt['summary']}**\n"
                        output += f"   📍 {evt['location']}\n" if evt['location'] else ""
                        output += f"   🕐 {evt['start']} → {evt['end']}\n"
                        if evt['attendees']:
                            output += f"   👥 {', '.join(a['email'] for a in evt['attendees'][:3])}\n"
                        output += "\n"
                else:
                    output = f"📭 No events in the next {days} days."
            
            elif action == 'TODAY_EVENTS':
                events = calendar_service.get_today_events(user_id)
                if events:
                    output = f"📅 **Today's Schedule ({len(events)} events):**\n\n"
                    for i, evt in enumerate(events, 1):
                        output += f"{i}. **{evt['summary']}** — {evt['start']} to {evt['end']}\n"
                        if evt['location']:
                            output += f"   📍 {evt['location']}\n"
                else:
                    output = "📭 No events scheduled for today. You're free!"
            
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
                        f"✅ **Event Created!**\n\n"
                        f"📌 **{event['summary']}**\n"
                        f"🕐 {event['start']} → {event['end']}\n"
                        f"🔗 [Open in Google Calendar]({event['html_link']})"
                    )
                else:
                    output = "❌ Missing info. Please provide: event title, start time, and end time."
            
            elif action == 'DELETE_EVENT':
                event_id = args.get('event_id', '')
                if event_id:
                    calendar_service.delete_event(user_id, event_id)
                    output = "🗑️ Event deleted."
                else:
                    output = "❌ No event ID provided."
            
            elif action == 'SET_REMINDER':
                desc = args.get('description', '')
                run_at_str = args.get('run_at', '')
                if desc and run_at_str:
                    run_at = datetime.fromisoformat(run_at_str)
                    if run_at.tzinfo is None:
                        run_at = run_at.replace(tzinfo=timezone.utc)
                    result = scheduler_service.add_reminder(
                        user_id=user_id,
                        description=desc,
                        run_at=run_at,
                    )
                    output = f"⏰ **Reminder Set!**\n\n📌 {desc}\n🕐 {run_at.strftime('%Y-%m-%d %H:%M')}"
                else:
                    output = "❌ Please provide what to remind you about and when."
            
            elif action == 'LIST_REMINDERS':
                jobs = scheduler_service.list_jobs(user_id)
                if jobs:
                    output = f"⏰ **{len(jobs)} active reminders/jobs:**\n\n"
                    for j in jobs:
                        output += f"- **{j['description']}** ({j['type']}) — next: {j['next_run'] or 'N/A'}\n"
                else:
                    output = "📭 No active reminders or scheduled jobs."
            
            else:
                # Default: show today's schedule
                events = calendar_service.get_today_events(user_id)
                if events:
                    output = f"📅 **Today's Schedule:**\n\n"
                    for i, evt in enumerate(events, 1):
                        output += f"{i}. **{evt['summary']}** — {evt['start']}\n"
                else:
                    output = "📭 Nothing on your calendar today."
            
            if explanation:
                output = f"*{explanation}*\n\n{output}"
            
            state['current_output'] = output
            state['final_output'] = output
            state['agent_path'].append('calendar_specialist')
            state['success'] = True
            
            logger.info(f"✅ Calendar action complete: {action}")
        
        except PermissionError as e:
            state['current_output'] = f"🔒 {str(e)}"
            state['final_output'] = state['current_output']
            state['agent_path'].append('calendar_specialist')
            state['success'] = False
        except Exception as e:
            logger.error(f"❌ Calendar agent error: {e}")
            state['current_output'] = f"Calendar error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Calendar agent error: {str(e)}")
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
    
    # ===== PUBLIC INTERFACE =====
    
    async def process(
        self,
        user_message: str,
        user_id: str,
        conversation_id: str,
        max_iterations: int = 3,
        message_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Process user message through graph"""
        logger.info(f"🚀 Processing: '{user_message[:50]}...'")
        
        # Initialize state
        initial_state = {
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
            'metadata': {},
            'code': '',
            'files': {},
            'language': '',
            'desktop_action': '',
            'desktop_result': {},
            'web_screenshots': [],
            'web_actions': [],
            'web_current_url': '',
            'web_permission_needed': {}
        }
        
        # Pass message callback via metadata for agents that need it
        if message_callback:
            initial_state['metadata']['_message_callback'] = message_callback
        
        try:
            # Execute graph
            result = await self.graph.ainvoke(initial_state)
            
            # Build response — drop non-serializable keys
            extra_metadata = {
                k: v for k, v in result.get('metadata', {}).items()
                if not callable(v) and not k.startswith('_')
            }
            response = {
                'success': result.get('success', False),
                'output': result.get('final_output', ''),
                'task_type': result.get('task_type'),
                'confidence': result.get('confidence'),
                'agent_path': result.get('agent_path', []),
                'code': result.get('code'),
                'files': result.get('files'),
                'language': result.get('language'),
                'file_path': extra_metadata.get('project_path', ''),
                'project_structure': None,
                'main_file': None,
                'project_type': extra_metadata.get('project_type', ''),
                'server_running': extra_metadata.get('server_running', False),
                'server_url': extra_metadata.get('server_url', ''),
                'server_port': None,
                'metadata': {
                    'routing_reason': result.get('routing_reason'),
                    'iterations': result.get('iteration', 1),
                    'errors': result.get('errors', []),
                    'web_screenshots': result.get('web_screenshots', []),
                    'web_actions_count': len(result.get('web_actions', [])),
                    'web_current_url': result.get('web_current_url', ''),
                    **extra_metadata
                }
            }
            
            step_count = len(result.get('agent_path', []))
            logger.info(f"✅ Completed with {step_count} steps")
            
            return response
        
        except Exception as e:
            logger.error(f"❌ Graph execution error: {e}")
            return {
                'success': False,
                'output': f"System error: {str(e)}",
                'task_type': 'general',
                'confidence': 0.0,
                'agent_path': ['error'],
                'metadata': {'error': str(e)}
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