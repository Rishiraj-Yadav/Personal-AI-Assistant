"""
Slash Command Service - Handles chat commands like /new, /status, /compact
Inspired by OpenClaw's chat command system.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from loguru import logger


class SlashCommandService:
    """Processes slash commands from chat input"""

    COMMANDS = {
        "/new": "Reset the current conversation and start fresh",
        "/status": "Show session status (model, memory, agents)",
        "/compact": "Compact conversation history (summarize old messages to save tokens)",
        "/help": "Show available slash commands",
        "/reminders": "List active reminders",
        "/history": "Show conversation stats",
        "/dashboard": "Get a link to your web dashboard",
        "/permissions": "View your permission tier and allowed agents",
    }

    def is_slash_command(self, message: str) -> bool:
        """Check if a message is a slash command"""
        return message.strip().startswith("/") and message.strip().split()[0].lower() in self.COMMANDS

    def parse_command(self, message: str) -> tuple:
        """Parse command name and args from message"""
        parts = message.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return command, args

    async def execute(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> Dict[str, Any]:
        """Execute a slash command and return the result"""
        command, args = self.parse_command(message)

        if command == "/new":
            return await self._cmd_new(user_id, conversation_id)
        elif command == "/status":
            return await self._cmd_status(user_id, conversation_id)
        elif command == "/compact":
            return await self._cmd_compact(user_id, conversation_id)
        elif command == "/help":
            return self._cmd_help()
        elif command == "/reminders":
            return await self._cmd_reminders(user_id)
        elif command == "/history":
            return await self._cmd_history(user_id, conversation_id)
        elif command == "/dashboard":
            return await self._cmd_dashboard(user_id)
        elif command == "/permissions":
            return await self._cmd_permissions(user_id)
        else:
            return {
                "type": "slash_command",
                "command": command,
                "response": f"Unknown command: {command}\nType /help for available commands.",
                "action": None,
            }

    async def _cmd_new(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """Reset conversation"""
        return {
            "type": "slash_command",
            "command": "/new",
            "response": "🗑️ **Conversation Reset**\n\nStarting a fresh conversation. Your memories and preferences are preserved.",
            "action": "new_conversation",
        }

    async def _cmd_status(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """Show session status"""
        from app.config import settings
        from app.services.enhanced_memory_service import enhanced_memory_service

        # Get memory stats
        try:
            history = enhanced_memory_service.get_conversation_history(conversation_id, limit=1000)
            msg_count = len(history) if history else 0
        except Exception:
            msg_count = 0

        # Get vector memory stats
        try:
            from app.services.vector_memory_service import vector_memory
            vm_stats = vector_memory.get_collection_stats() if vector_memory else {}
        except Exception:
            vm_stats = {}

        # Check Google connection
        try:
            from app.services.google_auth_service import google_auth_service
            google_connected = google_auth_service.is_connected(user_id)
        except Exception:
            google_connected = False

        status_lines = [
            "📊 **SonarBot Status**\n",
            f"**Model:** {settings.GROQ_MODEL}",
            f"**Version:** {settings.APP_VERSION}",
            f"**Messages in conversation:** {msg_count}",
            f"**Google Connected:** {'✅ Yes' if google_connected else '❌ No'}",
            f"**Vector Memory:** {vm_stats.get('total_messages', '?')} messages, {vm_stats.get('total_insights', '?')} insights",
            f"**Agents:** Router (Gemini) → Code, Desktop, Web, Email, Calendar, General (Groq)",
            f"**Conversation ID:** `{conversation_id}`",
        ]

        return {
            "type": "slash_command",
            "command": "/status",
            "response": "\n".join(status_lines),
            "action": None,
        }

    async def _cmd_compact(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """Compact conversation — summarize + trim old messages"""
        from app.services.context_compaction_service import context_compaction_service

        try:
            result = await context_compaction_service.compact_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return {
                "type": "slash_command",
                "command": "/compact",
                "response": result["message"],
                "action": "compacted",
                "metadata": result,
            }
        except Exception as e:
            logger.error(f"❌ Compact error: {e}")
            return {
                "type": "slash_command",
                "command": "/compact",
                "response": f"❌ Failed to compact conversation: {str(e)}",
                "action": None,
            }

    def _cmd_help(self) -> Dict[str, Any]:
        """Show available commands"""
        lines = ["📋 **Available Commands**\n"]
        for cmd, desc in self.COMMANDS.items():
            lines.append(f"  `{cmd}` — {desc}")
        lines.append("\nType any command to execute it.")
        return {
            "type": "slash_command",
            "command": "/help",
            "response": "\n".join(lines),
            "action": None,
        }

    async def _cmd_reminders(self, user_id: str) -> Dict[str, Any]:
        """List active reminders"""
        try:
            from app.services.scheduler_service import scheduler_service
            jobs = scheduler_service.list_jobs(user_id)
            if jobs:
                lines = [f"⏰ **{len(jobs)} Active Reminders**\n"]
                for j in jobs:
                    lines.append(f"- **{j['description']}** — next: {j['next_run'] or 'N/A'}")
            else:
                lines = ["📭 No active reminders."]
            return {
                "type": "slash_command",
                "command": "/reminders",
                "response": "\n".join(lines),
                "action": None,
            }
        except Exception as e:
            return {
                "type": "slash_command",
                "command": "/reminders",
                "response": f"❌ Error: {e}",
                "action": None,
            }

    async def _cmd_history(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """Show conversation stats"""
        from app.services.enhanced_memory_service import enhanced_memory_service

        try:
            history = enhanced_memory_service.get_conversation_history(conversation_id, limit=1000)
            msg_count = len(history) if history else 0
            user_msgs = sum(1 for m in history if m.get("role") == "user") if history else 0
            bot_msgs = msg_count - user_msgs

            lines = [
                "📈 **Conversation Stats**\n",
                f"**Total messages:** {msg_count}",
                f"**Your messages:** {user_msgs}",
                f"**Bot messages:** {bot_msgs}",
                f"**Conversation ID:** `{conversation_id}`",
            ]
            if history:
                first = history[0].get("timestamp", "?")
                last = history[-1].get("timestamp", "?")
                lines.append(f"**Started:** {first}")
                lines.append(f"**Last activity:** {last}")

            return {
                "type": "slash_command",
                "command": "/history",
                "response": "\n".join(lines),
                "action": None,
            }
        except Exception as e:
            return {
                "type": "slash_command",
                "command": "/history",
                "response": f"❌ Error: {e}",
                "action": None,
            }

    async def _cmd_dashboard(self, user_id: str) -> Dict[str, Any]:
        """Generate a dashboard link for the user"""
        from app.api.routes.dashboard import generate_dashboard_token
        import os

        token = generate_dashboard_token(user_id)
        base_url = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8000")
        link = f"{base_url}/api/v1/dashboard/?token={token}"

        return {
            "type": "slash_command",
            "command": "/dashboard",
            "response": (
                "🌐 **Your SonarBot Dashboard**\n\n"
                f"[Open Dashboard]({link})\n\n"
                "This link is valid for 24 hours. "
                "You can view your conversations, permissions, and preferences."
            ),
            "action": None,
        }

    async def _cmd_permissions(self, user_id: str) -> Dict[str, Any]:
        """Show user's permission tier and allowed agents"""
        from app.services.permission_service import permission_service

        perms = permission_service.get_permissions(user_id)
        agents = ", ".join(perms.get("allowed_agents", []))
        lines = [
            "🔑 **Your Permissions**\n",
            f"**Tier:** {perms.get('tier', 'unknown')}",
            f"**Allowed Agents:** {agents}",
            f"**Desktop Access:** {perms.get('desktop_access', 'none')}",
            f"**Sandbox:** {'✅ Enabled' if perms.get('sandbox_enabled') else '❌ Disabled'}",
            f"**Messages Today:** {perms.get('messages_today', 0)} / {perms.get('daily_message_limit', 100)}",
        ]
        return {
            "type": "slash_command",
            "command": "/permissions",
            "response": "\n".join(lines),
            "action": None,
        }


slash_command_service = SlashCommandService()
