#!/usr/bin/env python3
import os
import json
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from app.skills.desktop_bridge import desktop_bridge

async def main():
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        action = params.get("action", "click")
        if action == "move":
            result = await desktop_bridge.execute_skill("mouse_move", {"x": params.get("x", 0), "y": params.get("y", 0)}, safe_mode=False)
        elif action in ["click", "double_click", "right_click"]:
            button = params.get("button", "left")
            if action == "right_click": button = "right"
            clicks = 2 if action == "double_click" else params.get("clicks", 1)
            result = await desktop_bridge.execute_skill("mouse_click", {"button": button, "clicks": clicks}, safe_mode=False)
        elif action == "scroll":
            result = await desktop_bridge.execute_skill("mouse_scroll", {"direction": params.get("direction", "down"), "amount": params.get("amount", 3)}, safe_mode=False)
        else:
            result = {"success": False, "error": f"Unknown action: {action}"}
        if result.get("success"):
            output = result.get("result", {})
        else:
            output = {"error": result.get("error")}
        
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())