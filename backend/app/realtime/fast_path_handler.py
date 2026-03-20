"""
Fast Path Handler - Phase 3 + Phase 6 Integration
==================================================

Main entry point for real-time message handling.
Integrates fast intent classification, routing, and Phase 6 components.
"""

import time
import asyncio
import aiohttp
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime, timezone
from loguru import logger

from .fast_intent_classifier import fast_intent_classifier, IntentType, IntentResult
from .fast_router import fast_router, RoutingPath, RoutingDecision
from .simple_responder import simple_responder
from .response_sanitizer import response_sanitizer

# Phase 6 components
from app.core.master_router import get_master_router, RoutingPath as Phase6RoutingPath
from app.core.task_state_machine import get_task_state_machine, TaskTransition
from app.core.execution_feedback import get_feedback_loop, FeedbackStatus
from app.core.predictive_context import get_predictive_context_manager

# Config
from app.config import settings


@dataclass
class FastPathResult:
    """Result of fast path handling."""
    success: bool
    response: str
    intent_type: str
    is_fast_path: bool
    total_time_ms: float
    action_taken: Optional[str] = None
    target: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class FastPathHandler:
    """
    Main handler for fast-path message processing.
    
    Flow:
    1. Classify intent (fast pattern matching)
    2. Route based on confidence
    3. Execute via fast path or delegate to orchestration
    4. Return result with feedback
    """
    
    def __init__(self):
        """Initialize the fast path handler."""
        # Phase 6 components
        self.master_router = get_master_router()
        self.task_machine = get_task_state_machine()
        self.feedback_loop = get_feedback_loop(
            context_updater=self._update_context,
            on_fallback=self._handle_fallback
        )
        self.context_manager = get_predictive_context_manager()
        
        # HTTP client for desktop agent
        self._http_session: Optional[aiohttp.ClientSession] = None
        
        # Desktop agent URL
        self._desktop_url = getattr(settings, 'DESKTOP_AGENT_URL', 'http://localhost:7777')
        self._desktop_api_key = ""  # Will be loaded from config
        
        logger.info("✅ FastPathHandler initialized with Phase 6 integration")
    
    async def _ensure_http_session(self):
        """Ensure HTTP session is initialized."""
        if not self._http_session:
            self._http_session = aiohttp.ClientSession()
    
    async def handle(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
        stream_callback: Optional[Callable] = None
    ) -> FastPathResult:
        """
        Handle a user message through the fast path.
        
        Args:
            message: User's message
            user_id: User identifier
            conversation_id: Conversation identifier
            stream_callback: Optional callback for streaming updates
            
        Returns:
            FastPathResult with response and metadata
        """
        start_time = time.time()
        
        # Get context for routing
        context = self.context_manager.get_context_for_resolution()
        
        # Create task in state machine
        task = self.task_machine.create_task(
            user_message=message,
            session_id=user_id,
            conversation_id=conversation_id,
            context_snapshot=context
        )
        
        # Start task
        self.task_machine.transition(task.task_id, TaskTransition.START)
        
        try:
            # Send thinking message
            if stream_callback:
                await stream_callback({
                    "type": "thinking",
                    "message": "🧠 Analyzing your request...",
                    "request_id": task.task_id
                })
            
            # Step 1: Classify intent
            self.task_machine.transition(task.task_id, TaskTransition.VALIDATE)
            intent_result = fast_intent_classifier.classify(message, context)
            
            # Step 2: Route based on confidence
            self.task_machine.transition(task.task_id, TaskTransition.ROUTE)
            routing = fast_router.route(intent_result)
            
            if stream_callback:
                await stream_callback({
                    "type": "thinking",
                    "message": f"📍 Intent: {intent_result.intent_type.value} ({intent_result.confidence:.0%})",
                    "intent": intent_result.intent_type.value,
                    "confidence": intent_result.confidence,
                    "routing_path": routing.path.value
                })
            
            # Step 3: Execute based on routing path
            self.task_machine.transition(
                task.task_id,
                TaskTransition.EXECUTE,
                {"routing_decision": routing.to_dict()}
            )
            
            if routing.path == RoutingPath.FAST_RESPONSE:
                # Simple response (no tools)
                result = await self._handle_fast_response(message, intent_result, stream_callback)
                
            elif routing.path == RoutingPath.FAST_DESKTOP:
                # Direct desktop execution
                result = await self._handle_fast_desktop(
                    message, intent_result, routing, stream_callback
                )
                
            elif routing.path == RoutingPath.DISAMBIGUATE:
                # Need clarification
                result = await self._handle_disambiguation(
                    message, intent_result, routing, stream_callback
                )
                
            else:
                # Full orchestration
                result = await self._handle_full_orchestration(
                    message, user_id, conversation_id, intent_result, stream_callback
                )
            
            # Step 4: Verify and complete
            self.task_machine.transition(task.task_id, TaskTransition.VERIFY)
            
            total_time_ms = (time.time() - start_time) * 1000
            
            # Complete task
            self.task_machine.transition(
                task.task_id,
                TaskTransition.COMPLETE,
                {"execution_result": result}
            )
            
            return FastPathResult(
                success=True,
                response=result.get("response", ""),
                intent_type=intent_result.intent_type.value,
                is_fast_path=routing.path in [RoutingPath.FAST_RESPONSE, RoutingPath.FAST_DESKTOP],
                total_time_ms=total_time_ms,
                action_taken=intent_result.action,
                target=intent_result.target,
                metadata={
                    "task_id": task.task_id,
                    "routing_path": routing.path.value,
                    "confidence": intent_result.confidence,
                }
            )
            
        except Exception as e:
            logger.error(f"❌ Fast path error: {e}")
            
            # Fail task
            self.task_machine.transition(
                task.task_id,
                TaskTransition.FAIL,
                {"error": str(e)}
            )
            
            total_time_ms = (time.time() - start_time) * 1000
            
            return FastPathResult(
                success=False,
                response=f"Sorry, I encountered an error: {str(e)}",
                intent_type=intent_result.intent_type.value if intent_result else "unknown",
                is_fast_path=False,
                total_time_ms=total_time_ms,
                metadata={"error": str(e), "task_id": task.task_id}
            )
    
    async def _handle_fast_response(
        self,
        message: str,
        intent_result: IntentResult,
        stream_callback: Optional[Callable]
    ) -> Dict[str, Any]:
        """Handle simple responses without tool execution."""
        simple_response = simple_responder.respond(message)
        
        if simple_response:
            response_text = simple_response.response
        else:
            response_text = "I'm not sure how to help with that. Could you be more specific?"
        
        if stream_callback:
            await stream_callback({
                "type": "stream_chunk",
                "content": response_text
            })
            await stream_callback({
                "type": "stream_end"
            })
        
        return {"response": response_text, "success": True}
    
    async def _handle_fast_desktop(
        self,
        message: str,
        intent_result: IntentResult,
        routing: RoutingDecision,
        stream_callback: Optional[Callable]
    ) -> Dict[str, Any]:
        """Handle fast-path desktop commands."""
        action = intent_result.action
        target = intent_result.target
        
        if stream_callback:
            await stream_callback({
                "type": "action_started",
                "action_type": "desktop_control",
                "description": f"Executing: {action}",
                "target": target
            })
        
        # Resolve target using context
        resolved_target = target
        if target and "project" in target.lower():
            suggestions = self.context_manager.suggest_paths(target, limit=1)
            if suggestions:
                resolved_target = suggestions[0]
                logger.info(f"📁 Resolved '{target}' → '{resolved_target}'")
        
        # Execute on desktop agent
        start_time = time.time()
        result = await self._execute_on_desktop(action, resolved_target, intent_result.parameters)
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Process feedback
        feedback = self.feedback_loop.process(
            action=action,
            target=resolved_target,
            execution_result=result,
            execution_time_ms=execution_time_ms
        )
        
        if feedback.is_success:
            response = self._generate_success_response(action, resolved_target)
            
            if stream_callback:
                await stream_callback({
                    "type": "action_completed",
                    "action_type": "desktop_control",
                    "success": True,
                    "target": resolved_target
                })
                await stream_callback({
                    "type": "stream_chunk",
                    "content": response
                })
                await stream_callback({
                    "type": "stream_end"
                })
            
            return {"response": response, "success": True, "target": resolved_target}
        
        else:
            # Check if fallback is needed
            if feedback.needs_fallback:
                logger.info(f"🔄 Desktop action failed, falling back to orchestration")
                return await self._handle_full_orchestration(
                    message, "", "", intent_result, stream_callback
                )
            
            error_response = f"Sorry, I couldn't {action}. {feedback.error or 'Unknown error'}"
            
            if stream_callback:
                await stream_callback({
                    "type": "action_failed",
                    "action_type": "desktop_control",
                    "error": feedback.error
                })
                await stream_callback({
                    "type": "stream_chunk",
                    "content": error_response
                })
                await stream_callback({
                    "type": "stream_end"
                })
            
            return {"response": error_response, "success": False, "error": feedback.error}
    
    async def _execute_on_desktop(
        self,
        action: str,
        target: Optional[str],
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an action on the desktop agent."""
        await self._ensure_http_session()
        
        # Map Phase 6 actions to desktop agent skills
        skill_map = {
            "fs.open": "open_path",
            "app.launch": "launch_app",
            "web.open": "open_url",
            "browser.ensure": "ensure_browser",
            "screen.capture": "take_screenshot",
            "window.control": "manage_window",
            "mouse.click": "mouse_click",
            "keyboard.type": "type_text",
            "keyboard.press": "press_key",
        }
        
        skill = skill_map.get(action, action)
        
        # Build arguments
        args = dict(parameters) if parameters else {}
        if target:
            # Determine the right argument name based on skill
            if skill == "open_path":
                args["path"] = target
            elif skill == "open_url":
                args["url"] = target
            elif skill == "launch_app":
                args["app"] = target
            elif skill == "ensure_browser":
                args["wait_time"] = 2.0
            else:
                args["target"] = target
        
        try:
            # Load API key
            api_key = await self._get_desktop_api_key()
            
            url = f"{self._desktop_url}/execute"
            payload = {
                "skill": skill,
                "args": args
            }
            
            headers = {"X-API-Key": api_key}
            
            async with self._http_session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Desktop agent error: {response.status} - {error_text}"
                    }
                    
        except asyncio.TimeoutError:
            return {"success": False, "error": "Desktop agent timeout"}
        except aiohttp.ClientConnectorError:
            return {"success": False, "error": "Cannot connect to desktop agent"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _get_desktop_api_key(self) -> str:
        """Get desktop agent API key."""
        if self._desktop_api_key:
            return self._desktop_api_key
        
        # Try to read from config file
        import os
        key_file = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "desktop-agent", "config", "api_key.txt"
        )
        
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                self._desktop_api_key = f.read().strip()
        
        return self._desktop_api_key or "default-key"
    
    async def _handle_disambiguation(
        self,
        message: str,
        intent_result: IntentResult,
        routing: RoutingDecision,
        stream_callback: Optional[Callable]
    ) -> Dict[str, Any]:
        """Handle ambiguous requests by asking for clarification."""
        # For now, proceed with best guess
        # TODO: Implement actual disambiguation UI
        
        logger.info(f"🤔 Disambiguation needed for: {message}")
        
        # Use Phase 6 router for disambiguation options
        decision = self.master_router.route(message, self.context_manager.get_context_for_resolution())
        
        if decision.disambiguation_options:
            options_text = "\n".join(
                f"• {opt['label']}" for opt in decision.disambiguation_options
            )
            response = f"I'm not quite sure what you want. Did you mean:\n{options_text}"
            
            if stream_callback:
                await stream_callback({
                    "type": "disambiguation",
                    "options": decision.disambiguation_options
                })
                await stream_callback({
                    "type": "stream_chunk",
                    "content": response
                })
                await stream_callback({
                    "type": "stream_end"
                })
            
            return {"response": response, "success": True, "needs_clarification": True}
        
        # No disambiguation options, try to proceed anyway
        return await self._handle_full_orchestration(
            message, "", "", intent_result, stream_callback
        )
    
    async def _handle_full_orchestration(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
        intent_result: IntentResult,
        stream_callback: Optional[Callable]
    ) -> Dict[str, Any]:
        """Delegate to full LangGraph orchestration."""
        if stream_callback:
            await stream_callback({
                "type": "thinking",
                "message": "🧠 Using advanced reasoning...",
                "routing_path": "full_orchestration"
            })
        
        # Import and use TaskExecutor
        try:
            from app.core.executor_factory import ExecutorFactory
            from app.core.task_executor import TaskRequest, TaskType
            
            # Map intent to task type
            task_type_map = {
                IntentType.CODING: TaskType.CODE_GENERATION,
                IntentType.DESKTOP_ACTION: TaskType.DESKTOP_AUTOMATION,
                IntentType.WEB_AUTONOMOUS: TaskType.WEB_AUTOMATION,
                IntentType.GENERAL: TaskType.GENERAL_QUERY,
            }
            
            task_type = task_type_map.get(intent_result.intent_type, TaskType.GENERAL_QUERY)
            
            executor = ExecutorFactory.get_executor()
            
            task_request = TaskRequest(
                task_type=task_type,
                user_id=user_id or "anonymous",
                conversation_id=conversation_id or f"conv_{time.time()}",
                message=message,
                max_iterations=3
            )
            
            # Execute
            result = await executor.execute(task_request, progress_callback=stream_callback)
            
            return {
                "response": result.output,
                "success": result.success,
                "code": result.code,
                "files": result.files,
            }
            
        except Exception as e:
            logger.error(f"❌ Orchestration error: {e}")
            return {
                "response": f"I encountered an error while processing your request: {str(e)}",
                "success": False,
                "error": str(e)
            }
    
    def _generate_success_response(self, action: str, target: Optional[str]) -> str:
        """Generate a success response for an action."""
        responses = {
            "fs.open": f"I've opened {target or 'the folder'} for you.",
            "app.launch": f"I've launched {target or 'the application'}.",
            "web.open": f"I've opened {target} in your browser.",
            "screen.capture": "I've taken a screenshot.",
            "window.control": f"I've {target or 'updated'} the window.",
            "mouse.click": "I've clicked at that position.",
            "keyboard.type": "I've typed the text.",
            "keyboard.press": f"I've pressed {target}.",
        }
        
        return responses.get(action, f"Done! Action '{action}' completed successfully.")
    
    def _update_context(self, updates: Dict[str, Any]) -> None:
        """Update predictive context from feedback."""
        self.context_manager.update(updates)
    
    def _handle_fallback(self, feedback) -> None:
        """Handle fallback when desktop action fails."""
        logger.info(f"🔄 Fallback triggered: {feedback.fallback_reason}")
    
    async def shutdown(self):
        """Cleanup resources."""
        if self._http_session:
            await self._http_session.close()


# Global instance
fast_path_handler = FastPathHandler()
