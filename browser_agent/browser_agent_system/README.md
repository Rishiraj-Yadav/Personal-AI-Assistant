# Multi-Agent Browser System

A Python multi-agent system with a **Browser Agent** powered by Claude + Playwright,
and an **Orchestrator** that routes tasks to the right agent.

---

## Architecture

```
User Task
    ↓
OrchestratorAgent        ← Routes tasks using Claude (fast model)
    ↓
BrowserAgent             ← Controls a real Chromium browser (Claude + Playwright)
    ↓
browser_tools.py         ← navigate, click, type, get_text, screenshot, ...
```

---

## Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Install Playwright browsers
```bash
playwright install chromium
```

### 3. Set up environment
```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

---

## Usage

### Interactive mode
```bash
python main.py
```

### Single task
```bash
python main.py --task "Search Google for the latest Python news"
python main.py --task "Go to wikipedia.org and tell me what's on the homepage"
```

### Directly to browser agent (skip orchestrator)
```bash
python main.py --agent browser --task "Go to news.ycombinator.com and list the top 5 stories"
```

---

## Extending with New Agents

1. Create `agents/my_new_agent.py` with a class that has `async def run(task, context) -> str`
2. Register it in `agents/orchestrator.py`:
   ```python
   AGENT_REGISTRY["myagent"] = {
       "description": "What this agent does...",
       "examples": ["Example task 1", "Example task 2"]
   }
   ```
3. Instantiate it in `OrchestratorAgent.__init__`:
   ```python
   self.agents["myagent"] = MyNewAgent(verbose=verbose)
   ```

The orchestrator will automatically start routing relevant tasks to it.

---

## File Structure

```
browser_agent_system/
├── main.py                      ← Entry point (CLI + interactive REPL)
├── requirements.txt
├── .env.example
├── agents/
│   ├── browser_agent.py         ← BrowserAgent class
│   └── orchestrator.py          ← OrchestratorAgent (task router)
└── tools/
    ├── browser_tools.py         ← All Playwright browser functions
    └── tool_schemas.py          ← Tool definitions in Anthropic format
```

---

## Browser Tools Available

| Tool | Description |
|------|-------------|
| `navigate` | Go to a URL |
| `click` | Click element by selector or text |
| `type_text` | Type into input fields |
| `get_text` | Read text content from page |
| `get_page_info` | Get URL, title, inputs, buttons |
| `screenshot` | Take a screenshot |
| `scroll` | Scroll up/down |
| `wait_for_element` | Wait for dynamic content |
| `extract_links` | Get all page links |
| `execute_script` | Run JavaScript |
| `select_option` | Pick from dropdowns |
| `press_key` | Press Enter, Tab, Escape, etc. |
| `go_back` | Browser back button |
| `get_html` | Get raw HTML of element |
