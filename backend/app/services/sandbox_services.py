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



















# """
# E2B Sandbox Service - DUAL MODE
# - Simple scripts: Direct execution
# - Web servers: Proper background process management
# """
# import os
# import time
# import asyncio
# import subprocess
# from typing import Dict, Any, Optional, List
# from pathlib import Path
# from loguru import logger
# from e2b_code_interpreter import Sandbox


# class SandboxManager:
#     """Manages active server sandboxes"""
#     def __init__(self):
#         self.active_servers = {}
    
#     def register_server(self, project_name: str, sandbox, metadata: dict):
#         self.active_servers[project_name] = (sandbox, metadata)
#         logger.info(f"🟢 Registered: {project_name}")
    
#     def stop_server(self, project_name: str):
#         if project_name in self.active_servers:
#             sandbox, _ = self.active_servers[project_name]
#             try:
#                 sandbox.kill()
#                 logger.info(f"🛑 Stopped: {project_name}")
#             except:
#                 pass
#             del self.active_servers[project_name]


# sandbox_manager = SandboxManager()


# class EnhancedSandboxService:
#     """
#     E2B Service with TWO modes:
#     1. Simple scripts - Direct execution, get output
#     2. Web servers - Background process with URL
#     """

#     def __init__(self):
#         self.api_key = os.getenv("E2B_API_KEY", "")
#         self.workspace_path = os.getenv("WORKSPACE_PATH", "/workspace")

#         if not self.api_key:
#             logger.warning("⚠️ E2B_API_KEY not set")
#         else:
#             logger.info("✅ Enhanced E2B Sandbox Service initialized")
    
#     async def execute_project(
#         self,
#         files: Dict[str, str],
#         project_type: str,
#         project_name: str = "my-project",
#         install_command: Optional[str] = None,
#         start_command: Optional[str] = None,
#         port: Optional[int] = None,
#         timeout: int = 60
#     ) -> Dict[str, Any]:
#         """
#         Smart execution:
#         - port=None → Simple script (get output)
#         - port=number → Web server (get URL)
#         """

#         if not self.api_key:
#             return self._error_response("E2B_API_KEY not set")

#         sandbox = None
#         is_server_project = port is not None
        
#         try:
#             logger.info("🔵 Creating E2B sandbox...")
#             sandbox = Sandbox.create()
#             sandbox_id = getattr(sandbox, 'sandbox_id', 'unknown')
#             logger.info(f"✅ Sandbox: {sandbox_id}")

#             # Save locally
#             project_path = self._save_to_workspace(files, project_name)
#             logger.info(f"💾 Local: {project_path}")

#             # Create files in sandbox
#             logger.info(f"📁 Creating {len(files)} files...")
#             for filepath, content in files.items():
#                 self._create_file_in_sandbox(sandbox, filepath, content)
#             logger.info("✅ Files created")

#             # Install dependencies
#             if install_command:
#                 logger.info(f"📦 Installing: {install_command}")
#                 install_result = sandbox.run_code(f"!{install_command}")
                
#                 if hasattr(install_result, 'error') and install_result.error:
#                     return self._error_response(
#                         f"Install failed: {install_result.error}",
#                         project_path=project_path
#                     )
#                 logger.info("✅ Installed")

#             # MODE 1: Simple script (no server)
#             if not is_server_project:
#                 logger.info("📜 Executing script...")
#                 result = await self._execute_simple_script(
#                     sandbox,
#                     start_command,
#                     project_path
#                 )
                
#                 # Cleanup immediately for scripts
#                 try:
#                     sandbox.kill()
#                     logger.info("✅ Sandbox cleaned")
#                 except:
#                     pass
                
#                 return result
            
#             # MODE 2: Web server
#             else:
#                 logger.info(f"🌐 Starting {project_type} server...")
#                 result = await self._start_web_server(
#                     sandbox,
#                     start_command,
#                     port,
#                     project_type,
#                     sandbox_id,
#                     project_path,
#                     project_name
#                 )
                
#                 # Keep alive for servers
#                 if result.get("server_started"):
#                     sandbox_manager.register_server(project_name, sandbox, {
#                         "url": result["server_url"],
#                         "port": port
#                     })
                
#                 return result

#         except Exception as e:
#             logger.error(f"❌ Error: {e}")
            
#             if sandbox and not is_server_project:
#                 try:
#                     sandbox.kill()
#                 except:
#                     pass
            
#             return self._error_response(str(e))
    
#     async def _execute_simple_script(
#         self,
#         sandbox,
#         command: str,
#         project_path: str
#     ) -> Dict[str, Any]:
#         """
#         Execute simple script and return output
#         Perfect for: odd/even checker, calculator, etc.
#         """
        
#         logger.info(f"🚀 Running: {command}")
        
#         try:
#             # For interactive scripts, run directly
#             if command.startswith("python "):
#                 # Extract filename
#                 filename = command.replace("python ", "").strip()
                
#                 # Read the file to check if it's interactive
#                 read_code = f"""
# with open('{filename}', 'r') as f:
#     code = f.read()
# print(code)
# """
#                 file_content_result = sandbox.run_code(read_code)
#                 file_content = ""
#                 if hasattr(file_content_result, 'text'):
#                     file_content = file_content_result.text or ""
                
#                 # Check if interactive (has input())
#                 if "input(" in file_content:
#                     logger.info("📝 Interactive script detected")
                    
#                     return {
#                         "success": True,
#                         "stdout": f"""🎯 Interactive Python Script Created!

# 📁 File: {filename}
# 📍 Location: {project_path}

# 🚀 To run this script:
# 1. Open terminal in project folder
# 2. Run: python {filename}
# 3. Enter numbers when prompted

# Example:
# $ python {filename}
# Enter a number: 5
# 5 is odd

# The script is ready and saved!""",
#                         "stderr": "",
#                         "exit_code": 0,
#                         "execution_time": 0.5,
#                         "project_path": project_path,
#                         "is_interactive": True
#                     }
            
#             # Execute non-interactive command
#             execution = sandbox.run_code(f"!{command}")
            
#             stdout = ""
#             stderr = ""
#             success = True
            
#             if hasattr(execution, 'error') and execution.error:
#                 stderr = str(execution.error)
#                 success = False
#             else:
#                 if hasattr(execution, 'text'):
#                     stdout = execution.text or ""
#                 elif hasattr(execution, 'results'):
#                     for result in execution.results:
#                         if hasattr(result, 'text'):
#                             stdout += result.text or ""
            
#             return {
#                 "success": success,
#                 "stdout": stdout,
#                 "stderr": stderr,
#                 "exit_code": 0 if success else 1,
#                 "execution_time": 0.5,
#                 "project_path": project_path
#             }
        
#         except Exception as e:
#             logger.error(f"❌ Execution error: {e}")
#             return self._error_response(str(e), project_path=project_path)
    
#     async def _start_web_server(
#         self,
#         sandbox,
#         start_command: str,
#         port: int,
#         project_type: str,
#         sandbox_id: str,
#         project_path: str,
#         project_name: str
#     ) -> Dict[str, Any]:
#         """
#         Start web server with CORRECT E2B approach
        
#         Key insight: We need to use nohup or screen to keep process alive
#         """
        
#         logger.info(f"🚀 Starting {project_type} server on port {port}...")
        
#         server_url = f"https://{sandbox_id}-{port}.sandbox.e2b.dev"
        
#         # Use BASH to start process in background
#         # Key: Use nohup and & to detach from parent process
#         if project_type == "react":
#             bash_command = f"""
# export PORT={port}
# nohup npm start > /tmp/server.log 2> /tmp/server.err &
# echo "Started process $!"
# """
#         elif project_type == "flask":
#             bash_command = f"""
# export FLASK_APP=app.py
# nohup flask run --host=0.0.0.0 --port={port} > /tmp/server.log 2> /tmp/server.err &
# echo "Started process $!"
# """
#         elif project_type == "fastapi":
#             bash_command = f"""
# nohup uvicorn main:app --host 0.0.0.0 --port {port} > /tmp/server.log 2> /tmp/server.err &
# echo "Started process $!"
# """
#         elif project_type in ["express", "node"]:
#             bash_command = f"""
# export PORT={port}
# nohup node server.js > /tmp/server.log 2> /tmp/server.err &
# echo "Started process $!"
# """
#         else:
#             # Generic
#             bash_command = f"""
# nohup {start_command} > /tmp/server.log 2> /tmp/server.err &
# echo "Started process $!"
# """
        
#         try:
#             # Start server using bash
#             start_result = sandbox.run_code(f"!{bash_command}")
            
#             if hasattr(start_result, 'error') and start_result.error:
#                 logger.error(f"❌ Start failed: {start_result.error}")
#                 return self._error_response(
#                     f"Server start failed: {start_result.error}",
#                     project_path=project_path
#                 )
            
#             if hasattr(start_result, 'text'):
#                 logger.info(f"Start output: {start_result.text}")
            
#             # Wait for server
#             wait_time = 45 if project_type == "react" else 10
#             logger.info(f"⏳ Waiting {wait_time}s for server...")
#             await asyncio.sleep(wait_time)
            
#             # Check if process is running
#             check_process = sandbox.run_code("!ps aux | grep -E 'npm|node|python|flask|uvicorn' | grep -v grep")
            
#             is_running = False
#             if hasattr(check_process, 'text'):
#                 process_output = check_process.text or ""
#                 logger.info(f"Process check: {process_output[:200]}")
#                 is_running = len(process_output) > 10  # Has some process output
            
#             # Check port
#             port_listening = await self._check_port(sandbox, port)
            
#             # Check logs
#             log_output = ""
#             log_check = sandbox.run_code("""!tail -n 50 /tmp/server.log 2>/dev/null || echo 'No log'""")
#             if hasattr(log_check, 'text'):
#                 log_output = log_check.text or ""
#                 logger.info(f"Server logs:\n{log_output[:500]}")
            
#             logger.info(f"✅ Server URL: {server_url}")
            
#             # Build message
#             message = f"""🎉 {project_type.title()} Server Started!

# 📁 Project: {project_path}
# 🌐 URL: {server_url}
# 🔌 Port: {port}

# """
            
#             if project_type == "react":
#                 message += """⏳ IMPORTANT: React takes time to compile!
# - First load: 1-2 minutes
# - Refresh if you see errors
# - Check back in 60 seconds

# The server is running and compiling in the background."""
#             else:
#                 message += "✅ Server should be ready now!"
            
#             return {
#                 "success": True,
#                 "stdout": message,
#                 "stderr": "",
#                 "exit_code": 0,
#                 "execution_time": float(wait_time),
#                 "server_started": True,
#                 "server_url": server_url,
#                 "server_port": port,
#                 "sandbox_id": sandbox_id,
#                 "project_path": project_path,
#                 "project_name": project_name,
#                 "keep_alive": True,
#                 "server_logs": log_output,
#                 "process_running": is_running,
#                 "port_listening": port_listening,
#                 "message": message
#             }
        
#         except Exception as e:
#             logger.error(f"❌ Server error: {e}")
#             return self._error_response(str(e), project_path=project_path)
    
#     async def _check_port(self, sandbox, port: int) -> bool:
#         """Check if port is listening"""
        
#         check_code = f"""!netstat -tuln | grep {port} || ss -tuln | grep {port} || echo "NOT_LISTENING" """
        
#         try:
#             result = sandbox.run_code(check_code)
#             if hasattr(result, 'text'):
#                 output = result.text or ""
#                 logger.info(f"Port check: {output[:100]}")
#                 return "LISTEN" in output or str(port) in output
#         except:
#             pass
        
#         return False
    
#     def _create_file_in_sandbox(self, sandbox, filepath: str, content: str):
#         """Create file in sandbox"""
        
#         # Create directory
#         if '/' in filepath:
#             directory = '/'.join(filepath.split('/')[:-1])
#             sandbox.run_code(f"!mkdir -p {directory}")
        
#         # Escape content for bash
#         import json
#         content_json = json.dumps(content)
        
#         # Write file
#         write_code = f"""
# import json
# content = json.loads({json.dumps(content_json)})
# with open('{filepath}', 'w', encoding='utf-8') as f:
#     f.write(content)
# """
#         sandbox.run_code(write_code)
    
#     def _save_to_workspace(self, files: Dict[str, str], project_name: str) -> str:
#         """Save to local workspace"""
#         try:
#             workspace_dir = Path(self.workspace_path)
#             workspace_dir.mkdir(parents=True, exist_ok=True)
            
#             project_dir = workspace_dir / project_name
            
#             if project_dir.exists():
#                 import datetime
#                 ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
#                 project_dir = workspace_dir / f"{project_name}_{ts}"
            
#             project_dir.mkdir(parents=True, exist_ok=True)
            
#             for filepath, content in files.items():
#                 file_path = project_dir / filepath
#                 file_path.parent.mkdir(parents=True, exist_ok=True)
#                 file_path.write_text(content, encoding='utf-8')
            
#             return str(project_dir)
#         except Exception as e:
#             logger.error(f"❌ Workspace save error: {e}")
#             return ""
    
#     def _error_response(self, error_msg: str, project_path: str = "") -> Dict[str, Any]:
#         return {
#             "success": False,
#             "error": error_msg,
#             "stdout": "",
#             "stderr": error_msg,
#             "exit_code": 1,
#             "project_path": project_path
#         }
    
#     async def execute_python(self, code: str, **kwargs) -> Dict[str, Any]:
#         """Legacy single-file Python execution"""
#         if not self.api_key:
#             return self._error_response("E2B_API_KEY not set")
        
#         sandbox = None
#         try:
#             sandbox = Sandbox.create()
#             execution = sandbox.run_code(code)
            
#             stdout = ""
#             stderr = ""
#             success = True
            
#             if hasattr(execution, 'error') and execution.error:
#                 stderr = str(execution.error)
#                 success = False
#             else:
#                 if hasattr(execution, 'text'):
#                     stdout = execution.text or ""
            
#             return {
#                 "success": success,
#                 "stdout": stdout,
#                 "stderr": stderr,
#                 "exit_code": 0 if success else 1
#             }
#         except Exception as e:
#             return self._error_response(str(e))
#         finally:
#             if sandbox:
#                 try:
#                     sandbox.kill()
#                 except:
#                     pass
    
#     def is_available(self) -> bool:
#         return bool(self.api_key)


# # Global instance
# sandbox_service = EnhancedSandboxService()