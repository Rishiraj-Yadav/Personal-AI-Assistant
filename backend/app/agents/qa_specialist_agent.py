"""
QA Specialist Agent
Generates automated tests for code produced by the Code Specialist, executes them in the sandbox,
and provides pass/fail feedback for self-correction loops.
"""
import os
import re
from typing import Dict, Any, Optional
from loguru import logger
import google.generativeai as genai

from ..services.sandbox_services import sandbox_service


class QASpecialistAgent:
    """
    QA Verification Agent - Generates and runs tests for generated code.
    Enforces quality contracts before a task is considered successful.
    """

    def __init__(self):
        """Initialize QA specialist with Gemini GenAI."""
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("⚠️ GOOGLE_API_KEY not set for QA Agent")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("✅ QA Specialist initialized")

    async def verify_code(
        self,
        files: Dict[str, str],
        project_type: str,
        original_request: str
    ) -> Dict[str, Any]:
        """
        Generate and execute a test suite for the provided files.
        """
        logger.info(f"🧪 QA Agent: Verifying {len(files)} files for project type: {project_type}...")

        # 1. Generate tests
        prompt = self._create_test_generation_prompt(files, project_type, original_request)
        
        try:
            response = await self.model.generate_content_async(prompt)
            output = response.text.strip()
            
            # Parse test files from output
            test_files, test_cmd = self._parse_test_output(output, project_type)
            
            if not test_files:
                return {
                    "tests_passed": False,
                    "feedback": "QA Agent failed to generate valid test files.",
                    "test_output": output
                }
                
            logger.info(f"📝 QA Agent generated {len(test_files)} test files. Test command: {test_cmd}")

            # 2. Add test files to the project files map
            combined_files = {**files, **test_files}
            
            # 3. Execute tests in sandbox
            logger.info("🏃 QA Agent: Executing tests in sandbox...")
            # For simplicity, if it's not a server, we run execute_project with the test command as the start command
            
            # Use specific install commands if needed for testing (e.g. pytest, jest)
            install_cmd = None
            if project_type == "python":
                install_cmd = "pip install pytest"
            elif project_type in ["node", "javascript", "react", "express"]:
                install_cmd = "npm install jest --save-dev"
                
            test_result = await sandbox_service.execute_project(
                files=combined_files,
                project_type=project_type,
                project_name="qa-verification",
                install_command=install_cmd,
                start_command=test_cmd,
                port=None  # We don't want to start a server, we just want to run tests and get the exit code
            )
            
            # 4. Analyze results
            tests_passed = test_result.get("exit_code") == 0 and test_result.get("success", False)
            stdout = test_result.get("stdout", "")
            stderr = test_result.get("stderr", "")
            
            feedback = "All tests passed successfully." if tests_passed else f"Tests failed.\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            
            if tests_passed:
                logger.info("✅ QA Agent: All tests passed!")
            else:
                logger.warning("❌ QA Agent: Tests failed.")
                
            return {
                "tests_passed": tests_passed,
                "feedback": feedback,
                "test_output": stdout + "\n" + stderr,
                "test_files": test_files
            }

        except Exception as e:
            logger.error(f"❌ QA Agent verification error: {str(e)}")
            return {
                "tests_passed": False,
                "feedback": f"Test generation/execution threw an exception: {str(e)}",
                "test_output": str(e)
            }

    def _create_test_generation_prompt(self, files: Dict[str, str], project_type: str, request: str) -> str:
        """Create prompt to generate tests."""
        file_list_str = "\n".join([f"--- {name} ---\n{content}\n" for name, content in files.items()])
        
        return f"""You are an expert QA Engineer. Your job is to verify that the following code fulfills the user's intent.

User Request: "{request}"
Project Type: {project_type}

Source Files:
{file_list_str}

CRITICAL INSTRUCTIONS:
1. Write an automated test suite for the provided code.
2. If it's a python project, use `unittest` or `pytest`. Output a file named `test_main.py`. The test command should be `pytest test_main.py`.
3. If it's a javascript/node project, use `jest` or standard `assert`. Output a file named `test.js`. The test command should be `node test.js` or `npx jest`.
4. Make sure your test explicitly tests the edge cases and core requirements.
5. Provide the TEST_COMMAND and the FILES in the exact format below.

OUTPUT FORMAT:
TEST_COMMAND: [command to run the tests]

FILES:
--- path/to/test_file.ext ---
[Complete test file content]
"""

    def _parse_test_output(self, output: str, project_type: str):
        """Parse the test command and test files from the LLM output."""
        files = {}
        test_cmd = "pytest" if project_type == "python" else "npm test"
        
        # Parse command
        cmd_match = re.search(r'TEST_COMMAND:\s*(.*?)\n', output)
        if cmd_match:
            test_cmd = cmd_match.group(1).strip()
            
        # Parse files
        files_match = re.search(r'FILES:(.*?)$', output, re.DOTALL | re.IGNORECASE)
        if files_match:
            files_section = files_match.group(1)
            file_pattern = r'---\s*([^\n]+?)\s*---\n(.*?)(?=---|\Z)'
            matches = re.findall(file_pattern, files_section, re.DOTALL)
            for filepath, content in matches:
                files[filepath.strip()] = content.strip()
                
        # If regex failed but it's a python block
        if not files:
            code_match = re.search(r'```(?:python|js|javascript)?\n(.*?)\n```', output, re.DOTALL)
            if code_match:
                filename = "test_main.py" if project_type == "python" else "test.js"
                files[filename] = code_match.group(1).strip()
                
        return files, test_cmd


# Global instance
qa_specialist = QASpecialistAgent()
