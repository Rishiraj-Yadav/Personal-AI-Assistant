import os, json, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from app.skills.desktop_bridge import desktop_bridge
async def main():
    try:
        params = json.loads(os.environ.get("SKILL_PARAMS", "{}"))
        action = params.get("action")
        title = params.get("title", "")
        if action == "list":
            result = await desktop_bridge.execute_skill("list_windows", {}, safe_mode=False)
        elif action == "focus":
            result = await desktop_bridge.execute_skill("focus_window", {"title": title}, safe_mode=False)
        elif action == "maximize":
            result = await desktop_bridge.execute_skill("maximize_window", {"title": title}, safe_mode=False)
        elif action == "minimize":
            result = await desktop_bridge.execute_skill("minimize_window", {"title": title}, safe_mode=False)
        else:
            result = {"success": False, "error": f"Unknown action: {action}"}
        print(json.dumps(result.get("result", result)))
    except Exception as e: print(json.dumps({"error": str(e)}))
if __name__ == "__main__": asyncio.run(main())