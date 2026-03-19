"""
Notification Agent — Windows toast notifications and text-to-speech
"""
import os
import subprocess
from typing import Dict, Any, List
from datetime import datetime
from loguru import logger
from agents.base_agent import BaseAgent

try:
    from winotify import Notification, audio
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False

try:
    import pyttsx3
    HAS_TTS = True
except ImportError:
    HAS_TTS = False


class NotificationAgent(BaseAgent):
    """Agent for desktop notifications and text-to-speech"""

    def __init__(self):
        super().__init__(
            name="notification_agent",
            description="Send Windows toast notifications, speak text aloud, play sounds",
        )
        self._notification_history: List[Dict] = []
        self._tts_engine = None

    def _get_tts(self):
        """Lazy init TTS engine"""
        if self._tts_engine is None and HAS_TTS:
            try:
                self._tts_engine = pyttsx3.init()
                self._tts_engine.setProperty("rate", 175)
                self._tts_engine.setProperty("volume", 0.9)
            except Exception as e:
                logger.warning(f"TTS init failed: {e}")
        return self._tts_engine

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "send_notification",
                "description": "Send a Windows desktop toast notification with title and message",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Notification title",
                        },
                        "message": {
                            "type": "string",
                            "description": "Notification body text",
                        },
                        "urgency": {
                            "type": "string",
                            "description": "Urgency level: 'info', 'warning', or 'urgent' (default: info)",
                            "enum": ["info", "warning", "urgent"],
                        },
                    },
                    "required": ["title", "message"],
                },
            },
            {
                "name": "speak_text",
                "description": "Speak text aloud using text-to-speech. The computer will say the text out loud.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to speak aloud",
                        },
                        "rate": {
                            "type": "integer",
                            "description": "Speech rate (100=slow, 175=normal, 250=fast)",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "play_sound",
                "description": "Play a system beep or notification sound",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sound_type": {
                            "type": "string",
                            "description": "Type of sound: 'beep', 'success', 'warning', 'error'",
                            "enum": ["beep", "success", "warning", "error"],
                        },
                    },
                },
            },
            {
                "name": "get_notification_history",
                "description": "Get the history of notifications sent in this session",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "send_notification": lambda: self._notify(
                args.get("title", "Desktop Agent"),
                args.get("message", ""),
                args.get("urgency", "info"),
            ),
            "speak_text": lambda: self._speak(
                args.get("text", ""),
                args.get("rate", 175),
            ),
            "play_sound": lambda: self._play_sound(
                args.get("sound_type", "beep"),
            ),
            "get_notification_history": lambda: self._get_history(),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    def _notify(
        self, title: str, message: str, urgency: str = "info"
    ) -> Dict[str, Any]:
        """Send a Windows toast notification"""
        # Record in history
        entry = {
            "title": title,
            "message": message,
            "urgency": urgency,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._notification_history.append(entry)

        if HAS_WINOTIFY:
            try:
                toast = Notification(
                    app_id="Desktop Agent",
                    title=title,
                    msg=message,
                    duration="short" if urgency != "urgent" else "long",
                )

                # Set sound based on urgency
                if urgency == "warning":
                    toast.set_audio(audio.IM, loop=False)
                elif urgency == "urgent":
                    toast.set_audio(audio.Reminder, loop=False)
                else:
                    toast.set_audio(audio.Default, loop=False)

                toast.show()

                # If urgent, also speak it
                if urgency == "urgent":
                    self._speak(f"{title}. {message}", 175)

                return self._success(
                    entry, f"Notification sent: {title}"
                )
            except Exception as e:
                logger.warning(f"winotify failed: {e}, using PowerShell fallback")

        # Fallback: PowerShell toast
        try:
            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
            $template = '<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{message}</text></binding></visual></toast>'
            $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
            $xml.LoadXml($template)
            $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Desktop Agent").Show($toast)
            """
            subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True, timeout=10,
            )
            return self._success(entry, f"Notification sent: {title}")
        except Exception as e:
            return self._error(f"Notification failed: {e}")

    def _speak(self, text: str, rate: int = 175) -> Dict[str, Any]:
        """Speak text aloud using TTS"""
        if not text:
            return self._error("No text to speak")

        engine = self._get_tts()
        if engine:
            try:
                engine.setProperty("rate", rate)
                engine.say(text)
                engine.runAndWait()
                return self._success(
                    {"spoken": text[:100], "rate": rate},
                    f"Spoke: {text[:50]}...",
                )
            except Exception as e:
                logger.warning(f"pyttsx3 failed: {e}, trying PowerShell")

        # Fallback: PowerShell SAPI
        try:
            escaped = text.replace("'", "''")
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f"Add-Type -AssemblyName System.Speech; "
                    f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.Rate = {max(-10, min(10, (rate - 175) // 25))}; "
                    f"$s.Speak('{escaped}')",
                ],
                capture_output=True,
                timeout=30,
            )
            return self._success(
                {"spoken": text[:100], "method": "powershell_sapi"},
                f"Spoke: {text[:50]}...",
            )
        except Exception as e:
            return self._error(f"TTS failed: {e}")

    def _play_sound(self, sound_type: str = "beep") -> Dict[str, Any]:
        """Play a system sound"""
        try:
            if sound_type == "beep":
                import winsound
                winsound.Beep(800, 300)
            elif sound_type == "success":
                import winsound
                winsound.Beep(600, 150)
                winsound.Beep(800, 150)
                winsound.Beep(1000, 200)
            elif sound_type == "warning":
                import winsound
                winsound.Beep(500, 500)
            elif sound_type == "error":
                import winsound
                winsound.Beep(300, 500)
                winsound.Beep(200, 500)
            return self._success(
                {"sound": sound_type}, f"Played {sound_type} sound"
            )
        except Exception as e:
            return self._error(f"Sound failed: {e}")

    def _get_history(self) -> Dict[str, Any]:
        return self._success(
            {
                "notifications": self._notification_history[-20:],
                "count": len(self._notification_history),
            },
            f"{len(self._notification_history)} notifications in history",
        )


# Global instance
notification_agent = NotificationAgent()
