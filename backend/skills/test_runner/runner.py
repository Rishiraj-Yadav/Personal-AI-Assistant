"""
Test Runner Skill
Executes tests in secure sandbox environment
"""
import os
import json
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from app.services.sandbox_service import sandbox_service


async def main():
    """Run tests in sandbox"""
    try:
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        test_code = params.get("test_code", "")
        source_code = params.get("source_code", "")
        framework = params.get("framework", "pytest")
        packages = params.get("packages", [])
        
        if not test_code:
            print(json.dumps({
                "success": False,
                "error": "No test code provided"
            }))
            sys.exit(1)
        
        # Prepare files for sandbox
        files = {}
        if source_code:
            files["source.py"] = source_code
        files["test_file.py"] = test_code
        
        # Add framework to packages if not present
        if framework == "pytest" and "pytest" not in packages:
            packages.append("pytest")
        elif framework == "unittest":
            pass  # unittest is built-in
        
        # Build test execution command
        if framework == "pytest":
            test_command = "pytest test_file.py -v"
        else:
            test_command = "python -m unittest test_file.py"
        
        # Execute tests in sandbox
        result = await sandbox_service.execute_python(
            code=test_command,
            files=files,
            packages=packages,
            timeout=60
        )
        
        if result.get("success"):
            # Parse test results
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            exit_code = result.get("exit_code", 0)
            
            # Determine if tests passed
            tests_passed = exit_code == 0
            
            output = {
                "success": True,
                "tests_passed": tests_passed,
                "framework": framework,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "execution_time": result.get("execution_time", 0)
            }
        else:
            output = {
                "success": False,
                "error": result.get("error", "Test execution failed")
            }
        
        print(json.dumps(output, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())