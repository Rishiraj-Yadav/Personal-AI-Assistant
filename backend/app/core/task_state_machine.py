"""
Task State Machine - Phase 6 Pillar 5
======================================

Formal state machine for task continuity:
- Tracks task lifecycle: PENDING → RUNNING → COMPLETED/FAILED
- Maintains task_id binding across sequential operations
- Implements guards and error recovery paths
"""

import uuid
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable
from loguru import logger


class TaskState(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    VALIDATING = "validating"
    ROUTING = "routing"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_INPUT = "awaiting_input"  # Disambiguation or confirmation
    RETRYING = "retrying"


class TaskTransition(str, Enum):
    """Valid state transitions."""
    START = "start"
    VALIDATE = "validate"
    ROUTE = "route"
    EXECUTE = "execute"
    VERIFY = "verify"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"
    AWAIT_INPUT = "await_input"
    RETRY = "retry"
    RESUME = "resume"


@dataclass
class TaskContext:
    """Context maintained across task lifecycle."""
    task_id: str
    parent_task_id: Optional[str] = None  # For chained tasks
    user_message: str = ""
    session_id: str = ""
    conversation_id: str = ""
    
    # State tracking
    current_state: TaskState = TaskState.PENDING
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Routing info
    routing_decision: Optional[Dict[str, Any]] = None
    
    # Execution info
    action: Optional[str] = None
    target: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    execution_result: Optional[Dict[str, Any]] = None
    
    # Error tracking
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    # Timing
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # Context for task continuity
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "user_message": self.user_message,
            "session_id": self.session_id,
            "current_state": self.current_state.value,
            "state_history": self.state_history,
            "routing_decision": self.routing_decision,
            "action": self.action,
            "target": self.target,
            "parameters": self.parameters,
            "execution_result": self.execution_result,
            "error": self.error,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class TaskStateMachine:
    """
    Phase 6 Task State Machine
    
    Manages task lifecycle with formal state transitions, guards, and error recovery.
    Enables task continuity across sequential operations (create → edit → run).
    """
    
    # Valid state transitions
    TRANSITIONS: Dict[TaskState, Dict[TaskTransition, TaskState]] = {
        TaskState.PENDING: {
            TaskTransition.START: TaskState.VALIDATING,
            TaskTransition.CANCEL: TaskState.CANCELLED,
        },
        TaskState.VALIDATING: {
            TaskTransition.VALIDATE: TaskState.ROUTING,
            TaskTransition.FAIL: TaskState.FAILED,
            TaskTransition.CANCEL: TaskState.CANCELLED,
        },
        TaskState.ROUTING: {
            TaskTransition.ROUTE: TaskState.EXECUTING,
            TaskTransition.AWAIT_INPUT: TaskState.AWAITING_INPUT,
            TaskTransition.FAIL: TaskState.FAILED,
            TaskTransition.CANCEL: TaskState.CANCELLED,
        },
        TaskState.EXECUTING: {
            TaskTransition.EXECUTE: TaskState.VERIFYING,
            TaskTransition.FAIL: TaskState.FAILED,
            TaskTransition.CANCEL: TaskState.CANCELLED,
        },
        TaskState.VERIFYING: {
            TaskTransition.VERIFY: TaskState.COMPLETED,
            TaskTransition.FAIL: TaskState.FAILED,
            TaskTransition.RETRY: TaskState.RETRYING,
        },
        TaskState.AWAITING_INPUT: {
            TaskTransition.RESUME: TaskState.ROUTING,
            TaskTransition.CANCEL: TaskState.CANCELLED,
        },
        TaskState.RETRYING: {
            TaskTransition.RETRY: TaskState.EXECUTING,
            TaskTransition.FAIL: TaskState.FAILED,
        },
        # Terminal states - no transitions out
        TaskState.COMPLETED: {},
        TaskState.FAILED: {},
        TaskState.CANCELLED: {},
    }
    
    def __init__(self):
        """Initialize the Task State Machine."""
        self._tasks: Dict[str, TaskContext] = {}
        self._active_chain: Optional[str] = None  # Current task chain ID
        self._guards: Dict[TaskTransition, List[Callable]] = {}
        self._hooks: Dict[str, List[Callable]] = {
            "on_enter": [],
            "on_exit": [],
            "on_transition": [],
            "on_complete": [],
            "on_fail": [],
        }
        logger.info("✅ TaskStateMachine initialized")
    
    def create_task(
        self,
        user_message: str,
        session_id: str = "",
        conversation_id: str = "",
        parent_task_id: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None
    ) -> TaskContext:
        """
        Create a new task and register it in the state machine.
        
        Args:
            user_message: The user's request
            session_id: Session identifier
            conversation_id: Conversation identifier  
            parent_task_id: Parent task for chained operations
            context_snapshot: Snapshot of current context for continuity
            
        Returns:
            TaskContext for the new task
        """
        task_id = str(uuid.uuid4())[:8]
        
        task = TaskContext(
            task_id=task_id,
            parent_task_id=parent_task_id,
            user_message=user_message,
            session_id=session_id,
            conversation_id=conversation_id,
            context_snapshot=context_snapshot or {}
        )
        
        self._tasks[task_id] = task
        
        # If this is a chained task, link it
        if parent_task_id:
            logger.info(f"🔗 Task {task_id} chained to {parent_task_id}")
        
        logger.debug(f"📝 Created task {task_id}: {user_message[:50]}...")
        return task
    
    def transition(
        self,
        task_id: str,
        transition: TaskTransition,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Attempt a state transition for a task.
        
        Args:
            task_id: The task to transition
            transition: The transition to attempt
            data: Optional data to attach to the transition
            
        Returns:
            True if transition succeeded, False otherwise
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.error(f"❌ Task {task_id} not found")
            return False
        
        current_state = task.current_state
        valid_transitions = self.TRANSITIONS.get(current_state, {})
        
        if transition not in valid_transitions:
            logger.warning(
                f"⚠️ Invalid transition: {current_state.value} → {transition.value}"
            )
            return False
        
        # Run guards
        if not self._run_guards(transition, task, data):
            logger.warning(f"⚠️ Guard blocked transition: {transition.value}")
            return False
        
        # Execute transition
        next_state = valid_transitions[transition]
        old_state = task.current_state
        
        # Run exit hooks
        self._run_hooks("on_exit", task, old_state)
        
        # Update state
        task.current_state = next_state
        task.state_history.append({
            "from": old_state.value,
            "to": next_state.value,
            "transition": transition.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data
        })
        
        # Update timing
        if next_state == TaskState.EXECUTING and not task.started_at:
            task.started_at = datetime.now(timezone.utc).isoformat()
        elif next_state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED]:
            task.completed_at = datetime.now(timezone.utc).isoformat()
        
        # Attach data
        if data:
            if "routing_decision" in data:
                task.routing_decision = data["routing_decision"]
            if "action" in data:
                task.action = data["action"]
            if "target" in data:
                task.target = data["target"]
            if "parameters" in data:
                task.parameters = data["parameters"]
            if "execution_result" in data:
                task.execution_result = data["execution_result"]
            if "error" in data:
                task.error = data["error"]
        
        # Run enter hooks
        self._run_hooks("on_enter", task, next_state)
        self._run_hooks("on_transition", task, transition)
        
        # Run completion/failure hooks
        if next_state == TaskState.COMPLETED:
            self._run_hooks("on_complete", task, data)
        elif next_state == TaskState.FAILED:
            self._run_hooks("on_fail", task, data)
        
        logger.info(f"✅ Task {task_id}: {old_state.value} → {next_state.value}")
        return True
    
    def get_task(self, task_id: str) -> Optional[TaskContext]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def get_task_chain(self, task_id: str) -> List[TaskContext]:
        """
        Get all tasks in a chain (parent and children).
        Enables task continuity for sequential operations.
        """
        chain = []
        task = self._tasks.get(task_id)
        
        if not task:
            return chain
        
        # Walk up to root
        root_id = task_id
        while task and task.parent_task_id:
            root_id = task.parent_task_id
            task = self._tasks.get(root_id)
        
        # Walk down collecting children
        def collect_chain(tid: str):
            t = self._tasks.get(tid)
            if t:
                chain.append(t)
                # Find children
                for other_id, other_task in self._tasks.items():
                    if other_task.parent_task_id == tid:
                        collect_chain(other_id)
        
        collect_chain(root_id)
        return chain
    
    def can_retry(self, task_id: str) -> bool:
        """Check if a task can be retried."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        return (
            task.current_state in [TaskState.FAILED, TaskState.VERIFYING] and
            task.retry_count < task.max_retries
        )
    
    def retry_task(self, task_id: str) -> bool:
        """
        Retry a failed task.
        
        Returns:
            True if retry was initiated, False otherwise
        """
        task = self._tasks.get(task_id)
        if not task or not self.can_retry(task_id):
            return False
        
        task.retry_count += 1
        task.error = None
        
        return self.transition(task_id, TaskTransition.RETRY, {
            "retry_count": task.retry_count
        })
    
    def add_guard(self, transition: TaskTransition, guard: Callable[[TaskContext, Any], bool]):
        """
        Add a guard function for a transition.
        Guard returns True to allow, False to block.
        """
        if transition not in self._guards:
            self._guards[transition] = []
        self._guards[transition].append(guard)
    
    def add_hook(self, event: str, hook: Callable):
        """Add a lifecycle hook."""
        if event in self._hooks:
            self._hooks[event].append(hook)
    
    def _run_guards(
        self,
        transition: TaskTransition,
        task: TaskContext,
        data: Any
    ) -> bool:
        """Run all guards for a transition."""
        guards = self._guards.get(transition, [])
        for guard in guards:
            try:
                if not guard(task, data):
                    return False
            except Exception as e:
                logger.error(f"❌ Guard error: {e}")
                return False
        return True
    
    def _run_hooks(self, event: str, task: TaskContext, data: Any):
        """Run all hooks for an event."""
        hooks = self._hooks.get(event, [])
        for hook in hooks:
            try:
                hook(task, data)
            except Exception as e:
                logger.error(f"❌ Hook error ({event}): {e}")
    
    def cleanup_completed(self, max_age_seconds: int = 3600):
        """Remove completed tasks older than max_age."""
        now = datetime.now(timezone.utc)
        to_remove = []
        
        for task_id, task in self._tasks.items():
            if task.current_state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED]:
                if task.completed_at:
                    completed = datetime.fromisoformat(task.completed_at.replace('Z', '+00:00'))
                    age = (now - completed).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        if to_remove:
            logger.info(f"🧹 Cleaned up {len(to_remove)} old tasks")


# Global instance
_task_state_machine: Optional[TaskStateMachine] = None


def get_task_state_machine() -> TaskStateMachine:
    """Get or create the global TaskStateMachine instance."""
    global _task_state_machine
    if _task_state_machine is None:
        _task_state_machine = TaskStateMachine()
    return _task_state_machine
