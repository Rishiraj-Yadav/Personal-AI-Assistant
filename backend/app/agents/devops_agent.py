"""
DevOps / Sandbox-Ops Agent
Manages sandbox environments, Docker lifecycle, port conflicts, and
environment health. Wraps the existing sandbox_service with LLM-powered
reasoning for intelligent infrastructure decisions.
"""
import os
import asyncio
import socket
from typing import Dict, Any, Optional
from loguru import logger
import google.generativeai as genai


class DevOpsAgent:
    """
    DevOps Agent — Manages infrastructure for the multi-agent pipeline.
    
    Capabilities:
    - health_check: Ping sandbox/Docker services, report status
    - cleanup: Kill zombie processes, free ports, remove stale containers
    - provision: Spin up a fresh sandbox on demand
    - rollback: Restore a previous environment state
    """

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel("gemini-2.0-flash")
        else:
            self.model = None
            logger.warning("⚠️ GOOGLE_API_KEY not set for DevOps Agent")
        logger.info("✅ DevOps Agent initialized")

    async def execute(self, action: str, params: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Route to the appropriate DevOps capability.
        """
        params = params or {}
        context = context or {}

        action_map = {
            "health_check": self._health_check,
            "cleanup": self._cleanup,
            "provision": self._provision,
            "diagnose": self._diagnose,
        }

        handler = action_map.get(action)
        if not handler:
            return {"success": False, "error": f"Unknown DevOps action: {action}"}

        try:
            return await handler(params, context)
        except Exception as e:
            logger.error(f"❌ DevOps Agent error ({action}): {e}")
            return {"success": False, "error": str(e)}

    async def _health_check(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Check health of all agent services and sandbox."""
        results = {}

        # Check Desktop Agent
        results["desktop_agent"] = await self._ping_service(
            os.getenv("DESKTOP_AGENT_URL", "http://host.docker.internal:7777"),
            "Desktop Agent"
        )

        # Check Browser Agent
        results["browser_agent"] = await self._ping_service(
            os.getenv("BROWSER_AGENT_URL", "http://host.docker.internal:4000"),
            "Browser Agent"
        )

        # Check E2B Sandbox availability
        e2b_key = os.getenv("E2B_API_KEY", "")
        results["sandbox"] = {
            "status": "available" if e2b_key else "unavailable",
            "configured": bool(e2b_key),
        }

        # Check common ports
        ports_to_check = [3000, 5000, 5555, 7777, 4000, 8000, 8100]
        port_status = {}
        for port in ports_to_check:
            port_status[port] = self._is_port_in_use(port)
        results["ports"] = port_status

        all_healthy = (
            results["desktop_agent"]["status"] == "healthy"
            and results["browser_agent"]["status"] == "healthy"
            and results["sandbox"]["status"] == "available"
        )

        return {
            "success": True,
            "healthy": all_healthy,
            "services": results,
            "message": "All systems operational" if all_healthy else "Some services are degraded",
        }

    async def _cleanup(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Clean up zombie processes and free ports."""
        freed_ports = []
        target_port = params.get("port")

        if target_port and self._is_port_in_use(target_port):
            logger.info(f"🧹 DevOps: Attempting to free port {target_port}")
            try:
                # Use OS-level commands to find and kill the process
                result = await asyncio.to_thread(
                    os.popen,
                    f"netstat -ano | findstr :{target_port}"
                )
                output = result.read()
                if output.strip():
                    # Extract PIDs
                    lines = output.strip().split("\n")
                    pids = set()
                    for line in lines:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pids.add(parts[-1])

                    for pid in pids:
                        if pid != "0":
                            logger.info(f"🔪 Killing PID {pid} on port {target_port}")
                            os.system(f"taskkill /F /PID {pid}")
                            freed_ports.append(target_port)

                    return {
                        "success": True,
                        "freed_ports": freed_ports,
                        "message": f"Freed port {target_port} by killing PIDs: {pids}",
                    }
            except Exception as e:
                logger.error(f"Failed to free port {target_port}: {e}")
                return {"success": False, "error": str(e)}

        return {
            "success": True,
            "freed_ports": [],
            "message": f"Port {target_port} is already free" if target_port else "No port specified",
        }

    async def _provision(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Provision a fresh sandbox environment."""
        try:
            from ..services.sandbox_services import sandbox_service

            if not sandbox_service.is_available():
                return {
                    "success": False,
                    "error": "E2B sandbox not configured (E2B_API_KEY missing)",
                }

            # Test that we can create a sandbox
            from e2b_code_interpreter import Sandbox
            sandbox = Sandbox.create()
            sandbox_id = getattr(sandbox, "sandbox_id", "unknown")
            
            # Run a quick smoke test
            test_result = sandbox.run_code("print('DevOps health check: OK')")
            output = getattr(test_result, "text", "")
            healthy = "OK" in (output or "")

            sandbox.kill()

            return {
                "success": healthy,
                "sandbox_id": sandbox_id,
                "message": "Fresh sandbox provisioned and verified" if healthy else "Sandbox created but smoke test failed",
            }

        except Exception as e:
            return {"success": False, "error": f"Sandbox provisioning failed: {e}"}

    async def _diagnose(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Use LLM to diagnose an infrastructure error and suggest a fix."""
        error_msg = params.get("error", context.get("error", "Unknown error"))

        if not self.model:
            return {
                "success": False,
                "error": "LLM not available for diagnosis",
                "suggestion": "Check environment variables and service connectivity manually.",
            }

        prompt = f"""You are a DevOps engineer diagnosing an infrastructure error in a multi-agent AI system.

Error: {error_msg}

Available Services:
- Desktop Agent (Python HTTP server on port 7777)
- Browser Agent (TypeScript HTTP server on port 4000)
- E2B Sandbox (cloud code execution)
- Docker containers for backend services

Provide:
1. Root cause (1-2 sentences)
2. Recommended fix (specific commands or config changes)
3. Prevention strategy (1 sentence)

Be concise."""

        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            diagnosis = response.text.strip()

            return {
                "success": True,
                "error_analyzed": error_msg,
                "diagnosis": diagnosis,
                "message": "Diagnosis complete",
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Diagnosis failed: {e}",
                "suggestion": "Check network connectivity and API keys.",
            }

    async def _ping_service(self, url: str, name: str) -> Dict[str, str]:
        """Ping a service's health endpoint."""
        import requests
        try:
            resp = await asyncio.to_thread(
                requests.get, f"{url}/health", timeout=3
            )
            if resp.status_code == 200:
                return {"status": "healthy", "url": url}
            else:
                return {"status": "degraded", "url": url, "code": str(resp.status_code)}
        except Exception:
            return {"status": "unreachable", "url": url}

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is currently in use."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(("localhost", port))
                return result == 0
        except Exception:
            return False


# Global instance
devops_agent = DevOpsAgent()
