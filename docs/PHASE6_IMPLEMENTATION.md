# Phase 6: Production-Grade OpenClaw Architecture

## Overview

Phase 6 implements a production-grade desktop intelligence system with:
- Confidence-driven routing
- Formal task state machine
- Execution feedback loop
- Predictive context engine
- Real-time WebSocket communication

## Architecture

```
User → Frontend → WebSocket → Backend
                     ↓
              FastPathHandler
                     ↓
         FastIntentClassifier (patterns)
                     ↓
         FastRouter (confidence thresholds)
                     ↓
    ┌────────────────┼────────────────┐
    ↓                ↓                ↓
Fast Desktop    Disambiguate    Full Orchestration
(conf > 0.8)   (0.5-0.8)        (conf < 0.5)
    ↓                                 ↓
Desktop Agent ←──────────────→ LangGraph
    ↓
FeedbackLoop (verify → update context → log)
    ↓
Response → Frontend
```

## The 8 Pillars

### 1. Centralized Backend Routing
Every query goes to the backend's `MasterIntentRouter`. The frontend is a "dumb terminal."

### 2. Confidence Threshold System
- **Score > 0.8**: Fast path → Direct desktop execution
- **0.5 < Score < 0.8**: Disambiguation → Ask user for clarification
- **Score < 0.5**: Full orchestration → LangGraph multi-step flow

### 3. Action Validation & Safety
Pre-execution validation via `ActionValidator`:
- Risk levels: LOW, MEDIUM, HIGH, CRITICAL
- Destructive actions require confirmation

### 4. Predictive Context Engine
`PredictiveContextManager` tracks:
- `last_folder`, `last_file`, `last_app`
- `recent_paths`, `frequent_paths`
- `active_project`, `active_project_type`
- `current_task`

### 5. Task Continuity (State Machine)
`TaskStateMachine` manages task lifecycle:
```
PENDING → VALIDATING → ROUTING → EXECUTING → VERIFYING → COMPLETED
                                     ↓
                                   FAILED
```

Enables task chaining: "create file" → "edit it" → "run it"

### 6. Execution Feedback Loop
`FeedbackLoop` implements: Execute → Verify → Update Context → Log

Verification strategies per action type:
- `fs.open`: Check path exists
- `app.launch`: Check process running
- `web.open`: Check browser process
- `screen.capture`: Check screenshot file

### 7. Unified Action Protocol
Standard JSON payloads for all actions:
```json
{
  "action": "fs.open",
  "target": "/Projects/MyApp",
  "metadata": {"source": "fast_path", "requires_validation": true}
}
```

### 8. Fallback to Backend Intelligence
If desktop action fails, automatic fallback to LLM reasoning.

## New Files

### Backend (`backend/app/core/`)
| File | Purpose |
|------|---------|
| `master_router.py` | Confidence-based routing |
| `task_state_machine.py` | Task lifecycle management |
| `execution_feedback.py` | Action verification |
| `predictive_context.py` | Smart context tracking |

### Backend (`backend/app/realtime/`)
| File | Purpose |
|------|---------|
| `fast_intent_classifier.py` | Pattern-based classification |
| `fast_router.py` | Routing decisions |
| `simple_responder.py` | Conversational responses |
| `response_sanitizer.py` | Output cleanup |
| `fast_path_handler.py` | Main orchestration |

### Desktop Agent (`desktop-agent/app/`)
| File | Purpose |
|------|---------|
| `backend_client.py` | WebSocket client to backend |
| `agents/app_agent.py` | Added `open_path`, `launch_app` |

## Quick Start

### 1. Install Dependencies
```bash
# Backend
cd backend
pip install -r requirements.txt

# Desktop Agent
cd desktop-agent
pip install -r requirements.txt
```

### 2. Start Services
```bash
# Option A: Use the script
python scripts/start_phase6.py

# Option B: Manual
# Terminal 1 - Backend
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Desktop Agent
cd desktop-agent/app
python main.py
```

### 3. Test Commands
Try these in the frontend:
- "open my downloads folder"
- "launch notepad"
- "take a screenshot"
- "open youtube"
- "open my python project"

## Configuration

### Backend (.env)
```env
DESKTOP_AGENT_URL=http://localhost:7777
```

### Desktop Agent (.env.desktop)
```env
GOOGLE_API_KEY=your-key
HOST=127.0.0.1
PORT=7777
SAFE_MODE=false
```

### WebSocket Connection
Desktop agent automatically connects to:
```
ws://localhost:8000/ws/desktop
```

Override with environment variable:
```env
BACKEND_WS_URL=ws://localhost:8000/ws/desktop
```

## API Endpoints

### Backend WebSocket
```
ws://localhost:8000/ws/chat     # Frontend connection
ws://localhost:8000/ws/desktop  # Desktop agent connection
```

### Desktop Agent HTTP
```
POST /execute           # Direct skill execution
POST /execute-nl        # Natural language command
GET  /capabilities      # List available skills
GET  /node/describe     # Node info
GET  /node/tools        # Available tools
POST /node/execute      # Execute tool
```

## Testing

Run Phase 6 integration tests:
```bash
cd backend
pytest tests/test_phase6_integration.py -v
```

## Example Flow

User: "open python project"

1. **Frontend → Backend**: WebSocket message
2. **FastIntentClassifier**: Pattern match → `fs.open` (confidence: 0.92)
3. **FastRouter**: confidence > 0.8 → `FAST_DESKTOP` path
4. **TaskStateMachine**: Create task, transition through states
5. **Desktop Agent**: Execute `open_path` skill
6. **FeedbackLoop**: Verify folder opened, update `active_project`
7. **Response**: "I've opened your Python project folder."

## Troubleshooting

### Desktop Agent Not Connecting
1. Check backend is running on port 8000
2. Check `BACKEND_WS_URL` environment variable
3. Check firewall allows WebSocket connections

### Commands Not Executing
1. Check desktop agent logs: `desktop-agent/logs/desktop_agent.log`
2. Check skill is registered: `GET /capabilities`
3. Test direct execution: `POST /execute {"skill": "open_path", "args": {"path": "C:\\"}}`

### Low Confidence Routing
If commands go to full orchestration instead of fast path:
1. Check pattern matching in `fast_intent_classifier.py`
2. Add new patterns for common commands
3. Adjust thresholds in `FastRouter`
