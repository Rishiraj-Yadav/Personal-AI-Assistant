import os, json, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from app.skills.desktop_bridge import desktop_bridge
async def main():
    try:
        params = json.loads(os.environ.get("SKILL_PARAMS", "{}"))
        result = await desktop_bridge.execute_skill("window_manager", params, safe_mode=False)
        print(json.dumps(result.get("result", result)))
    except Exception as e: print(json.dumps({"error": str(e)}))
if __name__ == "__main__": asyncio.run(main())