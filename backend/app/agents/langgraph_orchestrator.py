"""
LangGraph Multi-Agent Orchestrator - SonarBot
Persistent memory across conversations and restarts.
All agents: coding, desktop, web, general
"""
from typing import Dict, Any, TypedDict, List, Annotated, Optional, Callable
from datetime import datetime, timezone
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
    agent_path: Annotated[List[str], operator.add]
    current_output: str
    
    # Execution
    iteration: int
    max_iterations: int
    errors: Annotated[List[str], operator.add]
    
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


class LangGraphOrchestrator:
    """LangGraph orchestrator with ALL agent types"""
    
    def __init__(self):
        self.context_builder = context_builder
        self.memory_service = enhanced_memory_service
        self.llm = llm_adapter
        self.graph = self._build_graph()
        logger.info("✅ LangGraph Orchestrator initialized")
    
    def _build_graph(self) -> StateGraph:
        """Build agent graph with ALL 4 agent types"""
        workflow = StateGraph(AgentState)
        
        # ✅ ALL NODES: code, desktop, web, general
        workflow.add_node("load_context", self._load_context_node)
        workflow.add_node("route", self._route_node)
        workflow.add_node("code_agent", self._code_agent_node)
        workflow.add_node("desktop_agent", self._desktop_agent_node)  # ✅ NEW
        workflow.add_node("web_agent", self._web_agent_node)          # ✅ NEW
        workflow.add_node("general_agent", self._general_agent_node)
        workflow.add_node("save_memory", self._save_memory_node)
        
        # Flow
        workflow.set_entry_point("load_context")
        workflow.add_edge("load_context", "route")
        
        # ✅ FIXED: Routing for ALL 4 types
        workflow.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "coding": "code_agent",
                "desktop": "desktop_agent",  # ✅ NEW
                "web": "web_agent",          # ✅ NEW
                "general": "general_agent"
            }
        )
        
        # All agents → save memory → END
        workflow.add_edge("code_agent", "save_memory")
        workflow.add_edge("desktop_agent", "save_memory")  # ✅ NEW
        workflow.add_edge("web_agent", "save_memory")      # ✅ NEW
        workflow.add_edge("general_agent", "save_memory")
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
            
            # If this is a new conversation (no history), load recent messages
            # from other conversations to maintain cross-chat context
            if not history:
                all_recent = self.memory_service.get_all_user_messages(
                    user_id=state['user_id'],
                    limit=10
                )
                if all_recent:
                    history = all_recent[-5:]  # Last 5 messages from any conversation
            
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
            # Classify with user context
            result = router_agent.classify_task(
                user_message=state['user_message'],
                user_context=state.get('user_context', '')
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
        """✅ FIXED: Route to correct agent"""
        task_type = state.get('task_type', 'general')
        
        # Map task types to agent nodes
        routing_map = {
            'coding': 'coding',
            'code': 'coding',
            'desktop': 'desktop',  # ✅ NEW
            'web': 'web',          # ✅ NEW
            'general': 'general'
        }
        
        return routing_map.get(task_type, 'general')
    
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
        """✅ Desktop specialist - actually executes desktop actions via desktop bridge"""
        logger.info("🖥️ Desktop Agent processing...")
        
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
- screenshot: {"region": null, "monitor": 1, "format": "base64"}
- mouse_control: {"action": "move|click|double_click|right_click|scroll", "x": int, "y": int, "button": "left|right", "clicks": 1, "direction": "up|down", "amount": 3}
- keyboard_control: {"action": "type|press|hotkey", "text": "string", "key": "string", "keys": ["ctrl", "c"], "interval": 0.05}
- app_launcher: {"app": "app_name", "wait": false}
- window_manager: {"action": "list|focus|minimize|maximize|close", "title": "window_title"}
- screen_reader: {"language": "eng", "region": null}

Respond EXACTLY in this format (one action per line):
ACTION: skill_name | {"arg1": "value1", "arg2": "value2"}
ACTION: skill_name | {"arg1": "value1"}
EXPLANATION: Brief description of what you're doing

Examples:
User: "open chrome"
ACTION: app_launcher | {"app": "chrome", "wait": false}
EXPLANATION: Opening Google Chrome browser

User: "take a screenshot"
ACTION: screenshot | {"monitor": 1, "format": "base64"}
EXPLANATION: Taking a screenshot of your desktop

User: "type hello world in notepad"
ACTION: app_launcher | {"app": "notepad", "wait": true}
ACTION: keyboard_control | {"action": "type", "text": "hello world"}
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
                    actions = [('screenshot', {'monitor': 1, 'format': 'base64'})]
                    explanation = 'Taking a screenshot'
                elif any(kw in msg_lower for kw in ['open ', 'launch ', 'start ']):
                    for kw in ['open ', 'launch ', 'start ']:
                        if kw in msg_lower:
                            app_name = msg_lower.split(kw, 1)[1].strip().split()[0] if msg_lower.split(kw, 1)[1].strip() else ''
                            if app_name:
                                actions = [('app_launcher', {'app': app_name, 'wait': False})]
                                explanation = f'Opening {app_name}'
                            break
                elif 'type ' in msg_lower:
                    text = state['user_message'].split('type ', 1)[1].strip() if 'type ' in state['user_message'].lower() else ''
                    if text:
                        actions = [('keyboard_control', {'action': 'type', 'text': text})]
                        explanation = 'Typing text'
                elif any(kw in msg_lower for kw in ['click', 'mouse']):
                    actions = [('mouse_control', {'action': 'click'})]
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
    
    async def _general_agent_node(self, state: AgentState) -> AgentState:
        """General assistant"""
        logger.info("💬 General Agent processing...")
        
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
            'desktop_result': {}
        }
        
        try:
            # Execute graph
            result = await self.graph.ainvoke(initial_state)
            
            # Build response
            extra_metadata = result.get('metadata', {})
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