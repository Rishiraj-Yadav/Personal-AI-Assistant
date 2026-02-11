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
        
        app = params.get("app", "")
        
        # Map common names
        app_mapping = {
            "task manager": "taskmgr",
            "taskmanager": "taskmgr",
            "taskmgr": "taskmgr"
        }
        
        app_lower = app.lower()
        app_to_launch = app_mapping.get(app_lower, app)
        
        result = await desktop_bridge.execute_skill("app_launcher", {
            "app": app_to_launch
        }, safe_mode=False)
        
        if result.get("success"):
            desktop_result = result.get("result", {})
            output = {
                "success": True,
                "app": app,
                "launched": desktop_result.get("success", False),
                "message": f"Attempted to launch {app}"
            }
        else:
            output = {"error": result.get("error", "Failed to launch app")}
        
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())