"""
E2B Sandbox Service
Secure code execution using E2B (e2b.dev) cloud sandboxes
"""
import os
import asyncio
from typing import Dict, Any, Optional, List
from loguru import logger
import httpx


class SandboxService:
    """
    E2B Sandbox Integration
    Executes code in isolated, secure cloud environments
    """
    
    def __init__(self):
        """Initialize E2B sandbox service"""
        self.api_key = os.getenv("E2B_API_KEY", "")
        self.api_url = "https://api.e2b.dev/sandboxes"
        self.timeout = httpx.Timeout(120.0)  # 2 minutes for code execution
        
        if not self.api_key:
            logger.warning("⚠️ E2B_API_KEY not set - code execution disabled")
        else:
            logger.info("✅ E2B Sandbox Service initialized")
    
    async def execute_python(
        self, 
        code: str, 
        files: Optional[Dict[str, str]] = None,
        packages: Optional[List[str]] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute Python code in E2B sandbox
        
        Args:
            code: Python code to execute
            files: Additional files {filename: content}
            packages: pip packages to install
            timeout: Execution timeout in seconds
            
        Returns:
            Execution result with stdout, stderr, exit_code
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "E2B API key not configured. Set E2B_API_KEY environment variable."
            }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Create sandbox
                create_response = await client.post(
                    f"{self.api_url}/python",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "template": "python-3.11",
                        "timeout": timeout
                    }
                )
                
                if create_response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Failed to create sandbox: {create_response.text}"
                    }
                
                sandbox = create_response.json()
                sandbox_id = sandbox["id"]
                
                logger.info(f"🔵 Created sandbox: {sandbox_id}")
                
                try:
                    # Install packages if specified
                    if packages:
                        install_result = await self._install_packages(
                            client, sandbox_id, packages
                        )
                        if not install_result["success"]:
                            return install_result
                    
                    # Upload files if specified
                    if files:
                        for filename, content in files.items():
                            await self._upload_file(client, sandbox_id, filename, content)
                    
                    # Execute code
                    exec_response = await client.post(
                        f"{self.api_url}/{sandbox_id}/execute",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "code": code,
                            "timeout": timeout
                        }
                    )
                    
                    if exec_response.status_code != 200:
                        return {
                            "success": False,
                            "error": f"Execution failed: {exec_response.text}"
                        }
                    
                    result = exec_response.json()
                    
                    return {
                        "success": True,
                        "stdout": result.get("stdout", ""),
                        "stderr": result.get("stderr", ""),
                        "exit_code": result.get("exit_code", 0),
                        "execution_time": result.get("execution_time", 0),
                        "sandbox_id": sandbox_id
                    }
                
                finally:
                    # Always cleanup sandbox
                    await self._delete_sandbox(client, sandbox_id)
        
        except httpx.TimeoutException:
            logger.error(f"⏱️ Execution timeout after {timeout}s")
            return {
                "success": False,
                "error": f"Execution timeout after {timeout} seconds"
            }
        
        except Exception as e:
            logger.error(f"❌ Sandbox execution error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_javascript(
        self,
        code: str,
        files: Optional[Dict[str, str]] = None,
        packages: Optional[List[str]] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute JavaScript/Node.js code in E2B sandbox
        
        Args:
            code: JavaScript code to execute
            files: Additional files
            packages: npm packages to install
            timeout: Execution timeout
            
        Returns:
            Execution result
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "E2B API key not configured"
            }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Create Node.js sandbox
                create_response = await client.post(
                    f"{self.api_url}/nodejs",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "template": "nodejs-20",
                        "timeout": timeout
                    }
                )
                
                if create_response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Failed to create sandbox: {create_response.text}"
                    }
                
                sandbox = create_response.json()
                sandbox_id = sandbox["id"]
                
                try:
                    # Install npm packages
                    if packages:
                        npm_install = f"npm install {' '.join(packages)}"
                        await client.post(
                            f"{self.api_url}/{sandbox_id}/execute",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json={"code": npm_install, "shell": True}
                        )
                    
                    # Execute code
                    exec_response = await client.post(
                        f"{self.api_url}/{sandbox_id}/execute",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={"code": code, "timeout": timeout}
                    )
                    
                    result = exec_response.json()
                    
                    return {
                        "success": True,
                        "stdout": result.get("stdout", ""),
                        "stderr": result.get("stderr", ""),
                        "exit_code": result.get("exit_code", 0),
                        "sandbox_id": sandbox_id
                    }
                
                finally:
                    await self._delete_sandbox(client, sandbox_id)
        
        except Exception as e:
            logger.error(f"❌ JavaScript execution error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _install_packages(
        self, 
        client: httpx.AsyncClient, 
        sandbox_id: str, 
        packages: List[str]
    ) -> Dict[str, Any]:
        """Install pip packages in sandbox"""
        install_cmd = f"pip install {' '.join(packages)}"
        
        response = await client.post(
            f"{self.api_url}/{sandbox_id}/execute",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"code": install_cmd, "shell": True}
        )
        
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Package installation failed: {response.text}"
            }
        
        result = response.json()
        if result.get("exit_code", 0) != 0:
            return {
                "success": False,
                "error": f"Package installation failed: {result.get('stderr', '')}"
            }
        
        logger.info(f"📦 Installed packages: {', '.join(packages)}")
        return {"success": True}
    
    async def _upload_file(
        self, 
        client: httpx.AsyncClient, 
        sandbox_id: str, 
        filename: str, 
        content: str
    ):
        """Upload file to sandbox"""
        await client.post(
            f"{self.api_url}/{sandbox_id}/files",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"path": filename, "content": content}
        )
        logger.info(f"📄 Uploaded file: {filename}")
    
    async def _delete_sandbox(self, client: httpx.AsyncClient, sandbox_id: str):
        """Delete sandbox after execution"""
        try:
            await client.delete(
                f"{self.api_url}/{sandbox_id}",
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            logger.info(f"🗑️ Deleted sandbox: {sandbox_id}")
        except Exception as e:
            logger.warning(f"Failed to delete sandbox {sandbox_id}: {e}")
    
    def is_available(self) -> bool:
        """Check if E2B service is configured"""
        return bool(self.api_key)


# Global sandbox service instance
sandbox_service = SandboxService()