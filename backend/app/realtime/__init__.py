"""
Real-time communication module for instant responses and streaming.

Phase 1: Message types and streaming infrastructure
Phase 2: Session management, request lifecycle, context tracking, assistant runtime
Phase 3: Fast path routing, intent classification, simple responder
Phase 6: Production-grade orchestration with confidence thresholds
"""

# Phase 2: Session Management
from .session_manager import (
    SessionManager,
    SessionState,
    SessionMessage,
    ActiveTask,
    session_manager,
)

# Phase 2: Request Lifecycle
from .request_lifecycle import (
    RequestLifecycleController,
    RequestStatus,
    ActiveRequest,
    CancellableStream,
    request_lifecycle,
)

# Phase 2: Active Context Tracking
from .active_context import (
    ActiveContextTracker,
    UserActiveContext,
    FileContext,
    AppContext,
    ActionContext,
    active_context_tracker,
)

# Phase 3: Fast Path Routing
from .fast_intent_classifier import (
    FastIntentClassifier,
    IntentType,
    IntentResult,
    fast_intent_classifier,
)

from .fast_router import (
    FastRouter,
    RoutingPath,
    RoutingDecision,
    fast_router,
)

from .simple_responder import (
    SimpleResponder,
    SimpleResponse,
    simple_responder,
)

from .response_sanitizer import (
    ResponseSanitizer,
    response_sanitizer,
)

from .fast_path_handler import (
    FastPathHandler,
    FastPathResult,
    fast_path_handler,
)

__all__ = [
    # Phase 2: Session Management
    "SessionManager",
    "SessionState",
    "SessionMessage",
    "ActiveTask",
    "session_manager",

    # Phase 2: Request Lifecycle
    "RequestLifecycleController",
    "RequestStatus",
    "ActiveRequest",
    "CancellableStream",
    "request_lifecycle",

    # Phase 2: Active Context Tracking
    "ActiveContextTracker",
    "UserActiveContext",
    "FileContext",
    "AppContext",
    "ActionContext",
    "active_context_tracker",

    # Phase 3: Fast Path Routing
    "FastIntentClassifier",
    "IntentType",
    "IntentResult",
    "fast_intent_classifier",
    "FastRouter",
    "RoutingPath",
    "RoutingDecision",
    "fast_router",
    "SimpleResponder",
    "SimpleResponse",
    "simple_responder",
    "ResponseSanitizer",
    "response_sanitizer",
    "FastPathHandler",
    "FastPathResult",
    "fast_path_handler",
]
