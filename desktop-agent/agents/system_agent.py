"""
System Agent — System info, clipboard, hardware monitoring
"""
import os
import platform
import subprocess
from typing import Dict, Any, List
from loguru import logger
from agents.base_agent import BaseAgent

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not installed — system monitoring limited")

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False
    logger.warning("pyperclip not installed — clipboard access limited")


class SystemAgent(BaseAgent):
    """Agent for system monitoring, clipboard, and hardware info"""

    def __init__(self):
        super().__init__(
            name="system_agent",
            description="Get system info (CPU, RAM, battery, network, processes), manage clipboard, control volume",
        )
        self._clipboard_history: List[str] = []
        self._max_history = 20

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_system_info",
                "description": "Get comprehensive system information: OS, CPU, RAM, disk, battery, network",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_cpu_usage",
                "description": "Get current CPU usage percentage",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_memory_usage",
                "description": "Get current RAM/memory usage",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_disk_usage",
                "description": "Get disk space usage for all drives",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_battery_status",
                "description": "Get battery level and charging status (laptops only)",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "list_processes",
                "description": "List running processes sorted by memory usage",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "top_n": {
                            "type": "integer",
                            "description": "Number of top processes to return (default: 15)",
                        },
                    },
                },
            },
            {
                "name": "kill_process",
                "description": "Kill a process by name or PID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Process name or PID to kill",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "get_clipboard",
                "description": "Get the current clipboard text content",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "set_clipboard",
                "description": "Copy text to the clipboard",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to copy to clipboard",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "get_network_info",
                "description": "Get network connection status, IP address, and Wi-Fi info",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "get_system_info": lambda: self._system_info(),
            "get_cpu_usage": lambda: self._cpu_usage(),
            "get_memory_usage": lambda: self._memory_usage(),
            "get_disk_usage": lambda: self._disk_usage(),
            "get_battery_status": lambda: self._battery(),
            "list_processes": lambda: self._list_processes(args.get("top_n", 15)),
            "kill_process": lambda: self._kill_process(args.get("name", "")),
            "get_clipboard": lambda: self._get_clipboard(),
            "set_clipboard": lambda: self._set_clipboard(args.get("text", "")),
            "get_network_info": lambda: self._network_info(),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    def _system_info(self) -> Dict[str, Any]:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
            "username": os.getlogin(),
            "python_version": platform.python_version(),
        }

        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            info["ram_total_gb"] = round(mem.total / (1024**3), 1)
            info["ram_used_gb"] = round(mem.used / (1024**3), 1)
            info["ram_percent"] = mem.percent
            info["cpu_count"] = psutil.cpu_count()
            info["cpu_percent"] = psutil.cpu_percent(interval=1)
            info["uptime_hours"] = round(
                (psutil.time.time() - psutil.boot_time()) / 3600, 1
            )

        return self._success(info, "System information retrieved")

    def _cpu_usage(self) -> Dict[str, Any]:
        if not HAS_PSUTIL:
            return self._error("psutil not installed")
        usage = psutil.cpu_percent(interval=1, percpu=True)
        return self._success(
            {
                "overall": psutil.cpu_percent(interval=0),
                "per_core": usage,
                "cores": psutil.cpu_count(),
            },
            f"CPU usage: {psutil.cpu_percent()}%",
        )

    def _memory_usage(self) -> Dict[str, Any]:
        if not HAS_PSUTIL:
            return self._error("psutil not installed")
        mem = psutil.virtual_memory()
        return self._success(
            {
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent": mem.percent,
            },
            f"RAM: {mem.percent}% used ({round(mem.used / (1024**3), 1)}GB / {round(mem.total / (1024**3), 1)}GB)",
        )

    def _disk_usage(self) -> Dict[str, Any]:
        if not HAS_PSUTIL:
            return self._error("psutil not installed")
        drives = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                drives.append({
                    "drive": part.device,
                    "mountpoint": part.mountpoint,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "percent": usage.percent,
                })
            except PermissionError:
                pass
        return self._success({"drives": drives}, f"Found {len(drives)} drives")

    def _battery(self) -> Dict[str, Any]:
        if not HAS_PSUTIL:
            return self._error("psutil not installed")
        battery = psutil.sensors_battery()
        if not battery:
            return self._success(
                {"has_battery": False},
                "No battery detected (desktop PC)",
            )
        return self._success(
            {
                "has_battery": True,
                "percent": battery.percent,
                "charging": battery.power_plugged,
                "time_left_minutes": (
                    round(battery.secsleft / 60)
                    if battery.secsleft > 0
                    else None
                ),
            },
            f"Battery: {battery.percent}% {'(charging)' if battery.power_plugged else ''}",
        )

    def _list_processes(self, top_n: int = 15) -> Dict[str, Any]:
        if not HAS_PSUTIL:
            return self._error("psutil not installed")

        procs = []
        for proc in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
            try:
                info = proc.info
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "memory_percent": round(info.get("memory_percent", 0), 1),
                    "cpu_percent": round(info.get("cpu_percent", 0), 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda x: x["memory_percent"], reverse=True)
        return self._success(
            {"processes": procs[:top_n], "total": len(procs)},
            f"Top {top_n} processes by memory usage",
        )

    def _kill_process(self, name: str) -> Dict[str, Any]:
        # Safety check
        protected = ["explorer", "csrss", "winlogon", "svchost", "system", "lsass"]
        if name.lower().replace(".exe", "") in protected:
            return self._error(f"Cannot kill protected process: {name}")

        try:
            result = subprocess.run(
                ["taskkill", "/IM", f"{name}.exe", "/F"] if not name.isdigit()
                else ["taskkill", "/PID", name, "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return self._success({"killed": name}, f"Killed process: {name}")
            return self._error(f"Could not kill {name}: {result.stderr.strip()}")
        except Exception as e:
            return self._error(f"Failed to kill process: {e}")

    def _get_clipboard(self) -> Dict[str, Any]:
        if HAS_PYPERCLIP:
            try:
                text = pyperclip.paste()
                return self._success(
                    {"text": text, "length": len(text)},
                    f"Clipboard: {text[:50]}..." if len(text) > 50 else f"Clipboard: {text}",
                )
            except Exception as e:
                return self._error(f"Clipboard read failed: {e}")

        # Fallback: PowerShell
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5,
            )
            text = result.stdout.strip()
            return self._success({"text": text, "length": len(text)}, "Clipboard content")
        except Exception as e:
            return self._error(f"Clipboard read failed: {e}")

    def _set_clipboard(self, text: str) -> Dict[str, Any]:
        if HAS_PYPERCLIP:
            try:
                pyperclip.copy(text)
                self._clipboard_history.append(text)
                if len(self._clipboard_history) > self._max_history:
                    self._clipboard_history.pop(0)
                return self._success(
                    {"copied": True, "length": len(text)},
                    f"Copied to clipboard ({len(text)} chars)",
                )
            except Exception as e:
                return self._error(f"Clipboard write failed: {e}")

        # Fallback
        try:
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard -Value '{text}'"],
                capture_output=True, text=True, timeout=5,
            )
            return self._success({"copied": True}, "Copied to clipboard")
        except Exception as e:
            return self._error(f"Clipboard write failed: {e}")

    def _network_info(self) -> Dict[str, Any]:
        info = {}
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -ne '127.0.0.1'} | "
                 "Select-Object IPAddress, InterfaceAlias | Format-Table -AutoSize | Out-String"],
                capture_output=True, text=True, timeout=10,
            )
            info["ip_info"] = result.stdout.strip()
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "SSID" in line and "BSSID" not in line:
                    info["wifi_network"] = line.split(":", 1)[1].strip()
                elif "Signal" in line:
                    info["wifi_signal"] = line.split(":", 1)[1].strip()
                elif "State" in line:
                    info["wifi_state"] = line.split(":", 1)[1].strip()
        except Exception:
            pass

        if HAS_PSUTIL:
            net = psutil.net_io_counters()
            info["bytes_sent_mb"] = round(net.bytes_sent / (1024**2), 1)
            info["bytes_recv_mb"] = round(net.bytes_recv / (1024**2), 1)

        return self._success(info, "Network information retrieved")


# Global instance
system_agent = SystemAgent()
