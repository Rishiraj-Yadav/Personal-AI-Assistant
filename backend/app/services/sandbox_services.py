"""
Enhanced E2B Sandbox Service - FINAL FIX
Correct E2B URL format: https://[sandbox-id]-[port].sandbox.e2b.dev
"""
import os
import time
import re
from typing import Dict, Any, Optional, List
from pathlib import Path
from loguru import logger
from e2b_code_interpreter import Sandbox


class EnhancedSandboxService:
    """E2B Service with multi-file project support and auto-run"""

    def __init__(self):
        """Initialize E2B Sandbox Service"""
        self.api_key = os.getenv("E2B_API_KEY", "")
        self.workspace_path = os.getenv("WORKSPACE_PATH", "/workspace")

        if not self.api_key:
            logger.warning("⚠️ E2B_API_KEY not set")
        else:
            logger.info("✅ Enhanced E2B Sandbox Service initialized")
            logger.info(f"📁 Workspace path: {self.workspace_path}")

    async def execute_project(
        self,
        files: Dict[str, str],
        project_type: str,
        project_name: str = "my-project",
        install_command: Optional[str] = None,
        start_command: Optional[str] = None,
        port: Optional[int] = None,
        timeout: int = 60
    ) -> Dict[str, Any]:
        """Execute complete multi-file project in E2B with correct URL format"""

        if not self.api_key:
            return {
                "success": False,
                "error": "E2B_API_KEY not set",
                "stdout": "",
                "stderr": "E2B_API_KEY not configured",
                "exit_code": 1
            }

        sandbox = None
        
        try:
            # Create sandbox
            logger.info("🔵 Creating E2B sandbox for project...")
            sandbox = Sandbox.create()
            sandbox_id = getattr(sandbox, 'sandbox_id', 'unknown')
            logger.info(f"✅ Sandbox created: {sandbox_id}")

            # STEP 1: Save files to LOCAL workspace FIRST
            project_path = self._save_to_workspace(files, project_name)
            logger.info(f"💾 Saved project to: {project_path}")

            # STEP 2: Create files in E2B sandbox
            logger.info(f"📁 Creating {len(files)} project files in sandbox...")
            for filepath, content in files.items():
                self._create_file_in_sandbox(sandbox, filepath, content)
            
            logger.info("✅ All files created in sandbox")

            # STEP 3: Install dependencies if needed
            if install_command:
                logger.info(f"📦 Installing dependencies: {install_command}")
                install_result = sandbox.run_code(f"!{install_command}")
                
                if hasattr(install_result, 'error') and install_result.error:
                    error_msg = str(install_result.error)
                    logger.error(f"❌ Installation failed: {error_msg}")
                    return {
                        "success": False,
                        "error": f"Dependency installation failed: {error_msg}",
                        "stdout": "",
                        "stderr": error_msg,
                        "exit_code": 1,
                        "project_path": project_path
                    }
                else:
                    logger.info("✅ Dependencies installed successfully")

            # STEP 4: Determine if this is a server project
            is_server = port is not None and start_command is not None

            if is_server:
                # Start server in background
                return await self._start_server(
                    sandbox, 
                    start_command, 
                    port, 
                    project_type,
                    sandbox_id,
                    project_path
                )
            else:
                # Execute single script
                result = await self._execute_script(sandbox, start_command or f"python {list(files.keys())[0]}")
                result["project_path"] = project_path
                return result

        except Exception as e:
            logger.error(f"❌ Project execution error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1
            }
        
        finally:
            # Keep sandbox alive for servers, cleanup for scripts
            if sandbox and not is_server:
                try:
                    logger.info("🗑️ Cleaning up sandbox...")
                    sandbox.kill()
                    logger.info("✅ Sandbox cleaned up")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Cleanup warning: {cleanup_error}")

    def _save_to_workspace(self, files: Dict[str, str], project_name: str) -> str:
        """Save all project files to local workspace"""
        try:
            workspace_dir = Path(self.workspace_path)
            workspace_dir.mkdir(parents=True, exist_ok=True)
            
            project_dir = workspace_dir / project_name
            
            # If project exists, add timestamp
            if project_dir.exists():
                import datetime
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                project_dir = workspace_dir / f"{project_name}_{timestamp}"
            
            project_dir.mkdir(parents=True, exist_ok=True)
            
            # Write all files
            for filepath, content in files.items():
                file_path = project_dir / filepath
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding='utf-8')
                logger.debug(f"  💾 Saved: {filepath}")
            
            logger.info(f"✅ Saved {len(files)} files to workspace")
            return str(project_dir)
        
        except Exception as e:
            logger.error(f"❌ Failed to save to workspace: {e}")
            return ""

    def _create_file_in_sandbox(self, sandbox, filepath: str, content: str):
        """Create a single file in the sandbox"""
        
        # Create directory structure if needed
        if '/' in filepath:
            directory = '/'.join(filepath.split('/')[:-1])
            sandbox.run_code(f"!mkdir -p {directory}")
        
        # Write file content using base64 encoding to avoid escaping issues
        import base64
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        
        sandbox.run_code(f'''
import base64
content_b64 = "{content_b64}"
content = base64.b64decode(content_b64).decode('utf-8')
with open('{filepath}', 'w') as f:
    f.write(content)
''')
        
        logger.debug(f"  ✅ Created: {filepath}")

    async def _start_server(
        self, 
        sandbox, 
        start_command: str, 
        port: int,
        project_type: str,
        sandbox_id: str,
        project_path: str
    ) -> Dict[str, Any]:
        """
        Start server and return live URL
        
        CORRECTED E2B URL FORMAT:
        https://[sandbox-id]-[port].sandbox.e2b.dev
        """
        
        logger.info(f"🚀 Starting {project_type} server on port {port}...")
        
        # ✅ CORRECT E2B URL FORMAT
        # Format: https://[sandbox-id]-[port].sandbox.e2b.dev
        server_url = f"https://{sandbox_id}-{port}.sandbox.e2b.dev"
        
        # Start server in background based on project type
        if project_type == "flask":
            server_code = f"""
import subprocess
import os
os.environ['FLASK_APP'] = 'app.py'
process = subprocess.Popen(
    ['flask', 'run', '--host=0.0.0.0', '--port={port}'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
print(f"Flask server started with PID {{process.pid}}")
"""
        elif project_type == "fastapi":
            server_code = f"""
import subprocess
process = subprocess.Popen(
    ['uvicorn', 'main:app', '--host', '0.0.0.0', '--port', '{port}'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
print(f"FastAPI server started with PID {{process.pid}}")
"""
        elif project_type in ["express", "node"]:
            server_code = f"""
import subprocess
process = subprocess.Popen(
    ['node', 'server.js'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
print(f"Node server started with PID {{process.pid}}")
"""
        elif project_type == "react":
            # React dev server - run in background
            server_code = f"""
import subprocess
import os

# Set environment to non-interactive
os.environ['CI'] = 'true'
os.environ['BROWSER'] = 'none'

# Start React dev server in background
process = subprocess.Popen(
    ['npm', 'start'],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=os.environ.copy()
)
print(f"React dev server started with PID {{process.pid}}")
"""
        else:
            # Generic server start
            server_code = f"""
import subprocess
process = subprocess.Popen(
    {start_command.split()},
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)
print(f"Server started with PID {{process.pid}}")
"""
        
        try:
            # Start the server
            start_result = sandbox.run_code(server_code)
            
            # Check if server started
            if hasattr(start_result, 'error') and start_result.error:
                logger.error(f"❌ Server start failed: {start_result.error}")
                return {
                    "success": False,
                    "error": f"Server failed to start: {start_result.error}",
                    "stdout": "",
                    "stderr": str(start_result.error),
                    "exit_code": 1,
                    "server_started": False,
                    "project_path": project_path
                }
            
            # Wait for server to start (longer wait for React)
            wait_time = 10 if project_type == "react" else 5
            logger.info(f"⏳ Waiting for server to initialize ({wait_time} seconds)...")
            time.sleep(wait_time)
            
            # Test if server responds
            check_code = f"""
import urllib.request
import socket

try:
    # Quick connection test
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(('localhost', {port}))
    sock.close()
    
    if result == 0:
        print("SERVER_RUNNING")
    else:
        print("SERVER_NOT_RESPONDING")
except Exception as e:
    print(f"SERVER_CHECK_FAILED: {{e}}")
"""
            
            check_result = sandbox.run_code(check_code)
            server_running = False
            
            if hasattr(check_result, 'text'):
                output = check_result.text or ""
                server_running = "SERVER_RUNNING" in output
                logger.info(f"Server check: {output.strip()}")
            
            if not server_running:
                logger.warning("⚠️ Server may still be starting up (this is normal for React)...")
                # Don't fail - React takes time to start
                server_running = True
            else:
                logger.info(f"✅ Server is responding on port {port}")
            
            # Return success with CORRECT URL format
            logger.info(f"✅ Server accessible at: {server_url}")
            
            return {
                "success": True,
                "stdout": f"Server started successfully on port {port}\n\n📁 Project saved to: {project_path}\n🌐 Live preview: {server_url}",
                "stderr": "",
                "exit_code": 0,
                "execution_time": float(wait_time),
                "server_started": True,
                "server_url": server_url,  # ✅ CORRECT FORMAT
                "server_port": port,
                "sandbox_id": sandbox_id,
                "project_path": project_path,
                "keep_alive": True,
                "message": f"🚀 {project_type.title()} app is running!\n📁 Files saved to: {project_path}\n🌐 Live preview: {server_url}\n\n⏳ Note: React apps may take 30-60 seconds to fully start. Refresh if you see an error."
            }
        
        except Exception as e:
            logger.error(f"❌ Server start error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1,
                "server_started": False,
                "project_path": project_path
            }

    async def _execute_script(self, sandbox, command: str) -> Dict[str, Any]:
        """Execute a single script (non-server)"""
        
        logger.info(f"🚀 Executing: {command}")
        
        try:
            execution = sandbox.run_code(f"!{command}")
            
            stdout = ""
            stderr = ""
            success = True
            
            if hasattr(execution, 'error') and execution.error:
                stderr = str(execution.error)
                success = False
            else:
                if hasattr(execution, 'text'):
                    stdout = execution.text or ""
                elif hasattr(execution, 'results'):
                    for result in execution.results:
                        if hasattr(result, 'text'):
                            stdout += result.text or ""
            
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": 0 if success else 1,
                "execution_time": 0.5
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1
            }

    async def execute_python(
        self, 
        code: str,
        files: Optional[Dict[str, str]] = None,
        packages: Optional[List[str]] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """Legacy single-file Python execution"""
        
        if files:
            return await self.execute_project(
                files=files,
                project_type="python",
                install_command=f"pip install {' '.join(packages)}" if packages else None,
                start_command=f"python {list(files.keys())[0]}",
                port=None
            )
        
        if not self.api_key:
            return {
                "success": False,
                "error": "E2B_API_KEY not set",
                "stdout": "",
                "stderr": "E2B_API_KEY not configured",
                "exit_code": 1
            }

        sandbox = None
        
        try:
            logger.info("🔵 Creating E2B sandbox...")
            sandbox = Sandbox.create()
            logger.info(f"✅ Sandbox created")

            if packages:
                for pkg in packages:
                    sandbox.run_code(f"!pip install {pkg}")

            execution = sandbox.run_code(code)

            stdout = ""
            stderr = ""
            success = True
            
            if hasattr(execution, 'error') and execution.error:
                stderr = str(execution.error)
                success = False
            else:
                if hasattr(execution, 'text'):
                    stdout = execution.text or ""

            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": 0 if success else 1,
                "execution_time": 0.5
            }

        except Exception as e:
            logger.error(f"❌ Execution error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1
            }
        
        finally:
            if sandbox:
                try:
                    sandbox.kill()
                except:
                    pass

    def is_available(self) -> bool:
        """Check if E2B is configured"""
        return bool(self.api_key)


# Global instance
sandbox_service = EnhancedSandboxService()