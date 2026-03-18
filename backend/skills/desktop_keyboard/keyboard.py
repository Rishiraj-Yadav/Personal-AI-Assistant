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
        action = params.get("action")
        if action == "type":
            result = await desktop_bridge.execute_skill("type_text", {"text": params.get("text", "")}, safe_mode=False)
        elif action == "press":
            result = await desktop_bridge.execute_skill("press_key", {"key": params.get("key", "")}, safe_mode=False)
        elif action == "hotkey":
            result = await desktop_bridge.execute_skill("press_hotkey", {"keys": params.get("keys", [])}, safe_mode=False)
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