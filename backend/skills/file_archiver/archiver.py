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
        
        result = await desktop_bridge.execute_skill("file_archiver", params, safe_mode=False)
        
        if result.get("success"):
            output = result.get("result", result)
        else:
            output = {"error": result.get("error", "Unknown error")}
        
        print(json.dumps(output, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())