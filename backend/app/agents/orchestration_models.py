"""
Shared planner/executor models for the unified backend orchestration flow.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ApprovalLevel = Literal["none", "confirm"]
SafetyLevel = Literal["safe", "confirm", "dangerous"]
AgentType = Literal[
    "coding",
    "desktop",
    "web",
    "web_autonomous",
    "email",
    "calendar",
    "general",
]


class TaskEnvelope(BaseModel):
    user_message: str
    user_id: str
    conversation_id: str
    channel: str = "unknown"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    required: bool = False
    approval_level: ApprovalLevel = "none"
    reason: str = ""
    affected_steps: List[str] = Field(default_factory=list)
    safety_level: SafetyLevel = "safe"


class VerificationRequirement(BaseModel):
    method: Literal["none", "process", "window", "file", "ocr", "screenshot", "browser", "composite"] = "none"
    target: str = ""
    expected: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class RecoveryPolicy(BaseModel):
    strategy: str = ""
    alternate_tools: List[str] = Field(default_factory=list)
    max_retries: int = 0
    notes: str = ""


class TaskAnalysis(BaseModel):
    task_type: AgentType
    confidence: float = 0.0
    reasoning: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    required_capabilities: List[str] = Field(default_factory=list)
    blocked: bool = False
    blocked_reason: str = ""
    approval: ApprovalRequest = Field(default_factory=ApprovalRequest)


class PlanStep(BaseModel):
    step_id: str
    agent_type: AgentType
    goal: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    approval_level: ApprovalLevel = "none"
    safety_level: SafetyLevel = "safe"
    tool_name: str = ""
    verification: VerificationRequirement = Field(default_factory=VerificationRequirement)
    recovery: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    retry_budget: int = 0
    success_criteria: str = ""
    fallback_strategy: str = ""
    status: Literal["pending", "running", "completed", "failed", "blocked"] = "pending"


class ExecutionPlan(BaseModel):
    plan_id: str
    task_type: AgentType
    summary: str
    steps: List[PlanStep] = Field(default_factory=list)
    requires_approval: bool = False
    approval_request: Optional[ApprovalRequest] = None
    workflow_key: Optional[str] = None
    workflow_name: Optional[str] = None
    workflow_source: str = "dynamic"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentHandoff(BaseModel):
    from_agent: AgentType
    to_agent: AgentType
    reason: str
    context: str = ""


class ExecutionTraceEvent(BaseModel):
    event_type: str
    phase: str
    message: str
    step_id: Optional[str] = None
    agent_type: Optional[AgentType] = None
    success: Optional[bool] = None
    data: Dict[str, Any] = Field(default_factory=dict)
