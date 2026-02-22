"""
LangGraph Multi-Agent Orchestrator
State graph-based orchestration with memory and reflection
"""
from typing import Dict, Any, TypedDict, List, Annotated
from datetime import datetime, timezone
import operator
from loguru import logger

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.agents.router_agent import router_agent
from app.services.context_builder import context_builder
from app.services.memory_service import memory_service
from app.core.llm import llm_adapter


# ===== STATE DEFINITION =====

class AgentState(TypedDict):
    """
    Shared state across all graph nodes
    """
    # Input
    user_message: str
    user_id: str
    conversation_id: str
    
    # Context (built before routing)
    user_context: str  # Personalized context from memory
    conversation_history: List[Dict]  # Recent messages
    
    # Routing
    task_type: str
    confidence: float
    routing_reason: str
    
    # Agent outputs
    agent_path: Annotated[List[str], operator.add]  # Track which agents ran
    current_output: str
    
    # Execution tracking
    iteration: int
    max_iterations: int
    errors: Annotated[List[str], operator.add]
    
    # Final output
    final_output: str
    success: bool
    metadata: Dict[str, Any]
    
    # Code generation specific
    code: str
    files: Dict[str, str]
    language: str
    
    # Reflection
    needs_improvement: bool
    improvement_suggestions: List[str]


# ===== GRAPH NODES =====

class LangGraphOrchestrator:
    """
    LangGraph-based multi-agent orchestrator with memory
    """
    
    def __init__(self):
        self.context_builder = context_builder
        self.memory_service = memory_service
        self.llm = llm_adapter
        
        # Build the graph
        self.graph = self._build_graph()
        
        logger.info("✅ LangGraph Orchestrator initialized")
    
    def _build_graph(self) -> StateGraph:
        """Build the agent state graph"""
        
        # Create graph
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("load_context", self._load_context_node)
        workflow.add_node("route", self._route_node)
        workflow.add_node("code_agent", self._code_agent_node)
        workflow.add_node("desktop_agent", self._desktop_agent_node)
        workflow.add_node("general_agent", self._general_agent_node)
        workflow.add_node("reflect", self._reflect_node)
        workflow.add_node("save_memory", self._save_memory_node)
        
        # Define edges
        workflow.set_entry_point("load_context")
        
        # Context → Router
        workflow.add_edge("load_context", "route")
        
        # Router → Specialists (conditional)
        workflow.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "coding": "code_agent",
                "desktop": "desktop_agent",
                "general": "general_agent"
            }
        )
        
        # Specialists → Reflect
        workflow.add_edge("code_agent", "reflect")
        workflow.add_edge("desktop_agent", "reflect")
        workflow.add_edge("general_agent", "reflect")
        
        # Reflect → Save Memory or Loop (conditional)
        workflow.add_conditional_edges(
            "reflect",
            self._reflect_decision,
            {
                "save": "save_memory",
                "improve": "route"  # Loop back for improvement
            }
        )
        
        # Save Memory → END
        workflow.add_edge("save_memory", END)
        
        return workflow.compile()
    
    # ===== NODE IMPLEMENTATIONS =====
    
    async def _load_context_node(self, state: AgentState) -> AgentState:
        """Load user context and conversation history"""
        logger.info("📚 Loading context...")
        
        try:
            # Build personalized context
            user_context = self.context_builder.build_user_context(
                user_id=state['user_id'],
                current_message=state['user_message'],
                conversation_id=state['conversation_id']
            )
            
            # Load recent conversation
            conversation_history = self.memory_service.get_conversation_history(
                state['conversation_id'], limit=10
            )
            
            state['user_context'] = user_context
            state['conversation_history'] = conversation_history
            state['agent_path'] = ['context_loader']
            
            logger.info(f"✅ Loaded context ({len(user_context)} chars)")
        
        except Exception as e:
            logger.error(f"❌ Error loading context: {e}")
            state['errors'] = [f"Context loading error: {str(e)}"]
        
        return state
    
    async def _route_node(self, state: AgentState) -> AgentState:
        """Route to appropriate specialist agent"""
        logger.info("🎯 Routing task...")
        
        try:
            # Classify with user context
            classification = router_agent.classify_task(
                user_message=state['user_message'],
                user_context=state['user_context']
            )
            
            state['task_type'] = classification['task_type']
            state['confidence'] = classification['confidence']
            state['routing_reason'] = classification.get('reasoning', '')
            state['agent_path'].append('router')
            
            logger.info(
                f"📍 Routed to: {classification['task_type']} "
                f"({classification['confidence']:.0%})"
            )
        
        except Exception as e:
            logger.error(f"❌ Routing error: {e}")
            state['task_type'] = 'general'  # Fallback
            state['errors'].append(f"Routing error: {str(e)}")
        
        return state
    
    def _route_decision(self, state: AgentState) -> str:
        """Decide which agent to use"""
        return state.get('task_type', 'general')
    
    async def _code_agent_node(self, state: AgentState) -> AgentState:
        """Code generation specialist"""
        logger.info("💻 Code Agent processing...")
        
        try:
            # Import here to avoid circular dependency
            from app.agents.code_specialist_agent import code_specialist
            
            # Build messages with context
            messages = self._build_messages_with_context(state)
            
            # Call code specialist
            # (Your existing code specialist logic)
            result = await code_specialist.generate_code(
                description=state['user_message'],
                conversation_history=messages
            )
            
            state['current_output'] = result.get('explanation', '')
            state['code'] = result.get('code', '')
            state['files'] = result.get('files', {})
            state['language'] = result.get('language', '')
            state['agent_path'].append('code_specialist')
            state['success'] = result.get('success', True)
        
        except Exception as e:
            logger.error(f"❌ Code agent error: {e}")
            state['current_output'] = f"Code generation failed: {str(e)}"
            state['errors'].append(f"Code agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _desktop_agent_node(self, state: AgentState) -> AgentState:
        """Desktop automation specialist"""
        logger.info("🖥️ Desktop Agent processing...")
        
        try:
            # Build messages with context
            messages = self._build_messages_with_context(state)
            
            # Import skills
            from app.skills.manager import skill_manager
            from app.skills.executor import skill_executor
            
            # Get desktop tools
            tools = skill_manager.get_skills_for_llm()
            formatted_tools = [{"type": "function", "function": t} for t in tools]
            
            # Call LLM with tools
            llm_result = await self.llm.generate_response(
                messages, tools=formatted_tools
            )
            
            # Execute tools if requested
            if llm_result.get("tool_calls"):
                import json
                for tool_call in llm_result["tool_calls"]:
                    skill_name = tool_call["function"]["name"]
                    args = json.loads(tool_call["function"]["arguments"])
                    
                    result = await skill_executor.execute_skill(
                        skill_name, args, state['user_id']
                    )
                    
                    logger.info(f"🔧 Executed: {skill_name}")
            
            state['current_output'] = llm_result.get('response', '')
            state['agent_path'].append('desktop_specialist')
            state['success'] = True
        
        except Exception as e:
            logger.error(f"❌ Desktop agent error: {e}")
            state['current_output'] = f"Desktop automation failed: {str(e)}"
            state['errors'].append(f"Desktop agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _general_agent_node(self, state: AgentState) -> AgentState:
        """General conversation agent"""
        logger.info("💬 General Agent processing...")
        
        try:
            # Build messages with context
            messages = self._build_messages_with_context(state)
            
            # Call LLM
            llm_result = await self.llm.generate_response(messages)
            
            state['current_output'] = llm_result.get('response', '')
            state['agent_path'].append('general_assistant')
            state['success'] = True
        
        except Exception as e:
            logger.error(f"❌ General agent error: {e}")
            state['current_output'] = f"Response generation failed: {str(e)}"
            state['errors'].append(f"General agent error: {str(e)}")
            state['success'] = False
        
        return state
    
    async def _reflect_node(self, state: AgentState) -> AgentState:
        """Reflect on output quality and decide if improvement needed"""
        logger.info("🤔 Reflecting on output...")
        
        try:
            # Simple reflection logic (can be enhanced with LLM)
            needs_improvement = False
            suggestions = []
            
            # Check for errors
            if state.get('errors'):
                needs_improvement = True
                suggestions.append("Fix errors that occurred")
            
            # Check if iteration limit reached
            if state.get('iteration', 0) >= state.get('max_iterations', 3):
                needs_improvement = False  # Stop iteration
            
            # Check if output is empty
            if not state.get('current_output'):
                needs_improvement = True
                suggestions.append("Generate actual output")
            
            state['needs_improvement'] = needs_improvement
            state['improvement_suggestions'] = suggestions
            state['agent_path'].append('reflection')
            
            if needs_improvement:
                logger.warning(f"⚠️ Needs improvement: {suggestions}")
                state['iteration'] = state.get('iteration', 0) + 1
            else:
                logger.info("✅ Output quality acceptable")
                state['final_output'] = state['current_output']
        
        except Exception as e:
            logger.error(f"❌ Reflection error: {e}")
            state['needs_improvement'] = False
            state['final_output'] = state.get('current_output', '')
        
        return state
    
    def _reflect_decision(self, state: AgentState) -> str:
        """Decide whether to save or improve"""
        if state.get('needs_improvement', False):
            return "improve"
        else:
            return "save"
    
    async def _save_memory_node(self, state: AgentState) -> AgentState:
        """Save interaction to memory"""
        logger.info("💾 Saving to memory...")
        
        try:
            # Save user message to SQL
            self.memory_service.save_message(
                conversation_id=state['conversation_id'],
                user_id=state['user_id'],
                role='user',
                content=state['user_message'],
                metadata={'context_used': bool(state.get('user_context'))}
            )
            
            # Save assistant response to SQL
            self.memory_service.save_message(
                conversation_id=state['conversation_id'],
                user_id=state['user_id'],
                role='assistant',
                content=state.get('final_output', ''),
                metadata={
                    'task_type': state.get('task_type'),
                    'agent_path': state.get('agent_path', []),
                    'success': state.get('success', True)
                }
            )
            
            # Extract and save insights (every 5 messages)
            messages = self.memory_service.get_conversation_history(
                state['conversation_id']
            )
            if len(messages) % 5 == 0:
                self.context_builder.extract_and_save_insights(
                    user_id=state['user_id'],
                    conversation_id=state['conversation_id']
                )
            
            # Learn from behavior
            if state.get('task_type') == 'coding':
                self.memory_service.learn_from_behavior(
                    user_id=state['user_id'],
                    task_data={
                        'task_type': 'coding',
                        'language': state.get('language'),
                        'success': state.get('success', True)
                    }
                )
            
            state['agent_path'].append('memory_saver')
            logger.info("✅ Saved to memory")
        
        except Exception as e:
            logger.error(f"❌ Memory save error: {e}")
            state['errors'].append(f"Memory save error: {str(e)}")
        
        return state
    
    # ===== HELPER METHODS =====
    
    def _build_messages_with_context(self, state: AgentState) -> List:
        """Build message list with context for LLM"""
        from app.models import Message, MessageRole
        
        messages = []
        
        # Add system message with context
        if state.get('user_context'):
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=state['user_context']
            ))
        
        # Add conversation history
        for msg in state.get('conversation_history', [])[-5:]:
            role = MessageRole.USER if msg['role'] == 'user' else MessageRole.ASSISTANT
            messages.append(Message(
                role=role,
                content=msg['content']
            ))
        
        # Add current message
        messages.append(Message(
            role=MessageRole.USER,
            content=state['user_message']
        ))
        
        return messages
    
    # ===== PUBLIC INTERFACE =====
    
    async def process(
        self,
        user_message: str,
        user_id: str,
        conversation_id: str,
        max_iterations: int = 3,
        message_callback: Any = None
    ) -> Dict:
        """
        Process user message through the agent graph
        
        Args:
            user_message: User's message
            user_id: User identifier
            conversation_id: Conversation ID
            max_iterations: Max improvement iterations
            message_callback: Callback for progress updates
            
        Returns:
            Final state dict
        """
        logger.info(f"🚀 Processing: '{user_message[:50]}...'")
        
        # Initialize state
        initial_state = AgentState(
            user_message=user_message,
            user_id=user_id,
            conversation_id=conversation_id,
            user_context="",
            conversation_history=[],
            task_type="general",
            confidence=0.0,
            routing_reason="",
            agent_path=[],
            current_output="",
            iteration=0,
            max_iterations=max_iterations,
            errors=[],
            final_output="",
            success=False,
            metadata={},
            code="",
            files={},
            language="",
            needs_improvement=False,
            improvement_suggestions=[]
        )
        
        # Run the graph
        try:
            final_state = await self.graph.ainvoke(initial_state)
            
            # Format response
            response = {
                "success": final_state.get('success', True),
                "output": final_state.get('final_output', ''),
                "task_type": final_state.get('task_type'),
                "confidence": final_state.get('confidence', 0.0),
                "agent_path": final_state.get('agent_path', []),
                "code": final_state.get('code'),
                "files": final_state.get('files'),
                "language": final_state.get('language'),
                "metadata": {
                    "iterations": final_state.get('iteration', 0),
                    "errors": final_state.get('errors', []),
                    "context_used": bool(final_state.get('user_context'))
                }
            }
            
            logger.info(f"✅ Completed with {len(final_state.get('agent_path', []))} steps")
            return response
        
        except Exception as e:
            logger.error(f"❌ Graph execution error: {e}")
            return {
                "success": False,
                "output": f"System error: {str(e)}",
                "task_type": "error",
                "confidence": 0.0,
                "agent_path": ["error"],
                "metadata": {"error": str(e)}
            }


# Global instance
langgraph_orchestrator = LangGraphOrchestrator()