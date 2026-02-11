#!/usr/bin/env python3
"""
Desktop Screenshot Skill - Wrapper
Calls the Desktop Agent to capture a screenshot
"""
import os
import json
import sys
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app.skills.desktop_bridge import desktop_bridge


async def main():
    """Main entry point"""
    try:
        # Get parameters
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        # Build arguments for desktop agent
        args = {
            "monitor": params.get("monitor", 1),
            "format": "base64"
        }
        
        # Add region if specified
        region_x = params.get("region_x")
        region_y = params.get("region_y")
        region_width = params.get("region_width")
        region_height = params.get("region_height")
        
        if all(v is not None for v in [region_x, region_y, region_width, region_height]):
            args["region"] = {
                "x": region_x,
                "y": region_y,
                "width": region_width,
                "height": region_height
            }
        
        # Execute via desktop bridge
        result = await desktop_bridge.execute_skill("screenshot", args)
        
        if result.get("success"):
            # Extract the actual result from desktop agent response
            desktop_result = result.get("result", {})
            output = {
                "image_base64": desktop_result.get("image_base64"),
                "width": desktop_result.get("width"),
                "height": desktop_result.get("height"),
                "format": desktop_result.get("format", "PNG"),
                "message": "Screenshot captured successfully"
            }
        else:
            output = {
                "error": result.get("error", "Unknown error")
            }
        
        print(json.dumps(output, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())