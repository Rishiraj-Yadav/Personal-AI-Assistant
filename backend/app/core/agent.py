"""
Agent Orchestrator
Main agent logic that coordinates LLM and state management
"""
import json
from typing import Dict, Optional, List
from app.models import Message, MessageRole
from app.core.llm import llm_adapter
from app.core.state import state_manager
from app.skills.manager import skill_manager
from app.skills.executor import skill_executor
from loguru import logger


class AgentOrchestrator:
    """
    Main agent that handles requests and orchestrates components
    """
    
    def __init__(self):
        """Initialize agent orchestrator"""
        self.llm = llm_adapter
        self.state = state_manager
        self.skill_manager = skill_manager
        self.skill_executor = skill_executor
        
        # Load available skills
        loaded = self.skill_manager.load_skills()
        logger.info(f"Initialized AgentOrchestrator with {loaded} skills")
    
    async def process_message(
        self,
        user_message: str,
        conversation_id: Optional[str] = None,
        user_id: str = "default_user"
    ) -> Dict:
        """
        Process user message and generate response
        
        Args:
            user_message: User's input message
            conversation_id: Optional existing conversation ID
            user_id: User identifier
            
        Returns:
            Dict with response and metadata
        """
        try:
            # Create or retrieve conversation
            if not conversation_id:
                conversation_id = self.state.create_conversation(user_id)
                logger.info(f"Created new conversation: {conversation_id}")
            else:
                # Verify conversation exists
                if not self.state.get_conversation(conversation_id):
                    logger.warning(f"Conversation {conversation_id} not found, creating new")
                    conversation_id = self.state.create_conversation(user_id)
            
            # Add user message to state
            self.state.add_message(
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content=user_message
            )
            
            # Get conversation history
            messages = self.state.get_messages(conversation_id)
            
            logger.info(f"Processing message in conversation {conversation_id} with {len(messages)} messages")
            
            # Get available tools/skills for LLM
            tools = self._get_tools_for_llm()
            
            # Generate response from LLM (may include tool calls)
            llm_result = await self.llm.generate_response(messages, tools=tools)
            
            # Check if LLM wants to use tools
            if "tool_calls" in llm_result and llm_result["tool_calls"]:
                # Execute tool calls and get final response
                final_response = await self._handle_tool_calls(
                    llm_result["tool_calls"],
                    messages,
                    tools,
                    conversation_id
                )
                response_text = final_response["response"]
                skill_results = final_response.get("skill_results", [])
            else:
                # Direct text response
                response_text = llm_result["response"]
                skill_results = []
            
            # Add assistant response to state
            self.state.add_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                metadata={
                    "model": llm_result["model"],
                    "tokens_used": llm_result["tokens_used"],
                    "skills_used": [s["skill_name"] for s in skill_results] if skill_results else []
                }
            )
            
            # Return response
            return {
                "response": response_text,
                "conversation_id": conversation_id,
                "model_used": llm_result["model"],
                "tokens_used": llm_result["tokens_used"],
                "skills_used": skill_results
            }
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            raise
    
    def _get_tools_for_llm(self) -> List[Dict]:
        """
        Get skill definitions formatted for LLM tool calling
        
        Returns:
            List of tool definitions
        """
        skills = self.skill_manager.get_skills_for_llm()
        
        # Convert to Groq tool format
        tools = []
        for skill in skills:
            tools.append({
                "type": "function",
                "function": skill
            })
        
        return tools
    
    async def _handle_tool_calls(
        self,
        tool_calls: List[Dict],
        conversation_history: List[Message],
        tools: List[Dict],
        conversation_id: str
    ) -> Dict:
        """
        Execute tool calls and get final response
        
        Args:
            tool_calls: List of tool calls from LLM
            conversation_history: Current conversation
            tools: Available tools
            conversation_id: Conversation ID
            
        Returns:
            Dict with final response and skill results
        """
        skill_results = []
        
        # Execute each tool call
        for tool_call in tool_calls:
            skill_name = tool_call["function"]["name"]
            
            try:
                # Parse arguments
                arguments = json.loads(tool_call["function"]["arguments"])
                
                logger.info(f"Executing skill: {skill_name} with args: {arguments}")
                
                # Execute skill
                result = await self.skill_executor.execute_skill(
                    skill_name=skill_name,
                    parameters=arguments
                )
                
                skill_results.append({
                    "skill_name": skill_name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error
                })
                
                # Add tool result to conversation
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(result.output) if result.success else result.error
                }
                
                # Get final response from LLM with tool results
                messages_with_tool = self.llm._format_messages(conversation_history)
                
                # Add assistant message with tool call
                messages_with_tool.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": skill_name,
                            "arguments": tool_call["function"]["arguments"]
                        }
                    }]
                })
                
                # Add tool response
                messages_with_tool.append(tool_message)
                
                # Get LLM's interpretation/summary
                final_response = await self.llm.generate_response(
                    [Message(role=MessageRole.USER, content=m["content"]) 
                     for m in messages_with_tool if m.get("role") != "tool"],
                    tools=None  # Don't allow recursive tool calls for now
                )
                
            except Exception as e:
                logger.error(f"Error executing skill {skill_name}: {str(e)}")
                skill_results.append({
                    "skill_name": skill_name,
                    "success": False,
                    "output": None,
                    "error": str(e)
                })
                final_response = {
                    "response": f"I encountered an error while using the {skill_name} skill: {str(e)}"
                }
        
        return {
            "response": final_response.get("response", ""),
            "skill_results": skill_results
        }
    
    async def get_conversation_history(
        self,
        conversation_id: str
    ) -> Optional[Dict]:
        """
        Retrieve conversation history
        
        Args:
            conversation_id: Conversation identifier
            
        Returns:
            Conversation data or None
        """
        conversation = self.state.get_conversation(conversation_id)
        
        if not conversation:
            return None
        
        return {
            "conversation_id": conversation.conversation_id,
            "user_id": conversation.user_id,
            "message_count": len(conversation.messages),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "messages": [
                {
                    "role": msg.role.value,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat()
                }
                for msg in conversation.messages
            ]
        }
    
    async def clear_conversation(self, conversation_id: str) -> bool:
        """
        Clear conversation history
        
        Args:
            conversation_id: Conversation identifier
            
        Returns:
            Success boolean
        """
        return self.state.clear_conversation(conversation_id)
    
    async def health_check(self) -> Dict:
        """
        Perform health check on agent and dependencies
        
        Returns:
            Health status dict
        """
        groq_healthy = await self.llm.check_health()
        state_stats = self.state.get_stats()
        
        return {
            "agent_status": "healthy",
            "groq_api_status": "healthy" if groq_healthy else "unhealthy",
            "state_manager": state_stats
        }


# Global agent instance
agent = AgentOrchestrator()