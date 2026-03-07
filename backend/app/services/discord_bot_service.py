"""
Discord Bot Service for SonarBot
Thread-based conversations — each new user message in a channel auto-creates
a Discord thread for isolated conversation context (OpenClaw-style).
"""
import os
import asyncio
import discord
from discord import Intents
from loguru import logger
from typing import Optional
from datetime import datetime, timezone


class DiscordBotService:
    """Discord bot that forwards messages to SonarBot's LangGraph orchestrator.
    
    Conversation model:
      - Messages inside an existing thread → use that thread as conversation_id.
      - New messages in a channel → auto-create a thread, use thread id.
      - DMs → use DM channel id (no threads in DMs).
    """
    
    def __init__(self):
        self.token: Optional[str] = os.getenv("DISCORD_BOT_TOKEN", "")
        self.bot: Optional[discord.Client] = None
        self._running = False
        self._orchestrator = None
        
    def _get_orchestrator(self):
        """Lazy import to avoid circular imports"""
        if self._orchestrator is None:
            from app.agents.langgraph_orchestrator import langgraph_orchestrator
            self._orchestrator = langgraph_orchestrator
        return self._orchestrator
    
    async def start(self):
        """Start the Discord bot if token is configured"""
        if not self.token:
            logger.info("⏭️ Discord bot skipped (no DISCORD_BOT_TOKEN set)")
            return
        
        intents = Intents.default()
        intents.message_content = True
        
        self.bot = discord.Client(intents=intents)
        
        @self.bot.event
        async def on_ready():
            logger.info(f"🤖 Discord bot connected as {self.bot.user}")
            self._running = True
        
        @self.bot.event
        async def on_message(message: discord.Message):
            # Ignore own messages and other bots
            if message.author == self.bot.user or message.author.bot:
                return
            
            # --- Determine if we should respond ---
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_thread = isinstance(message.channel, discord.Thread)
            is_mentioned = self.bot.user in message.mentions if message.guild else False
            is_bot_channel = (
                hasattr(message.channel, 'name') and
                message.channel.name in ('sonarbot', 'ai-assistant', 'general')
            )
            
            # Always respond in threads we created (our threads)
            is_our_thread = False
            if is_thread and message.channel.owner_id == self.bot.user.id:
                is_our_thread = True
            
            if not is_dm and not is_mentioned and not is_bot_channel and not is_our_thread:
                return
            
            # Strip the bot mention from the message if present
            content = message.content
            if is_mentioned and self.bot.user:
                content = content.replace(f'<@{self.bot.user.id}>', '').strip()
            
            if not content:
                return
            
            logger.info(f"💬 Discord message from {message.author}: {content[:50]}...")
            
            # --- Determine conversation context ---
            user_id = f"discord_{message.author.id}"
            
            # Thread routing: inside a thread → that thread IS the conversation.
            # In a channel → create a new thread for this conversation.
            reply_target = message  # default: reply to the message
            
            if is_thread:
                # Already in a thread — use thread as conversation
                conversation_id = f"discord_thread_{message.channel.id}"
                reply_target = message
            elif is_dm:
                # DMs don't support threads — use DM channel
                conversation_id = f"discord_dm_{message.channel.id}"
                reply_target = message
            else:
                # Channel message → auto-create a thread
                try:
                    thread_name = f"🤖 {content[:40]}{'...' if len(content) > 40 else ''}"
                    thread = await message.create_thread(
                        name=thread_name,
                        auto_archive_duration=60,  # archive after 1 hour inactivity
                    )
                    conversation_id = f"discord_thread_{thread.id}"
                    reply_target = thread  # reply inside the thread
                    logger.info(f"🧵 Created thread '{thread_name}' for {message.author}")
                except discord.Forbidden:
                    # Can't create threads — fall back to channel reply
                    conversation_id = f"discord_{message.channel.id}"
                    reply_target = message
                except Exception as e:
                    logger.warning(f"⚠️ Thread creation failed: {e}")
                    conversation_id = f"discord_{message.channel.id}"
                    reply_target = message
            
            # --- Process the message ---
            async with message.channel.typing():
                try:
                    # Handle slash commands
                    from app.services.slash_command_service import slash_command_service
                    if slash_command_service.is_slash_command(content):
                        result = await slash_command_service.execute(
                            message=content,
                            user_id=user_id,
                            conversation_id=conversation_id
                        )
                        response_text = result.get("response", "Command executed.")
                    else:
                        # Process through LangGraph orchestrator
                        orchestrator = self._get_orchestrator()
                        result = await orchestrator.process(
                            user_message=content,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            max_iterations=3
                        )
                        response_text = result.get("output", "I couldn't generate a response.")
                    
                    # Check for screenshot attachment from virtual desktop
                    screenshot_b64 = None
                    if isinstance(result, dict):
                        meta = result.get('metadata', {}) or {}
                        screenshot_b64 = meta.get('screenshot_base64')
                    
                    # Send response (in thread or DM)
                    for chunk in self._split_message(response_text):
                        if isinstance(reply_target, discord.Thread):
                            await reply_target.send(chunk)
                        else:
                            await reply_target.reply(chunk)
                    
                    # If there's a screenshot, send it as an attachment
                    if screenshot_b64:
                        import base64
                        img_bytes = base64.b64decode(screenshot_b64)
                        file = discord.File(
                            fp=__import__('io').BytesIO(img_bytes),
                            filename="screenshot.png"
                        )
                        if isinstance(reply_target, discord.Thread):
                            await reply_target.send("📸 **Virtual Desktop Screenshot:**", file=file)
                        else:
                            await message.reply("📸 **Virtual Desktop Screenshot:**", file=file)
                    
                except Exception as e:
                    logger.error(f"❌ Discord processing error: {e}")
                    error_msg = f"Sorry, I encountered an error: {str(e)[:200]}"
                    if isinstance(reply_target, discord.Thread):
                        await reply_target.send(error_msg)
                    else:
                        await reply_target.reply(error_msg)
        
        try:
            logger.info("🚀 Starting Discord bot...")
            await self.bot.start(self.token)
        except discord.LoginFailure:
            logger.error("❌ Invalid Discord bot token")
        except Exception as e:
            logger.error(f"❌ Discord bot error: {e}")
    
    async def stop(self):
        """Gracefully stop the Discord bot"""
        if self.bot and self._running:
            logger.info("🛑 Stopping Discord bot...")
            await self.bot.close()
            self._running = False
    
    @staticmethod
    def _split_message(text: str, limit: int = 2000) -> list:
        """Split a long message into chunks respecting Discord's limit"""
        if len(text) <= limit:
            return [text]
        
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Try to split at a newline
            split_at = text.rfind('\n', 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip('\n')
        return chunks
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_configured(self) -> bool:
        return bool(self.token)


# Global instance
discord_bot_service = DiscordBotService()
