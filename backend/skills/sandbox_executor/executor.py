#!/usr/bin/env python3
"""
Sandbox Executor Skill
Safely executes code in E2B cloud sandbox
Works independently or after code_generator
"""
import os
import json
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app.services.sandbox_service import sandbox_service


async def main():
    """Execute code in secure E2B sandbox"""
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        code = params.get("code", "")
        language = params.get("language", "python").lower()
        packages = params.get("packages", [])
        files = params.get("files", {})
        timeout = params.get("timeout", 30)
        
        if not code:
            print(json.dumps({
                "success": False,
                "error": "No code provided to execute"
            }))
            sys.exit(1)
        
        # Check if E2B is available
        if not sandbox_service.is_available():
            print(json.dumps({
                "success": False,
                "error": "E2B sandbox not configured. Please set E2B_API_KEY in .env file.",
                "help": "Get free API key at https://e2b.dev"
            }))
            sys.exit(1)
        
        # Execute based on language
        if language in ["python", "py"]:
            result = await sandbox_service.execute_python(
                code=code,
                files=files,
                packages=packages,
                timeout=timeout
            )
        
        elif language in ["javascript", "js", "node", "nodejs"]:
            result = await sandbox_service.execute_javascript(
                code=code,
                files=files,
                packages=packages,
                timeout=timeout
            )
        
        else:
            print(json.dumps({
                "success": False,
                "error": f"Unsupported language: {language}. Supported: python, javascript"
            }))
            sys.exit(1)
        
        # Add metadata
        if result.get("success"):
            result["language"] = language
            result["packages_installed"] = packages
            result["code_executed"] = code
            result["message"] = "Code executed successfully in E2B sandbox"
        
        print(json.dumps(result, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())