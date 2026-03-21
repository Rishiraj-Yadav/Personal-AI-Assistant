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
from app.services.desktop_execution_service import desktop_execution_service
from app.services.enhanced_memory_service import enhanced_memory_service
from app.services.workflow_library_service import workflow_library_service
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
    browser_state: Dict[str, Any]


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
            # ── Fast path: check if the desktop agent is waiting for an answer ──
            from app.skills.desktop_bridge import DesktopBridgeSkill
            bridge = DesktopBridgeSkill()
            user_id = state.get('user_id', 'default')
            
            is_pending = await bridge.check_pending_state(user_id)
            if is_pending:
                logger.info("🎯 Routing to web_autonomous_agent because user has a pending input state")
                state['task_type'] = 'web_autonomous'
                state['confidence'] = 1.0
                state['routing_reason'] = "User is answering a pending request from the browser agent."
                state['agent_path'].append('router')
                return state

            browser_status = await bridge.get_browser_status(user_id)
            browser_result = browser_status.get("result") or {}
            browser_running = bool(
                browser_status.get("success")
                and browser_result.get("running")
                and browser_result.get("connected")
            )
            if browser_running and self._looks_page_relative_follow_up(state.get('user_message', '')):
                logger.info("ðŸŽ¯ Routing to web_autonomous_agent because the live browser is already open")
                state['task_type'] = 'web_autonomous'
                state['confidence'] = 0.95
                state['routing_reason'] = (
                    "A live browser session is already open and the new message looks page-relative."
                )
                state['agent_path'].append('router')
                return state

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
        logger.info("Desktop Agent processing...")

        user_id = state.get('user_id', '')

        from app.services.permission_service import permission_service
        perms = permission_service.get_permissions(user_id)
        desktop_access = perms.get('desktop_access', 'none')

        if desktop_access == 'virtual':
            return await self._virtual_desktop_handler(state)

        try:
            from app.skills.desktop_bridge import desktop_bridge

            desktop_available = await desktop_bridge.check_connection()
            if not desktop_available:
                state['current_output'] = (
                    "Desktop Agent is not running.\n\n"
                    "Start it from the desktop-agent folder with `python desktop_agent.py`."
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('desktop_specialist')
                state['success'] = False
                state['desktop_action'] = 'agent_unavailable'
                state['desktop_result'] = {'status': 'desktop_agent_not_running'}
                return state

            step_hint = state.get('metadata', {}).get('_current_step')
            message_callback = state.get('metadata', {}).get('_message_callback')
            desktop_execution = await desktop_execution_service.execute(
                user_message=state['user_message'],
                user_id=user_id,
                user_context=state.get('user_context', ''),
                step_hint=step_hint,
                message_callback=message_callback,
                approval_granted=bool(state.get('metadata', {}).get('approval_override')),
                resume_context=state.get('metadata', {}).get('_resume_context'),
            )

            desktop_plan = desktop_execution.get('plan')
            desktop_trace = desktop_execution.get('trace') or []
            desktop_result = desktop_execution.get('desktop_result') or {}
            desktop_approval_state = desktop_execution.get('approval_state') or {}
            desktop_clarification_state = desktop_execution.get('clarification_state') or {}

            state['current_output'] = desktop_execution.get('output', '')
            state['final_output'] = state['current_output']
            state['agent_path'].append('desktop_specialist')
            state['success'] = desktop_execution.get('success', False)
            state['desktop_action'] = 'executed' if state['success'] else 'failed'
            state['desktop_result'] = desktop_result
            state['metadata'] = {
                **state.get('metadata', {}),
                'desktop_plan': desktop_plan.model_dump() if hasattr(desktop_plan, 'model_dump') else desktop_plan,
                'desktop_execution_trace': [
                    event.model_dump() if hasattr(event, 'model_dump') else event
                    for event in desktop_trace
                ],
                'desktop_evidence': desktop_result.get('evidence', []),
                '_approval_state': desktop_approval_state,
                '_clarification_state': desktop_clarification_state,
                '_specialist_trace_events': desktop_trace,
            }
            if desktop_plan and getattr(desktop_plan, 'workflow_key', None):
                state['metadata']['workflow_key'] = desktop_plan.workflow_key
                state['metadata']['workflow_name'] = desktop_plan.workflow_name
                state['metadata']['workflow_source'] = desktop_plan.workflow_source

            logger.info(
                f"Desktop execution finished with "
                f"{desktop_result.get('steps_completed', 0)}/{desktop_result.get('steps_total', 0)} verified steps"
            )

        except Exception as e:
            logger.error(f"Desktop agent error: {e}")
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
        """Web specialist — real internet search, fetch, and LLM summarisation."""
        logger.info("🌐 Web Agent processing...")

        try:
            # ── Step 1: DuckDuckGo search ──────────────────────────────────
            search_results = []
            try:
                from duckduckgo_search import DDGS
                with DDGS() as ddgs:
                    raw = list(ddgs.text(
                        state['user_message'],
                        region="in-en",
                        max_results=5,
                    ))
                search_results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", r.get("link", "")),
                        "snippet": r.get("body", r.get("snippet", ""))[:400],
                    }
                    for r in raw
                ]
                logger.info(f"🔍 DDG returned {len(search_results)} results")
            except ImportError:
                logger.warning("⚠️ duckduckgo-search not installed — falling back to LLM only.")
            except Exception as ddg_err:
                logger.warning(f"⚠️ DDG search failed: {ddg_err}")

            # ── Step 2: Fetch page content for top 2 results ───────────────
            fetched_pages = []
            if search_results:
                try:
                    import httpx
                    async with httpx.AsyncClient(
                        timeout=8.0,
                        follow_redirects=True,
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"
                            )
                        },
                    ) as client:
                        for result in search_results[:2]:
                            url = result.get("url", "")
                            if not url:
                                continue
                            try:
                                resp = await client.get(url)
                                resp.raise_for_status()
                                # Strip HTML tags simply
                                import re as _re
                                text = _re.sub(r"<[^>]+>", " ", resp.text)
                                text = _re.sub(r"\s{3,}", "\n\n", text).strip()
                                fetched_pages.append({
                                    "url": url,
                                    "title": result.get("title", ""),
                                    "content": text[:4000],
                                })
                            except Exception as fetch_err:
                                logger.debug(f"Fetch skipped {url}: {fetch_err}")
                    logger.info(f"📄 Fetched {len(fetched_pages)} pages")
                except ImportError:
                    logger.warning("⚠️ httpx not installed — using snippets only.")
                except Exception as http_err:
                    logger.warning(f"⚠️ HTTP fetch error: {http_err}")

            # ── Step 3: Build LLM context ──────────────────────────────────
            context_parts = []

            if search_results:
                context_parts.append("## Search Results\n")
                for i, r in enumerate(search_results, 1):
                    context_parts.append(
                        f"{i}. **{r['title']}** ({r['url']})\n   {r['snippet']}\n"
                    )

            if fetched_pages:
                context_parts.append("\n## Full Page Content\n")
                for page in fetched_pages:
                    context_parts.append(
                        f"### {page['title']}\nURL: {page['url']}\n\n{page['content'][:3000]}\n"
                    )

            web_context = "\n".join(context_parts) if context_parts else ""

            # ── Step 4: LLM synthesis ──────────────────────────────────────
            messages = []

            if state.get('user_context'):
                messages.append(Message(
                    role=MessageRole.SYSTEM,
                    content=state['user_context'],
                ))

            system_content = (
                "You are a Web Research Agent. You have searched the internet for the user's query "
                "and retrieved the following results. Use this information to give a comprehensive, "
                "accurate, and concise answer. Always cite the source URLs.\n\n"
            )
            if web_context:
                system_content += web_context
            else:
                system_content += (
                    "NOTE: Live search was unavailable. Answer based on your training data "
                    "and clearly indicate the information may not be up-to-date."
                )

            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=system_content,
            ))

            for msg in state.get('conversation_history', [])[-3:]:
                if isinstance(msg, dict):
                    role = MessageRole.USER if msg.get('role') == 'user' else MessageRole.ASSISTANT
                    messages.append(Message(role=role, content=msg.get('content', '')))

            messages.append(Message(
                role=MessageRole.USER,
                content=state['user_message'],
            ))

            result = await self.llm.generate_response(messages)

            state['current_output'] = result['response']
            state['final_output'] = result['response']
            state['agent_path'].append('web_specialist')
            state['success'] = True
            state['metadata'] = {
                **state.get('metadata', {}),
                'web_search_used': bool(search_results),
                'web_results_count': len(search_results),
                'web_pages_fetched': len(fetched_pages),
            }

            logger.info(
                f"✅ Web response complete "
                f"({len(search_results)} results, {len(fetched_pages)} pages fetched)"
            )

        except Exception as e:
            logger.error(f"❌ Web agent error: {e}")
            state['current_output'] = f"Web search error: {str(e)}"
            state['final_output'] = state['current_output']
            state['errors'].append(f"Web agent error: {str(e)}")
            state['success'] = False

        return state


    async def _web_autonomous_agent_node(self, state: AgentState) -> AgentState:
        """
        Autonomous Web Agent — Perplexity Comet-style browser automation.

        Strategy:
        1. Try the Desktop Agent's live browser first (visible on user's screen).
        2. If the Desktop Agent is unavailable, fall back to the headless
           web_agent_service running in Docker.
        3. If the live browser reports a sensitive-action-blocked error,
           create an approval request so the user can approve/deny via the
           Web UI or Telegram.
        """
        logger.info("🌐 Web Autonomous Agent processing...")

        user_id = state['user_id']
        user_message = state['user_message']

        def _live_browser_looks_failed(actions: list, response_text: str) -> bool:
            """True if the host live-browser runtime failed and headless fallback should take over."""
            blob = (response_text or "").lower()
            phrases = (
                "failed to open browser",
                "browser failed",
                "could not open the browser",
                "playwright is not installed",
                "no usable browser",
                "could not launch",
                "browser launch failed",
                "underlying issue",
                "cannot resolve",
            )
            if any(p in blob for p in phrases):
                return True

            fatal_codes = {"browser_launch_failed", "connection_failed", "playwright_unavailable"}
            action_error_codes = {
                str(a.get("error_code"))
                for a in (actions or [])
                if a.get("error_code")
            }
            if action_error_codes & fatal_codes:
                return True

            opens = [
                a for a in (actions or [])
                if a.get("tool") in {"open_browser", "browser"}
                and (a.get("tool") != "browser" or (a.get("args") or {}).get("command") in {"start", "open", "navigate"})
            ]
            if opens:
                if any(a.get("success") for a in opens):
                    return False
                if any(str(a.get("error_code")) in fatal_codes for a in opens):
                    return True
            return False

        try:
            from app.skills.desktop_bridge import desktop_bridge

            desktop_available = await desktop_bridge.check_connection()

            if desktop_available:
                logger.info("🖥️ Desktop Agent available — using LIVE browser")

                # ── Build conversation context block from recent history ────
                # This fixes Bug 2: instead of "Open the browser and complete
                # this web task: {msg}", we send the actual user message with
                # full conversation context so follow-up commands work.
                conversation_history = state.get('conversation_history', [])
                recent_msgs = [
                    msg for msg in conversation_history
                    if isinstance(msg, dict) and msg.get('role') in ('user', 'assistant', 'model')
                ][-6:]  # Last 6 messages for context

                context_lines = ["Recent conversation:"]
                for msg in recent_msgs:
                    role = msg.get('role', 'user')
                    content = str(msg.get('content', ''))[:150]
                    context_lines.append(f"  {role}: {content}")

                context_block = "\n".join(context_lines) if len(recent_msgs) > 1 else None

                # Use user_id as session_id for per-user browser state isolation
                session_id = user_id or "default"

                result = await desktop_bridge.execute_nl_command(
                    user_message,          # <— just the raw user message, not wrapped
                    timeout_seconds=300,
                    conversation_context=context_block,
                    session_id=session_id,
                )

                actions = result.get("actions_taken", [])
                response_text = result.get("response", "")
                browser_state = self._normalize_browser_state(result.get("browser_state"))
                state['browser_state'] = browser_state
                state['web_current_url'] = browser_state.get("current_url", "")

                if _live_browser_looks_failed(actions, response_text):
                    if not self._allows_safe_headless_browser_fallback(user_message):
                        state['current_output'] = (
                            "The live browser on your computer is unavailable, and I will not silently "
                            "downgrade this sensitive browser task to headless mode.\n\n"
                            "Please make sure the Desktop Agent live browser is available, then try again."
                        )
                        state['final_output'] = state['current_output']
                        state['agent_path'].append('web_autonomous_agent')
                        state['success'] = False
                        state['metadata'] = {
                            **state.get('metadata', {}),
                            'browser_state': browser_state,
                            'web_autonomous': True,
                            'web_live_browser': True,
                            'web_fallback_blocked': True,
                        }
                        return state
                    logger.warning(
                        "Live Playwright on the host failed — falling back to headless web agent in Docker"
                    )
                    from app.services.web_agent_service import web_agent_service

                    conversation_history = state.get('conversation_history', [])
                    user_context = state.get('user_context', '')
                    callback = state.get('metadata', {}).get('_message_callback')
                    headless = await web_agent_service.execute_task(
                        user_message=user_message,
                        user_id=user_id,
                        conversation_history=[
                            msg for msg in conversation_history if isinstance(msg, dict)
                        ],
                        user_context=user_context,
                        message_callback=callback,
                    )
                    note = (
                        "The on-screen (Playwright) browser on your PC could not start, "
                        "so this run used the **headless browser inside Docker** instead. "
                        "To fix the live window: in the same terminal/venv you use for the Desktop Agent, run "
                        "`pip install playwright` then `python -m playwright install chromium`, "
                        "then restart `desktop_agent.py`.\n\n"
                    )
                    headless_browser_state = self._normalize_browser_state({
                        "is_open": False,
                        "driver": "headless",
                        "transport": "headless",
                        "current_url": headless.get('current_url', ''),
                        "current_title": headless.get('current_title', ''),
                    })
                    state['browser_state'] = headless_browser_state
                    state['current_output'] = note + (headless.get('output') or '')
                    state['final_output'] = state['current_output']
                    state['agent_path'].append('web_autonomous_agent')
                    state['success'] = headless.get('success', False)
                    state['web_screenshots'] = headless.get('screenshots', [])
                    state['web_actions'] = headless.get('actions_taken', [])
                    state['web_current_url'] = headless.get('current_url', '')
                    state['web_permission_needed'] = headless.get('permission_needed') or {}
                    state['metadata'] = {
                        **state.get('metadata', {}),
                        'browser_state': headless_browser_state,
                        'web_screenshots': headless.get('screenshots', [])[-1:],
                        'web_actions_count': len(headless.get('actions_taken', [])),
                        'web_current_url': headless.get('current_url', ''),
                        'web_autonomous': True,
                        'web_live_browser': False,
                        'web_fallback_headless': True,
                    }
                    return state

                # ── Handle ask_user_question clarification ────────────────
                if result.get("user_input_required"):
                    input_request = result.get("input_request") or {}
                    browser_input_state = {
                        "status": "required",
                        "desktop_request_id": input_request.get("request_id", ""),
                        "field_description": input_request.get("field_description", "input"),
                        "input_type": input_request.get("input_type", "text"),
                        "reason": input_request.get("reason", ""),
                        "task_type": "web_autonomous",
                    }
                    state['current_output'] = self._build_browser_input_prompt(browser_input_state)
                    state['final_output'] = state['current_output']
                    state['agent_path'].append('web_autonomous_agent')
                    state['success'] = False
                    state['metadata'] = {
                        **state.get('metadata', {}),
                        '_browser_input_state': browser_input_state,
                        'browser_state': browser_state,
                        'web_autonomous': True,
                        'web_live_browser': True,
                    }
                    return state

                if result.get("requires_clarification"):
                    logger.info("❓ Agent needs clarification from user")
                    clarif_question = result.get("question", "")
                    clarif_options = result.get("options", [])
                    clarif_context = result.get("context", "")

                    state['current_output'] = clarif_question
                    state['final_output'] = clarif_question
                    state['agent_path'].append('web_autonomous_agent')
                    state['success'] = False
                    clarification_state = {
                        "status": "required",
                        "question": clarif_question,
                        "options": [
                            {"index": i + 1, "label": opt}
                            for i, opt in enumerate(clarif_options)
                        ],
                        "reason": clarif_context,
                        "task_type": "web_autonomous",
                    }
                    state['metadata'] = {
                        **state.get('metadata', {}),
                        '_clarification_state': clarification_state,
                        'browser_state': browser_state,
                        'requires_clarification': True,
                        'clarification_question': clarif_question,
                        'clarification_options': clarif_options,
                        'web_autonomous': True,
                        'web_live_browser': True,
                    }
                    return state

                screenshots = []
                for action in actions:
                    preview = action.get("result_preview", "")
                    if "screenshot" in preview.lower() and "base64" in preview.lower():
                        screenshots.append(preview)

                sensitive_blocked = any(
                    "sensitive_action_blocked" in str(a.get("result_preview", "")).lower()
                    for a in actions
                ) or "sensitive_action_blocked" in response_text.lower()

                if sensitive_blocked:
                    logger.warning("🔒 Sensitive action blocked by live browser — requesting approval")
                    state['current_output'] = (
                        "The live browser detected a sensitive page (login, payment, or password fields). "
                        "User approval is required before continuing.\n\n"
                        f"Details: {response_text}"
                    )
                    state['final_output'] = state['current_output']
                    state['agent_path'].append('web_autonomous_agent')
                    state['success'] = False
                    state['web_permission_needed'] = {
                        "reason": "Sensitive page detected by live browser",
                        "details": response_text,
                    }

                    state['metadata'] = {
                        **state.get('metadata', {}),
                        'browser_state': browser_state,
                        'web_autonomous': True,
                        'web_live_browser': True,
                        'web_sensitive_blocked': True,
                        'approval_required': True,
                        'approval_reason': (
                            "The browser encountered a sensitive page "
                            "(password fields, payment form, or login page). "
                            "Please approve to continue."
                        ),
                    }
                    return state

                state['current_output'] = response_text or "Web task completed via live browser."
                state['final_output'] = state['current_output']
                state['agent_path'].append('web_autonomous_agent')
                state['success'] = result.get("success", False)
                state['web_screenshots'] = screenshots
                state['web_actions'] = actions
                state['web_current_url'] = browser_state.get("current_url", "")
                state['web_permission_needed'] = {}

                state['metadata'] = {
                    **state.get('metadata', {}),
                    'browser_state': browser_state,
                    'web_screenshots': screenshots[-1:] if screenshots else [],
                    'web_actions_count': len(actions),
                    'web_current_url': browser_state.get("current_url", ""),
                    'web_autonomous': True,
                    'web_live_browser': True,
                }

                if user_id and result.get("success"):
                    self.memory_service.learn_from_behavior(user_id, {
                        'task_type': 'web_autonomous',
                        'success': True,
                        'actions_count': len(actions),
                        'live_browser': True,
                    })

                logger.info(
                    f"✅ Live browser task complete: {len(actions)} actions"
                )
                return state

            logger.info("🐳 Desktop Agent unavailable — falling back to headless browser")
            if not self._allows_safe_headless_browser_fallback(user_message):
                state['current_output'] = (
                    "The live browser is unavailable, and this browser task is sensitive, so I will not "
                    "silently downgrade it to headless mode.\n\n"
                    "Please start the Desktop Agent browser runtime and try again."
                )
                state['final_output'] = state['current_output']
                state['agent_path'].append('web_autonomous_agent')
                state['success'] = False
                state['metadata'] = {
                    **state.get('metadata', {}),
                    'browser_state': {},
                    'web_autonomous': True,
                    'web_live_browser': False,
                    'web_fallback_blocked': True,
                }
                return state
            from app.services.web_agent_service import web_agent_service

            conversation_history = state.get('conversation_history', [])
            user_context = state.get('user_context', '')
            callback = state.get('metadata', {}).get('_message_callback')

            result = await web_agent_service.execute_task(
                user_message=user_message,
                user_id=user_id,
                conversation_history=[
                    msg for msg in conversation_history if isinstance(msg, dict)
                ],
                user_context=user_context,
                message_callback=callback,
            )

            state['current_output'] = result.get('output', 'Web task completed.')
            state['final_output'] = state['current_output']
            state['agent_path'].append('web_autonomous_agent')
            state['success'] = result.get('success', False)
            state['web_screenshots'] = result.get('screenshots', [])
            state['web_actions'] = result.get('actions_taken', [])
            state['web_current_url'] = result.get('current_url', '')
            state['web_permission_needed'] = result.get('permission_needed') or {}
            state['browser_state'] = self._normalize_browser_state({
                "is_open": False,
                "driver": "headless",
                "transport": "headless",
                "current_url": result.get('current_url', ''),
                "current_title": result.get('current_title', ''),
            })

            state['metadata'] = {
                **state.get('metadata', {}),
                'browser_state': state['browser_state'],
                'web_screenshots': result.get('screenshots', [])[-1:],
                'web_actions_count': len(result.get('actions_taken', [])),
                'web_current_url': result.get('current_url', ''),
                'web_autonomous': True,
                'web_live_browser': False,
            }

            if user_id and result.get('success'):
                self.memory_service.learn_from_behavior(user_id, {
                    'task_type': 'web_autonomous',
                    'success': True,
                    'actions_count': len(result.get('actions_taken', [])),
                    'url_visited': result.get('current_url', ''),
                })

            logger.info(f"✅ Headless web task complete: {len(result.get('actions_taken', []))} actions")

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
            user_message_lower = state.get('user_message', '').strip().lower()
            if any(phrase in user_message_lower for phrase in ("what is my name", "what's my name", "do you know my name", "who am i")):
                profile = self.memory_service.get_user_profile(state.get('user_id', ''))
                display_name = profile.get("display_name") or (profile.get("metadata") or {}).get("display_name")
                if display_name:
                    state['current_output'] = f"Your name is {display_name}."
                else:
                    state['current_output'] = "I don't have your name stored confidently yet."
                state['final_output'] = state['current_output']
                state['agent_path'].append('general_assistant')
                state['success'] = True
                return state

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
            'browser_state': {},
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

    def _looks_page_relative_follow_up(self, user_message: str) -> bool:
        """Detect follow-up commands that should stay attached to an open browser session."""
        message = (user_message or "").strip().lower()
        if not message:
            return False

        direct_phrases = (
            "click ", "type ", "fill ", "submit", "press ", "scroll", "continue",
            "next", "back", "go back", "open this", "open that", "open the first",
            "open the second", "select ", "choose ", "search here", "search on this page",
            "in the browser", "on this page", "on the page", "on that site", "log in",
            "login", "sign in", "sign up", "enter ", "paste ", "hover ", "drag ",
        )
        if any(phrase in message for phrase in direct_phrases):
            return True

        contextual_terms = ("this page", "that page", "this site", "that site", "the page", "the browser")
        action_terms = ("click", "type", "fill", "submit", "open", "continue", "search", "scroll", "press")
        return any(term in message for term in contextual_terms) and any(
            action in message for action in action_terms
        )

    def _is_sensitive_browser_task(self, user_message: str) -> bool:
        """Block unsafe silent headless fallback for sensitive website tasks."""
        message = (user_message or "").lower()
        sensitive_terms = (
            "login", "log in", "sign in", "sign up", "password", "otp", "captcha",
            "checkout", "payment", "pay ", "credit card", "debit card", "cvv",
            "billing", "bank", "purchase", "buy ", "order ", "book ", "submit form",
            "create account", "register", "account settings", "personal details",
        )
        return any(term in message for term in sensitive_terms)

    def _allows_safe_headless_browser_fallback(self, user_message: str) -> bool:
        """Allow headless fallback only for clearly non-sensitive browse/read tasks."""
        message = (user_message or "").lower()
        if self._is_sensitive_browser_task(message):
            return False
        safe_terms = (
            "search", "look up", "research", "find", "open", "visit", "read",
            "summarize", "browse", "compare", "show me", "what is", "latest",
        )
        return any(term in message for term in safe_terms)

    def _build_browser_input_prompt(self, browser_input_state: Dict[str, Any]) -> str:
        field_description = browser_input_state.get("field_description", "the requested input")
        reason = browser_input_state.get("reason", "")
        prompt = f"Browser input required: please provide {field_description}."
        if reason:
            prompt += f"\n\nReason: {reason}"
        return prompt

    def _normalize_browser_state(self, browser_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        state = browser_state or {}
        return {
            "is_open": bool(
                state.get("is_open", state.get("running", False))
            ),
            "profile": state.get("profile", ""),
            "driver": state.get("driver", ""),
            "transport": state.get("transport", ""),
            "current_url": state.get("current_url", ""),
            "current_title": state.get("current_title", ""),
            "tab_id": state.get("tab_id", ""),
            "last_snapshot_mode": state.get("last_snapshot_mode", ""),
            "last_action_summary": state.get("last_action_summary", ""),
        }

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
        dangerous_keywords = [
            "delete", "remove", "erase", "format", "wipe", "factory reset",
            "shutdown", "reboot", "kill process", "terminate process", "trash",
            "purchase", "buy", "checkout", "payment", "transfer money",
            "deploy to production", "git push", "git commit", "revoke",
            "archive email", "empty recycle bin",
        ]
        confirm_keywords = [
            "send email", "send mail", "send message", "send it", "submit",
            "post publicly", "publish", "share", "install", "sign in",
            "log in", "login", "download and move", "upload",
            "create file", "write file", "save file", "create folder",
            "move file", "copy file", "write to", "save to",
        ]
        desktop_sensitive_confirm = [
            "type password", "enter password", "paste password", "close all",
            "close every", "send report", "open bank", "open payment",
            "create file", "write file", "save file", "create folder",
            "move file", "copy file", "write to", "save to",
        ]
        desktop_sensitive_danger = [
            "delete file", "delete folder", "rm -rf", "format drive",
            "remove all", "close all windows",
        ]

        safety_level = "safe"
        reason = ""

        if any(keyword in message_lower for keyword in dangerous_keywords):
            safety_level = "dangerous"
            reason = "The request would modify, delete, purchase, or permanently change something on your behalf."
        elif any(keyword in message_lower for keyword in confirm_keywords):
            safety_level = "confirm"
            reason = "The request appears to commit an external action or change personal data."

        if task_type == "desktop":
            if any(keyword in message_lower for keyword in desktop_sensitive_danger):
                safety_level = "dangerous"
                reason = "The desktop action could close, delete, or alter important user data."
            elif safety_level == "safe" and any(keyword in message_lower for keyword in desktop_sensitive_confirm):
                safety_level = "confirm"
                reason = "The desktop action touches sensitive personal workflows and should be confirmed first."
            if any(keyword in message_lower for keyword in ("create file", "write file", "save file", "write to", "save to", "create folder", "move file", "copy file")):
                safety_level = "confirm"
                reason = "The desktop action will create, write, move, or copy files on your machine, so I need your approval first."

        requires_approval = safety_level != "safe"
        return ApprovalRequest(
            required=requires_approval,
            approval_level="confirm" if requires_approval else "none",
            reason=reason,
            safety_level=safety_level,  # type: ignore[arg-type]
        )

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
        if approval.safety_level == "dangerous":
            risk_level = "high"
        elif approval.required or task_type in {"desktop", "email", "calendar", "web_autonomous"}:
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

    def _desktop_executor_handles_approval(self, user_message: str, task_type: str) -> bool:
        """Let the desktop executor resolve exact paths before asking for approval."""
        if task_type != "desktop":
            return False
        message_lower = user_message.lower()
        return any(
            phrase in message_lower
            for phrase in [
                "create file",
                "write file",
                "save file",
                "write to",
                "save to",
                "create folder",
                "move file",
                "copy file",
            ]
        )

    def _build_execution_plan(
        self,
        envelope: TaskEnvelope,
        analysis: TaskAnalysis,
        approval_override: bool = False,
    ) -> ExecutionPlan:
        """Create an explicit step-by-step plan before execution starts."""
        steps: List[PlanStep] = []
        desktop_internal_approval = (
            self._desktop_executor_handles_approval(envelope.user_message, analysis.task_type)
            and not approval_override
        )

        def _make_step(
            index: int,
            agent_type: str,
            goal: str,
            message: str,
            depends_on: Optional[List[str]] = None,
            approval_level: str = "none",
            safety_level: str = "safe",
            tool_name: str = "",
            success_criteria: str = "",
            fallback_strategy: str = "",
            verification: Optional[Dict[str, Any]] = None,
            recovery: Optional[Dict[str, Any]] = None,
            retry_budget: int = 0,
        ) -> PlanStep:
            return PlanStep(
                step_id=f"step-{index}",
                agent_type=agent_type,  # type: ignore[arg-type]
                goal=goal,
                inputs={"message": message},
                depends_on=depends_on or [],
                approval_level=approval_level,  # type: ignore[arg-type]
                safety_level=safety_level,  # type: ignore[arg-type]
                tool_name=tool_name,
                verification=verification or {},
                recovery=recovery or {},
                retry_budget=retry_budget,
                success_criteria=success_criteria,
                fallback_strategy=fallback_strategy,
            )

        workflow_match = workflow_library_service.match_workflow(
            envelope.user_message,
            envelope.user_id,
        )
        if workflow_match and workflow_match.get("steps"):
            workflow_steps = [step.model_copy(deep=True) for step in workflow_match["steps"]]
            if approval_override:
                for workflow_step in workflow_steps:
                    workflow_step.approval_level = "none"
                    if workflow_step.safety_level == "confirm":
                        workflow_step.safety_level = "safe"
            if analysis.approval.required and not any(step.approval_level != "none" for step in workflow_steps):
                workflow_steps[0].approval_level = analysis.approval.approval_level
                workflow_steps[0].safety_level = analysis.approval.safety_level

            affected_steps = [
                step.step_id for step in workflow_steps if step.approval_level != "none"
            ]
            requires_approval = bool(affected_steps) or analysis.approval.required
            approval_request = ApprovalRequest(
                required=requires_approval,
                approval_level="confirm" if requires_approval else "none",
                reason=analysis.approval.reason or (
                    "The workflow contains confirmation-gated steps."
                    if affected_steps else ""
                ),
                affected_steps=affected_steps or (
                    [workflow_steps[0].step_id] if requires_approval else []
                ),
                safety_level=analysis.approval.safety_level if analysis.approval.required else (
                    "confirm" if affected_steps else "safe"
                ),
            )
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                task_type=analysis.task_type,  # type: ignore[arg-type]
                summary=workflow_match.get("summary") or f"Run the {analysis.task_type} workflow.",
                steps=workflow_steps,
                requires_approval=requires_approval,
                approval_request=approval_request if requires_approval else None,
                workflow_key=workflow_match.get("workflow_key"),
                workflow_name=workflow_match.get("workflow_name"),
                workflow_source=workflow_match.get("workflow_source", "builtin"),
                metadata=workflow_match.get("metadata") or {},
            )

        if not analysis.blocked:
            if self._requires_research_step(envelope.user_message, analysis.task_type):
                steps.append(_make_step(
                    1,
                    "web_autonomous",
                    "Research the requested implementation on the web before coding.",
                    f"Research documentation and implementation guidance for: {envelope.user_message}",
                    approval_level="none",
                    safety_level="safe",
                    success_criteria="Relevant references or findings are gathered.",
                    fallback_strategy="Proceed with implementation using existing context if research is unavailable.",
                    verification={
                        "method": "none",
                        "description": "Research is verified by the presence of relevant findings in the output.",
                    },
                    recovery={
                        "strategy": "Fallback to coding with current repo context if web research is unavailable.",
                    },
                ))
                steps.append(_make_step(
                    2,
                    "coding",
                    "Implement the requested solution using the gathered context.",
                    envelope.user_message,
                    depends_on=["step-1"],
                    approval_level=analysis.approval.approval_level if analysis.approval.required else "none",
                    safety_level=analysis.approval.safety_level if analysis.approval.required else "safe",
                    success_criteria="Code, files, and execution artifacts are produced.",
                    fallback_strategy="Return a concrete blocking error with partial output if implementation fails.",
                    verification={
                        "method": "none",
                        "description": "Implementation is verified by produced files or a concrete output.",
                    },
                    recovery={
                        "strategy": "Surface the blocking implementation error and preserve partial output.",
                    },
                ))
            else:
                verification = {
                    "method": "none",
                    "description": "The specialist should either complete the task or return a clear failure reason.",
                }
                recovery = {
                    "strategy": "Escalate to the general agent with failure context if the specialist cannot complete the task.",
                }
                retry_budget = 0
                if analysis.task_type == "desktop":
                    verification = {
                        "method": "composite",
                        "target": envelope.user_message,
                        "description": "Desktop requests should be verified through observed state, evidence, and recovery.",
                    }
                    recovery = {
                        "strategy": "Analyze, plan, execute, verify, and recover using the desktop executor.",
                        "alternate_tools": ["list_windows", "get_active_window", "read_screen_text", "search_system"],
                        "max_retries": 1,
                    }
                    retry_budget = 1
                steps.append(_make_step(
                    1,
                    analysis.task_type,
                    f"Execute the user's {analysis.task_type.replace('_', ' ')} request.",
                    envelope.user_message,
                    approval_level=(
                        "none"
                        if desktop_internal_approval
                        else analysis.approval.approval_level if analysis.approval.required else "none"
                    ),
                    safety_level=(
                        "safe"
                        if desktop_internal_approval
                        else analysis.approval.safety_level if analysis.approval.required else "safe"
                    ),
                    success_criteria="The specialist completes the request or returns a clear blocking error.",
                    fallback_strategy="Escalate to the general agent with the failure context if needed.",
                    verification=verification,
                    recovery=recovery,
                    retry_budget=retry_budget,
                ))

        requires_approval = analysis.approval.required and not desktop_internal_approval

        if requires_approval:
            analysis.approval.affected_steps = [
                step.step_id for step in steps if step.approval_level != "none"
            ]

        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            task_type=analysis.task_type,  # type: ignore[arg-type]
            summary=f"Analyze the request, then execute it through the {analysis.task_type} specialist flow.",
            steps=steps,
            requires_approval=requires_approval,
            approval_request=analysis.approval if requires_approval else None,
            workflow_source="dynamic",
            metadata={"desktop_internal_approval": desktop_internal_approval},
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
            'browser_state': state.get('browser_state', {}),
            'desktop_action': state.get('desktop_action', ''),
            'desktop_result': state.get('desktop_result', {}),
            'desktop_plan': safe_metadata.get('desktop_plan', {}),
            'desktop_execution_trace': safe_metadata.get('desktop_execution_trace', []),
            'desktop_evidence': safe_metadata.get('desktop_evidence', []),
            'workflow_key': safe_metadata.get('workflow_key', ''),
            'workflow_name': safe_metadata.get('workflow_name', ''),
            'workflow_source': safe_metadata.get('workflow_source', ''),
        }

    async def _execute_plan_step(self, step: PlanStep, state: AgentState) -> AgentState:
        """Dispatch a single plan step to the correct specialist node."""
        step_message = step.inputs.get("message", state.get('user_message', ''))
        state['metadata'] = {
            **state.get('metadata', {}),
            '_current_step': step.model_dump(),
        }
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
    ) -> tuple[AgentState, List[ExecutionTraceEvent], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Run the explicit plan, capturing step traces and orchestrator-managed handoffs."""
        execution_trace: List[ExecutionTraceEvent] = []
        approval_state = {"status": "not_required", "reason": ""}
        clarification_state = {"status": "not_required", "reason": "", "options": []}
        browser_input_state = {"status": "not_required", "reason": "", "field_description": "", "input_type": "text"}
        completed_steps: set[str] = set()
        step_index = 0
        state['metadata'] = {
            **state.get('metadata', {}),
            'workflow_key': plan.workflow_key or '',
            'workflow_name': plan.workflow_name or '',
            'workflow_source': plan.workflow_source,
        }

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
                    "safety_level": step.safety_level,
                    "workflow_name": plan.workflow_name,
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
            specialist_trace_events = state.get('metadata', {}).pop('_specialist_trace_events', [])
            for specialist_event in specialist_trace_events:
                if isinstance(specialist_event, ExecutionTraceEvent):
                    execution_trace.append(specialist_event)
                elif isinstance(specialist_event, dict):
                    execution_trace.append(ExecutionTraceEvent(**specialist_event))

            specialist_approval_state = state.get('metadata', {}).pop('_approval_state', {}) or {}
            specialist_clarification_state = state.get('metadata', {}).pop('_clarification_state', {}) or {}
            specialist_browser_input_state = state.get('metadata', {}).pop('_browser_input_state', {}) or {}
            if specialist_clarification_state.get("status") == "required":
                step.status = "blocked"
                clarification_state = specialist_clarification_state
            elif specialist_browser_input_state.get("status") == "required":
                step.status = "blocked"
                browser_input_state = specialist_browser_input_state
            elif specialist_approval_state.get("status") == "required":
                step.status = "blocked"
                approval_state = specialist_approval_state
            else:
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

            if clarification_state.get("status") == "required":
                execution_trace.append(ExecutionTraceEvent(
                    event_type="clarification_required",
                    phase="execution",
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    success=False,
                    message=clarification_state.get("reason", clarification_state.get("question", "Clarification required.")),
                    data={"clarification_state": clarification_state},
                ))
                await self._emit_progress(
                    message_callback,
                    "clarification_required",
                    clarification_state.get("question", clarification_state.get("reason", "Clarification required.")),
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    clarification_state=clarification_state,
                )
                break

            if browser_input_state.get("status") == "required":
                execution_trace.append(ExecutionTraceEvent(
                    event_type="browser_input_required",
                    phase="execution",
                    step_id=step.step_id,
                    agent_type=step.agent_type,
                    success=False,
                    message=browser_input_state.get("reason", self._build_browser_input_prompt(browser_input_state)),
                    data={"browser_input_state": browser_input_state},
                ))
                break

            if approval_state.get("status") == "required":
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

            if not state.get('success', False):
                break

            completed_steps.add(step.step_id)
            state.get('metadata', {}).pop('_current_step', None)
            state['conversation_history'] = (
                state.get('conversation_history', [])
                + [{'role': 'user', 'content': step.inputs.get("message", '')}]
                + (
                    [{'role': 'assistant', 'content': state.get('current_output', '')}]
                    if state.get('current_output') else []
                )
            )[-20:]

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

        return state, execution_trace, approval_state, clarification_state, browser_input_state

    async def _persist_interaction(
        self,
        envelope: TaskEnvelope,
        response_text: str,
        task_type: str,
        agent_path: List[str],
        success: bool,
        execution_trace: List[ExecutionTraceEvent],
        plan: Optional[ExecutionPlan] = None,
        artifacts: Optional[Dict[str, Any]] = None,
        approval_state: Optional[Dict[str, Any]] = None,
        clarification_state: Optional[Dict[str, Any]] = None,
        browser_input_state: Optional[Dict[str, Any]] = None,
        browser_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist the user request and assistant response once per orchestrated turn."""
        try:
            trace_payload = [event.model_dump() for event in execution_trace]
            interaction_user_message = envelope.metadata.get('interaction_user_message', envelope.user_message)
            self.memory_service.save_message(
                conversation_id=envelope.conversation_id,
                user_id=envelope.user_id,
                role='user',
                content=interaction_user_message,
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
                    'plan': plan.model_dump() if plan else None,
                    'artifacts': artifacts or {},
                    'approval_state': approval_state or {},
                    'clarification_state': clarification_state or {},
                    'browser_input_state': browser_input_state,
                    'browser_state': browser_state or {},
                },
            )
            self.memory_service.save_conversation_exchange(
                conversation_id=envelope.conversation_id,
                user_id=envelope.user_id,
                user_message=interaction_user_message,
                assistant_response=response_text,
                metadata={'task_type': task_type},
            )
            self.memory_service.save_task(
                envelope.user_id,
                {
                    'conversation_id': envelope.conversation_id,
                    'task_type': task_type,
                    'description': interaction_user_message,
                    'agent_used': 'planner_executor',
                    'iterations': len([event for event in execution_trace if event.event_type == 'step_completed']),
                    'success': success,
                }
            )
            if (
                plan
                and plan.workflow_key
                and (approval_state or {}).get('status') != 'required'
                and (clarification_state or {}).get('status') != 'required'
                and (browser_input_state or {}).get('status') != 'required'
            ):
                self.memory_service.record_workflow_run(
                    envelope.user_id,
                    plan.workflow_key,
                    plan.workflow_name or plan.summary,
                    success=success,
                    parameters=plan.metadata,
                    description=plan.summary,
                    is_builtin=plan.workflow_source in {'builtin', 'heuristic'},
                )
        except Exception as exc:
            logger.error(f"❌ Unified persistence error: {exc}")

    def _format_clarification_prompt(self, clarification_state: Dict[str, Any]) -> str:
        question = clarification_state.get("question") or clarification_state.get("reason") or "Clarification required."
        options = clarification_state.get("options") or []
        if not options or "\n" in question:
            return question
        lines = [question]
        for option in options[:5]:
            lines.append(f"{option.get('index')}. {option.get('path') or option.get('label')}")
        return "\n".join(lines)

    async def _build_clarification_response(
        self,
        *,
        envelope: TaskEnvelope,
        clarification_state: Dict[str, Any],
        message_callback: Optional[Callable],
        prompt_prefix: str = "",
    ) -> Dict[str, Any]:
        prompt = self._format_clarification_prompt(clarification_state)
        output = f"{prompt_prefix}\n\n{prompt}".strip() if prompt_prefix else prompt
        execution_trace = [
            ExecutionTraceEvent(
                event_type="clarification_required",
                phase="analysis",
                message=clarification_state.get("reason", clarification_state.get("question", "Clarification required.")),
                agent_type=clarification_state.get("task_type", "desktop"),
                success=False,
                data={"clarification_state": clarification_state},
            )
        ]
        response = {
            'success': False,
            'output': output,
            'task_type': clarification_state.get("task_type", "desktop"),
            'confidence': 1.0,
            'agent_path': ['clarification_pending'],
            'code': None,
            'files': None,
            'language': None,
            'file_path': '',
            'project_structure': None,
            'main_file': None,
            'project_type': '',
            'server_running': False,
            'server_url': '',
            'server_port': None,
            'plan': None,
            'execution_trace': [event.model_dump() for event in execution_trace],
            'approval_state': {'status': 'not_required', 'reason': '', 'affected_steps': []},
            'clarification_state': clarification_state,
            'browser_input_state': None,
            'browser_state': (envelope.metadata or {}).get("browser_state", {}),
            'artifacts': {},
            'metadata': {
                'channel': envelope.channel,
                'routing_reason': 'Waiting for the user to disambiguate an exact folder or file target.',
                'risk_level': 'medium',
                'iterations': 0,
                'errors': [],
                'browser_state': (envelope.metadata or {}).get("browser_state", {}),
            },
        }
        await self._persist_interaction(
            envelope=envelope,
            response_text=output,
            task_type=response['task_type'],
            agent_path=response['agent_path'],
            success=False,
            execution_trace=execution_trace,
            plan=None,
            artifacts={},
            approval_state=response['approval_state'],
            clarification_state=clarification_state,
            browser_input_state=None,
            browser_state=response['browser_state'],
        )
        await self._emit_progress(
            message_callback,
            "final",
            output[:500],
            result=response,
        )
        return response

    async def _build_browser_input_response(
        self,
        *,
        envelope: TaskEnvelope,
        browser_input_state: Dict[str, Any],
        browser_state: Dict[str, Any],
        message_callback: Optional[Callable],
    ) -> Dict[str, Any]:
        output = self._build_browser_input_prompt(browser_input_state)
        execution_trace = [
            ExecutionTraceEvent(
                event_type="browser_input_required",
                phase="analysis",
                message=browser_input_state.get("reason", output),
                agent_type="web_autonomous",
                success=False,
                data={
                    "browser_input_state": browser_input_state,
                    "browser_state": browser_state,
                },
            )
        ]
        response = {
            'success': False,
            'output': output,
            'task_type': 'web_autonomous',
            'confidence': 1.0,
            'agent_path': ['web_autonomous_agent', 'browser_input_pending'],
            'code': None,
            'files': None,
            'language': None,
            'file_path': '',
            'project_structure': None,
            'main_file': None,
            'project_type': '',
            'server_running': False,
            'server_url': '',
            'server_port': None,
            'plan': None,
            'execution_trace': [event.model_dump() for event in execution_trace],
            'approval_state': {'status': 'not_required', 'reason': '', 'affected_steps': []},
            'clarification_state': {'status': 'not_required', 'reason': '', 'options': []},
            'browser_input_state': browser_input_state,
            'browser_state': browser_state,
            'artifacts': {
                'web_current_url': browser_state.get('current_url', ''),
                'browser_state': browser_state,
            },
            'metadata': {
                'channel': envelope.channel,
                'routing_reason': 'Waiting for browser input to resume the live browser task.',
                'risk_level': 'medium',
                'iterations': 0,
                'errors': [],
                'web_current_url': browser_state.get('current_url', ''),
                'browser_state': browser_state,
                'web_autonomous': True,
                'web_live_browser': True,
            },
        }
        await self._persist_interaction(
            envelope=envelope,
            response_text=output,
            task_type='web_autonomous',
            agent_path=response['agent_path'],
            success=False,
            execution_trace=execution_trace,
            plan=None,
            artifacts=response['artifacts'],
            approval_state=response['approval_state'],
            clarification_state=response['clarification_state'],
            browser_input_state=browser_input_state,
            browser_state=browser_state,
        )
        await self._emit_progress(
            message_callback,
            "question_for_user",
            output,
            browser_input_state=browser_input_state,
        )
        await self._emit_progress(
            message_callback,
            "final",
            output[:500],
            result=response,
        )
        return response

    async def _build_browser_result_response(
        self,
        *,
        envelope: TaskEnvelope,
        desktop_result: Dict[str, Any],
        browser_state: Dict[str, Any],
        message_callback: Optional[Callable],
        user_message_for_memory: Optional[str] = None,
    ) -> Dict[str, Any]:
        output = desktop_result.get("response") or desktop_result.get("error") or "Browser task completed."
        success = bool(desktop_result.get("success", False))
        actions = desktop_result.get("actions_taken", []) or []
        execution_trace = [
            ExecutionTraceEvent(
                event_type="browser_resumed",
                phase="execution",
                message=output[:500],
                agent_type="web_autonomous",
                success=success,
                data={"browser_state": browser_state, "actions_taken": actions},
            )
        ]
        response = {
            'success': success,
            'output': output,
            'task_type': 'web_autonomous',
            'confidence': 1.0,
            'agent_path': ['web_autonomous_agent'],
            'code': None,
            'files': None,
            'language': None,
            'file_path': '',
            'project_structure': None,
            'main_file': None,
            'project_type': '',
            'server_running': False,
            'server_url': '',
            'server_port': None,
            'plan': None,
            'execution_trace': [event.model_dump() for event in execution_trace],
            'approval_state': {'status': 'not_required', 'reason': '', 'affected_steps': []},
            'clarification_state': {'status': 'not_required', 'reason': '', 'options': []},
            'browser_input_state': None,
            'browser_state': browser_state,
            'artifacts': {
                'web_current_url': browser_state.get('current_url', ''),
                'web_actions': actions,
                'browser_state': browser_state,
            },
            'metadata': {
                'channel': envelope.channel,
                'routing_reason': 'Continued the live browser task using the pending browser input.',
                'risk_level': 'medium',
                'iterations': 0,
                'errors': [desktop_result.get('error')] if desktop_result.get('error') else [],
                'web_actions_count': len(actions),
                'web_current_url': browser_state.get('current_url', ''),
                'browser_state': browser_state,
                'web_autonomous': True,
                'web_live_browser': browser_state.get('transport', '') != 'headless',
            },
        }
        await self._persist_interaction(
            envelope=TaskEnvelope(
                user_message=user_message_for_memory or envelope.user_message,
                user_id=envelope.user_id,
                conversation_id=envelope.conversation_id,
                channel=envelope.channel,
                metadata=envelope.metadata,
            ),
            response_text=output,
            task_type='web_autonomous',
            agent_path=response['agent_path'],
            success=success,
            execution_trace=execution_trace,
            plan=None,
            artifacts=response['artifacts'],
            approval_state=response['approval_state'],
            clarification_state=response['clarification_state'],
            browser_input_state=None,
            browser_state=browser_state,
        )
        await self._emit_progress(
            message_callback,
            "final",
            output[:500],
            result=response,
        )
        return response

    async def _maybe_resume_pending_browser_input(
        self,
        *,
        user_message: str,
        user_id: str,
        conversation_id: str,
        message_callback: Optional[Callable],
    ) -> Optional[Dict[str, Any]]:
        from app.services.browser_input_service import browser_input_service
        from app.services.clarification_service import clarification_service
        from app.skills.desktop_bridge import desktop_bridge

        pending = browser_input_service.get_pending_request(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not pending:
            return None

        channel = pending.channel or self._detect_channel(user_id)
        sanitized_input_message = f"Provided {pending.field_description}"
        envelope = TaskEnvelope(
            user_message=sanitized_input_message,
            user_id=user_id,
            conversation_id=conversation_id,
            channel=channel,
            metadata={"browser_input_for": pending.field_description},
        )

        resumed = await desktop_bridge.provide_input(
            request_id=pending.desktop_request_id,
            value=user_message,
        )
        browser_state = self._normalize_browser_state(resumed.get("browser_state"))

        browser_input_service.resolve(
            pending.browser_input_id,
            result={"success": resumed.get("success", False)},
            status="resolved",
        )
        browser_input_service.remove(pending.browser_input_id)

        if resumed.get("user_input_required"):
            input_request = resumed.get("input_request") or {}
            next_pending = browser_input_service.create_request(
                desktop_request_id=input_request.get("request_id", ""),
                user_id=user_id,
                conversation_id=conversation_id,
                channel=channel,
                field_description=input_request.get("field_description", "input"),
                input_type=input_request.get("input_type", "text"),
                reason=input_request.get("reason", ""),
            )
            browser_input_state = {
                "status": "required",
                "browser_input_id": next_pending.browser_input_id,
                "field_description": next_pending.field_description,
                "input_type": next_pending.input_type,
                "reason": next_pending.reason,
                "channel": next_pending.channel,
            }
            return await self._build_browser_input_response(
                envelope=envelope,
                browser_input_state=browser_input_state,
                browser_state=browser_state,
                message_callback=message_callback,
            )

        if resumed.get("requires_clarification"):
            clarification_state = {
                "status": "required",
                "reason": resumed.get("question", "") or resumed.get("response", ""),
                "question": resumed.get("question", ""),
                "options": [
                    {"index": i + 1, "label": opt}
                    for i, opt in enumerate(resumed.get("options", []) or [])
                ],
                "task_type": "web_autonomous",
            }
            clarification_request = clarification_service.create_request(
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=sanitized_input_message,
                question=clarification_state.get("question") or clarification_state.get("reason", "Clarification required."),
                options=clarification_state.get("options", []),
                channel=channel,
                task_type="web_autonomous",
                metadata={"resume_context": {"browser_state": browser_state}},
            )
            clarification_state["clarification_id"] = clarification_request.clarification_id
            return await self._build_clarification_response(
                envelope=envelope,
                clarification_state=clarification_state,
                message_callback=message_callback,
                prompt_prefix="I still need one more clarification before continuing the browser task.",
            )

        return await self._build_browser_result_response(
            envelope=envelope,
            desktop_result=resumed,
            browser_state=browser_state,
            message_callback=message_callback,
            user_message_for_memory=sanitized_input_message,
        )

    async def _maybe_resume_pending_clarification(
        self,
        *,
        user_message: str,
        user_id: str,
        conversation_id: str,
        max_iterations: int,
        message_callback: Optional[Callable],
        approval_override: bool,
    ) -> Optional[Dict[str, Any]]:
        from app.services.clarification_service import clarification_service

        pending = clarification_service.get_pending_request(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if not pending:
            return None

        envelope = TaskEnvelope(
            user_message=user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            channel=self._detect_channel(user_id),
            metadata={"clarification_for": pending.user_message},
        )

        selected_option = clarification_service.parse_response(pending, user_message)
        clarification_state = {
            "status": "required",
            "reason": pending.question,
            "question": pending.question,
            "options": pending.options,
            "clarification_id": pending.clarification_id,
            "original_request": pending.user_message,
            "task_type": pending.task_type,
        }
        if not selected_option:
            return await self._build_clarification_response(
                envelope=envelope,
                clarification_state=clarification_state,
                message_callback=message_callback,
                prompt_prefix="I still need you to choose one of the exact matches before I continue.",
            )

        clarification_service.resolve(
            pending.clarification_id,
            selected_option=selected_option,
        )
        clarification_service.remove(pending.clarification_id)

        resume_context = {
            **(pending.metadata.get("resume_context") or {}),
            "selected_option": selected_option,
            "selected_path": selected_option.get("value") or selected_option.get("path"),
        }
        await self._emit_progress(
            message_callback,
            "clarification_resolved",
            f"Using {resume_context.get('selected_path', 'the selected path')}.",
            clarification_state={**clarification_state, "status": "resolved", "selected_option": selected_option},
        )
        return await self.process(
            user_message=pending.user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
            message_callback=message_callback,
            approval_override=approval_override,
            resume_context=resume_context,
            interaction_user_message=user_message,
        )

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
        resume_context: Optional[Dict[str, Any]] = None,
        interaction_user_message: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process a request through the unified planner/executor architecture."""
        logger.info(f"🚀 Processing: '{user_message[:50]}...'")

        # Infer message_callback from extra_metadata if not provided directly.
        if extra_metadata and not message_callback:
            message_callback = extra_metadata.get('_message_callback')

        if not resume_context:
            browser_resume_result = await self._maybe_resume_pending_browser_input(
                user_message=user_message,
                user_id=user_id,
                conversation_id=conversation_id,
                message_callback=message_callback,
            )
            if browser_resume_result is not None:
                return browser_resume_result
            clarification_result = await self._maybe_resume_pending_clarification(
                user_message=user_message,
                user_id=user_id,
                conversation_id=conversation_id,
                max_iterations=max_iterations,
                message_callback=message_callback,
                approval_override=approval_override,
            )
            if clarification_result is not None:
                return clarification_result

        state = self._build_initial_state(
            user_message=user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
            message_callback=message_callback,
        )
        state['metadata']['approval_override'] = approval_override
        state['metadata']['_resume_context'] = resume_context or {}
        # Inject caller-provided metadata (callbacks, queues, etc.)
        if extra_metadata:
            state['metadata'].update(extra_metadata)
        envelope = TaskEnvelope(
            user_message=user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            channel=self._detect_channel(user_id),
            metadata={"interaction_user_message": interaction_user_message or user_message},
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

            plan = self._build_execution_plan(
                envelope,
                analysis,
                approval_override=approval_override,
            )
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
            clarification_state = {
                "status": "not_required",
                "reason": "",
                "options": [],
            }
            browser_input_state = None

            if analysis.blocked:
                state['success'] = False
                state['final_output'] = analysis.blocked_reason
            else:
                state, execution_events, approval_state, clarification_state, browser_input_state = await self._execute_plan(
                    state,
                    plan,
                    message_callback=message_callback,
                )
                execution_trace.extend(execution_events)

                web_sensitive = state.get('metadata', {}).get('web_sensitive_blocked')
                if web_sensitive and approval_state.get("status") != "required":
                    approval_state = {
                        "status": "required",
                        "reason": state['metadata'].get(
                            'approval_reason',
                            "The browser encountered a sensitive page and needs your approval to continue.",
                        ),
                        "affected_steps": [s.step_id for s in plan.steps if s.agent_type == "web_autonomous"],
                        "safety_level": "confirm",
                        "resume_context": {
                            "original_message": user_message,
                            "task_type": "web_autonomous",
                            "live_browser": True,
                        },
                    }

                if browser_input_state and browser_input_state.get("status") == "required":
                    from app.services.browser_input_service import browser_input_service

                    browser_input_request = browser_input_service.create_request(
                        desktop_request_id=browser_input_state.get("desktop_request_id", ""),
                        user_id=envelope.user_id,
                        conversation_id=envelope.conversation_id,
                        channel=envelope.channel,
                        field_description=browser_input_state.get("field_description", "input"),
                        input_type=browser_input_state.get("input_type", "text"),
                        reason=browser_input_state.get("reason", ""),
                        metadata={
                            "browser_state": state.get('browser_state', {}),
                        },
                    )
                    browser_input_state = {
                        "status": "required",
                        "browser_input_id": browser_input_request.browser_input_id,
                        "field_description": browser_input_request.field_description,
                        "input_type": browser_input_request.input_type,
                        "reason": browser_input_request.reason,
                        "channel": browser_input_request.channel,
                    }
                    state['success'] = False
                    state['final_output'] = self._build_browser_input_prompt(browser_input_state)
                    await self._emit_progress(
                        message_callback,
                        "question_for_user",
                        state['final_output'],
                        browser_input_state=browser_input_state,
                    )
                elif approval_state["status"] == "required":
                    from app.services.approval_service import approval_service

                    approval_request = approval_service.create_request(
                        user_id=envelope.user_id,
                        conversation_id=envelope.conversation_id,
                        user_message=user_message,
                        reason=approval_state["reason"],
                        channel=envelope.channel,
                        affected_steps=approval_state.get("affected_steps", []),
                        task_type=analysis.task_type,
                        metadata={
                            "safety_level": approval_state.get("safety_level"),
                            "workflow_name": approval_state.get("workflow_name"),
                            "resume_context": approval_state.get("resume_context") or resume_context or {},
                        },
                    )
                    approval_state["approval_id"] = approval_request.approval_id
                    state['success'] = False
                    state['final_output'] = (
                        "Approval is required before I continue.\n\n"
                        f"Reason: {approval_state['reason']}"
                    )
                elif clarification_state["status"] == "required":
                    from app.services.clarification_service import clarification_service

                    clarification_request = clarification_service.create_request(
                        user_id=envelope.user_id,
                        conversation_id=envelope.conversation_id,
                        user_message=user_message,
                        question=clarification_state.get("question") or clarification_state.get("reason", "Clarification required."),
                        options=clarification_state.get("options", []),
                        channel=envelope.channel,
                        task_type=analysis.task_type,
                        metadata={
                            "resume_context": clarification_state.get("resume_context") or {},
                        },
                    )
                    clarification_state["clarification_id"] = clarification_request.clarification_id
                    state['success'] = False
                    state['final_output'] = self._format_clarification_prompt(clarification_state)
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
                'clarification_state': clarification_state,
                'browser_input_state': browser_input_state,
                'browser_state': state.get('browser_state', {}),
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
                    'browser_state': state.get('browser_state', {}),
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
                plan=plan,
                artifacts=artifacts,
                approval_state=approval_state,
                clarification_state=clarification_state,
                browser_input_state=browser_input_state,
                browser_state=state.get('browser_state', {}),
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
                'clarification_state': {'status': 'not_required', 'reason': '', 'options': []},
                'browser_input_state': None,
                'browser_state': {},
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


