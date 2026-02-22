"""
LLM Adapter for Google Gemini API integration
"""
import os
import json
import asyncio
import re
from typing import List, Dict, Optional
from app.config import settings
from app.models import Message, MessageRole
from loguru import logger
import google.generativeai as genai


class GeminiLLMAdapter:
    """Adapter for Google Gemini LLM API with function calling support"""

    def __init__(self):
        """Initialize Gemini client"""
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("⚠️ GOOGLE_API_KEY not set — LLM will fail")

        genai.configure(api_key=api_key)
        self.model_name = getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
        self.max_tokens = getattr(settings, "GEMINI_MAX_TOKENS", 2048)
        self.temperature = getattr(settings, "GEMINI_TEMPERATURE", 0.7)

        logger.info(f"Initialized Gemini LLM with model: {self.model_name}")

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """
        Convert Message objects to a simple list of dicts.
        Used by agent.py when building the tool-call follow-up conversation.

        Returns:
            List of message dicts with 'role' and 'content'
        """
        formatted = []
        for msg in messages:
            formatted.append({
                "role": msg.role.value,
                "content": msg.content
            })
        return formatted

    def _build_gemini_tools(self, tools: List[Dict]) -> List:
        """
        Convert OpenAI/Groq-style tool definitions to Gemini function declarations.

        Input format (from skill_manager):
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]

        Output: list of tool dicts for Gemini
        """
        function_declarations = []
        for tool in tools:
            func_def = tool.get("function", tool)
            name = func_def.get("name", "")
            description = func_def.get("description", "")
            parameters = func_def.get("parameters", {})

            # Clean up parameters for Gemini (remove unsupported keys)
            cleaned_params = self._clean_parameters(parameters)

            decl = {
                "name": name,
                "description": description,
            }
            if cleaned_params and cleaned_params.get("properties"):
                decl["parameters"] = cleaned_params

            function_declarations.append(decl)

        # Use dict-based tool format for maximum compatibility
        return [{"function_declarations": function_declarations}]

    def _clean_parameters(self, params: dict) -> dict:
        """Clean parameter schema to be compatible with Gemini API."""
        if not params:
            return {}

        cleaned = {}
        if "type" in params:
            cleaned["type"] = params["type"].upper() if params["type"] in ("string", "number", "integer", "boolean", "array", "object") else params["type"]
        if "description" in params:
            cleaned["description"] = params["description"]
        if "properties" in params:
            cleaned["properties"] = {}
            for prop_name, prop_val in params["properties"].items():
                cleaned["properties"][prop_name] = self._clean_parameters(prop_val)
        if "required" in params:
            cleaned["required"] = params["required"]
        if "items" in params:
            cleaned["items"] = self._clean_parameters(params["items"])
        if "enum" in params:
            cleaned["enum"] = params["enum"]

        return cleaned

    async def generate_response(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, any]:
        """
        Generate response from Gemini LLM

        Args:
            messages: Conversation history
            tools: Optional list of function/tool definitions
            temperature: Override default temperature
            max_tokens: Override default max tokens

        Returns:
            Dict with response text and metadata (including tool calls if any)
        """
        try:
            # Separate system prompt from conversation
            system_instruction = None
            chat_messages = []

            formatted = self._format_messages(messages)

            # Add system prompt if not present
            if not any(msg["role"] == "system" for msg in formatted):
                system_instruction = settings.SYSTEM_PROMPT
            else:
                for msg in formatted:
                    if msg["role"] == "system":
                        system_instruction = msg["content"]
                    else:
                        chat_messages.append(msg)

            if not chat_messages:
                chat_messages = [m for m in formatted if m["role"] != "system"]

            # Build Gemini contents (convert role names)
            contents = []
            for msg in chat_messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })

            # Ensure conversation doesn't start with model
            if contents and contents[0]["role"] == "model":
                contents.insert(0, {"role": "user", "parts": [{"text": "Hello"}]})

            logger.debug(f"Sending {len(contents)} messages to Gemini")

            # Build model config
            generation_config = {
                "temperature": temperature or self.temperature,
                "max_output_tokens": max_tokens or self.max_tokens,
            }

            # Create model with system instruction and tools
            model_kwargs = {
                "generation_config": generation_config,
            }
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            gemini_tools = None
            if tools:
                gemini_tools = self._build_gemini_tools(tools)
                model_kwargs["tools"] = gemini_tools
                # Tell Gemini to use AUTO function calling mode
                model_kwargs["tool_config"] = {
                    "function_calling_config": {"mode": "AUTO"}
                }
                logger.info(f"Enabled tool calling with {len(tools)} tools (AUTO mode)")

            model = genai.GenerativeModel(self.model_name, **model_kwargs)

            # Call Gemini API (run in thread to avoid blocking async event loop)
            response = await asyncio.to_thread(model.generate_content, contents)

            # Parse response
            result = {
                "model": self.model_name,
                "tokens_used": None,  # Gemini doesn't always expose this the same way
                "finish_reason": "stop"
            }

            # Try to get token count
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                result["tokens_used"] = getattr(response.usage_metadata, 'total_token_count', None)

            # Check for function calls
            candidate = response.candidates[0] if response.candidates else None
            if candidate and candidate.content and candidate.content.parts:
                tool_calls_found = []
                text_parts = []

                for i, part in enumerate(candidate.content.parts):
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        # Convert Gemini function_call to the format agent.py expects
                        tool_calls_found.append({
                            "id": f"call_{i}_{fc.name}",
                            "type": "function",
                            "function": {
                                "name": fc.name,
                                "arguments": json.dumps(dict(fc.args)) if fc.args else "{}"
                            }
                        })
                    elif hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)

                if tool_calls_found:
                    result["tool_calls"] = tool_calls_found
                    result["response"] = " ".join(text_parts) if text_parts else ""
                    result["finish_reason"] = "tool_calls"
                    logger.info(f"LLM requested {len(tool_calls_found)} tool calls")
                else:
                    result["response"] = " ".join(text_parts)
                    logger.info(f"Gemini response generated: {result.get('tokens_used', '?')} tokens used")
            else:
                # Fallback
                try:
                    result["response"] = response.text
                except Exception:
                    result["response"] = "I couldn't generate a response. Please try again."

            # Fallback: if no structured tool_calls, check for text-based tool calls
            if "tool_calls" not in result and result.get("response"):
                text_tool_calls = self._parse_text_tool_calls(result["response"])
                if text_tool_calls:
                    result["tool_calls"] = text_tool_calls
                    result["finish_reason"] = "tool_calls"
                    # Remove tool call text from response
                    result["response"] = re.sub(
                        r'```(?:tool_code|python)?\s*\n?.*?```',
                        '', result["response"], flags=re.DOTALL
                    ).strip()
                    logger.info(f"Parsed {len(text_tool_calls)} tool calls from text fallback")

            return result

        except Exception as e:
            logger.error(f"Error calling Gemini API: {str(e)}")
            raise

    def _parse_text_tool_calls(self, text: str) -> List[Dict]:
        """
        Fallback: parse tool calls from text when Gemini outputs them as code blocks.
        Handles patterns like:
          ```tool_code
          desktop_app_launcher(app="chrome")
          ```
        or inline: desktop_app_launcher(app="chrome")
        """
        tool_calls = []
        
        # Get all known skill names
        known_skills = set()
        try:
            from app.skills.manager import skill_manager
            known_skills = set(skill_manager.skills.keys())
        except Exception:
            pass
        
        if not known_skills:
            return []
        
        # Pattern: skill_name(arg1="val1", arg2="val2")
        # Build regex from known skill names
        skill_pattern = '|'.join(re.escape(s) for s in known_skills)
        pattern = rf'({skill_pattern})\s*\(([^)]*)\)'
        
        matches = re.findall(pattern, text)
        
        for i, (func_name, args_str) in enumerate(matches):
            # Parse arguments from function-call-like syntax
            args = {}
            if args_str.strip():
                # Match key="value" or key='value' or key=value patterns
                arg_pattern = r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))'
                arg_matches = re.findall(arg_pattern, args_str)
                for key, val1, val2, val3 in arg_matches:
                    args[key] = val1 or val2 or val3
            
            tool_calls.append({
                "id": f"text_call_{i}_{func_name}",
                "type": "function",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps(args)
                }
            })
            logger.info(f"Parsed text tool call: {func_name}({args})")
        
        return tool_calls

    async def check_health(self) -> bool:
        """
        Check if Gemini API is accessible

        Returns:
            Boolean indicating API health
        """
        try:
            model = genai.GenerativeModel(self.model_name)
            response = await asyncio.to_thread(model.generate_content, "Hello")
            return bool(response.text)
        except Exception as e:
            logger.error(f"Gemini health check failed: {str(e)}")
            return False


# Global LLM adapter instance
llm_adapter = GeminiLLMAdapter()