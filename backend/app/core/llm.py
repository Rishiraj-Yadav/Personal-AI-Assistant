"""
LLM Adapter for Groq API integration
"""
from groq import Groq, AsyncGroq
from typing import List, Dict, Optional
from app.config import settings
from app.models import Message, MessageRole
from loguru import logger


class GroqLLMAdapter:
    """Adapter for Groq LLM API"""
    
    def __init__(self):
        """Initialize Groq client"""
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL
        self.max_tokens = settings.GROQ_MAX_TOKENS
        self.temperature = settings.GROQ_TEMPERATURE
        
        logger.info(f"Initialized Groq LLM with model: {self.model}")
    
    def _format_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """
        Convert Message objects to Groq API format
        
        Args:
            messages: List of Message objects
            
        Returns:
            List of message dicts for Groq API
        """
        formatted = []
        
        for msg in messages:
            formatted.append({
                "role": msg.role.value,
                "content": msg.content
            })
        
        return formatted
    
    async def generate_response(
        self, 
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """
        Generate response from Groq LLM
        
        Args:
            messages: Conversation history
            tools: Optional list of function/tool definitions
            temperature: Override default temperature
            max_tokens: Override default max tokens
            
        Returns:
            Dict with response text and metadata (including tool calls if any)
        """
        try:
            # Format messages for API
            formatted_messages = self._format_messages(messages)
            
            # Add system prompt if not present
            if not any(msg["role"] == "system" for msg in formatted_messages):
                formatted_messages.insert(0, {
                    "role": "system",
                    "content": settings.SYSTEM_PROMPT
                })
            
            logger.debug(f"Sending {len(formatted_messages)} messages to Groq")
            
            # Prepare API call parameters
            api_params = {
                "model": self.model,
                "messages": formatted_messages,
                "temperature": temperature or self.temperature,
                "max_tokens": max_tokens or self.max_tokens,
                "top_p": 1,
                "stream": False
            }
            
            # Add tools if provided (function calling)
            if tools:
                api_params["tools"] = tools
                api_params["tool_choice"] = "auto"
                logger.debug(f"Enabled tool calling with {len(tools)} tools")
            
            # Call Groq API
            response = await self.client.chat.completions.create(**api_params)
            
            # Extract response
            choice = response.choices[0]
            tokens_used = response.usage.total_tokens if response.usage else None
            
            result = {
                "model": self.model,
                "tokens_used": tokens_used,
                "finish_reason": choice.finish_reason
            }
            
            # Check if tool was called
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                result["tool_calls"] = []
                for tool_call in choice.message.tool_calls:
                    result["tool_calls"].append({
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
                result["response"] = choice.message.content or ""
                logger.info(f"LLM requested {len(result['tool_calls'])} tool calls")
            else:
                # Normal text response
                result["response"] = choice.message.content
                logger.info(f"Groq response generated: {tokens_used} tokens used")
            
            return result
            
        except Exception as e:
            logger.error(f"Error calling Groq API: {str(e)}")
            raise
    
    async def check_health(self) -> bool:
        """
        Check if Groq API is accessible
        
        Returns:
            Boolean indicating API health
        """
        try:
            # Try a minimal API call
            test_messages = [{
                "role": "user",
                "content": "Hello"
            }]
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=test_messages,
                max_tokens=5
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Groq health check failed: {str(e)}")
            return False


# Global LLM adapter instance
llm_adapter = GroqLLMAdapter()