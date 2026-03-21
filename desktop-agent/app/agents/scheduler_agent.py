"""
Scheduler Agent — Timed tasks, reminders, recurring automation
"""
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from loguru import logger
from agents.base_agent import BaseAgent
from config import settings

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.warning("apscheduler not installed — scheduling unavailable")


class SchedulerAgent(BaseAgent):
    """Agent for scheduling tasks, reminders, and recurring automation"""

    def __init__(self):
        super().__init__(
            name="scheduler_agent",
            description="Schedule tasks for later — reminders, recurring jobs, delayed execution",
        )
        self._tasks: Dict[str, Dict] = {}
        self._scheduler = None
        self._data_file = settings.SCHEDULER_DATA_FILE

        if HAS_APSCHEDULER:
            self._scheduler = BackgroundScheduler()
            self._scheduler.start()
            logger.info("⏰ Scheduler started")

        self._load_tasks()

    def _load_tasks(self):
        """Load persisted tasks from file"""
        try:
            if os.path.exists(self._data_file):
                with open(self._data_file, "r") as f:
                    self._tasks = json.load(f)
                logger.info(f"Loaded {len(self._tasks)} scheduled tasks")
        except Exception as e:
            logger.warning(f"Failed to load scheduled tasks: {e}")

    def _save_tasks(self):
        """Persist tasks to file"""
        try:
            os.makedirs(os.path.dirname(self._data_file), exist_ok=True)
            with open(self._data_file, "w") as f:
                json.dump(self._tasks, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save scheduled tasks: {e}")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "schedule_reminder",
                "description": "Set a reminder for a specific time or after a delay. Will send a desktop notification when triggered.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Reminder message",
                        },
                        "delay_minutes": {
                            "type": "integer",
                            "description": "Minutes from now to trigger the reminder",
                        },
                        "at_time": {
                            "type": "string",
                            "description": "Specific time in HH:MM format (24h). Overrides delay_minutes.",
                        },
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "schedule_recurring",
                "description": "Schedule a recurring task. Will send a notification at each occurrence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Task description / reminder message",
                        },
                        "interval_minutes": {
                            "type": "integer",
                            "description": "Repeat every N minutes",
                        },
                        "cron_expression": {
                            "type": "string",
                            "description": "Cron expression (e.g., '0 9 * * *' for 9 AM daily). Overrides interval.",
                        },
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "list_scheduled_tasks",
                "description": "List all scheduled tasks and reminders",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "cancel_scheduled_task",
                "description": "Cancel a scheduled task by its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "ID of the task to cancel",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "schedule_reminder": lambda: self._schedule_reminder(
                args.get("message", ""),
                args.get("delay_minutes"),
                args.get("at_time"),
            ),
            "schedule_recurring": lambda: self._schedule_recurring(
                args.get("message", ""),
                args.get("interval_minutes"),
                args.get("cron_expression"),
            ),
            "list_scheduled_tasks": lambda: self._list_tasks(),
            "cancel_scheduled_task": lambda: self._cancel_task(
                args.get("task_id", "")
            ),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    def _trigger_notification(self, task_id: str, message: str):
        """Called when a scheduled task fires"""
        logger.info(f"⏰ Triggered: {message}")
        try:
            from agents.notification_agent import notification_agent
            notification_agent.execute("send_notification", {
                "title": "⏰ Reminder",
                "message": message,
                "urgency": "warning",
            })
        except Exception as e:
            logger.error(f"Notification trigger failed: {e}")

        # Update task status
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task["last_triggered"] = datetime.now().isoformat()
            if task["type"] == "one_shot":
                task["status"] = "completed"
            self._save_tasks()

    def _schedule_reminder(
        self,
        message: str,
        delay_minutes: Optional[int] = None,
        at_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not message:
            return self._error("No reminder message provided")

        if not HAS_APSCHEDULER:
            return self._error("apscheduler not installed. Run: pip install apscheduler")

        task_id = str(uuid.uuid4())[:8]

        if at_time:
            # Parse HH:MM time
            try:
                hour, minute = map(int, at_time.split(":"))
                trigger_time = datetime.now().replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                if trigger_time <= datetime.now():
                    trigger_time += timedelta(days=1)
            except Exception:
                return self._error(f"Invalid time format: {at_time}. Use HH:MM (24h)")
        elif delay_minutes:
            trigger_time = datetime.now() + timedelta(minutes=delay_minutes)
        else:
            # Default: 5 minutes
            delay_minutes = 5
            trigger_time = datetime.now() + timedelta(minutes=5)

        try:
            self._scheduler.add_job(
                self._trigger_notification,
                DateTrigger(run_date=trigger_time),
                args=[task_id, message],
                id=task_id,
            )

            task_info = {
                "id": task_id,
                "type": "one_shot",
                "message": message,
                "trigger_time": trigger_time.isoformat(),
                "created": datetime.now().isoformat(),
                "status": "scheduled",
            }
            self._tasks[task_id] = task_info
            self._save_tasks()

            return self._success(
                task_info,
                f"Reminder set for {trigger_time.strftime('%I:%M %p')}: {message}",
            )
        except Exception as e:
            return self._error(f"Failed to schedule reminder: {e}")

    def _schedule_recurring(
        self,
        message: str,
        interval_minutes: Optional[int] = None,
        cron_expression: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not message:
            return self._error("No task message provided")

        if not HAS_APSCHEDULER:
            return self._error("apscheduler not installed")

        task_id = str(uuid.uuid4())[:8]

        try:
            if cron_expression:
                parts = cron_expression.split()
                if len(parts) >= 5:
                    trigger = CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4],
                    )
                    schedule_desc = f"cron: {cron_expression}"
                else:
                    return self._error("Invalid cron expression. Use: min hour day month weekday")
            elif interval_minutes:
                trigger = IntervalTrigger(minutes=interval_minutes)
                schedule_desc = f"every {interval_minutes} minutes"
            else:
                return self._error("Provide interval_minutes or cron_expression")

            self._scheduler.add_job(
                self._trigger_notification,
                trigger,
                args=[task_id, message],
                id=task_id,
            )

            task_info = {
                "id": task_id,
                "type": "recurring",
                "message": message,
                "schedule": schedule_desc,
                "created": datetime.now().isoformat(),
                "status": "active",
            }
            self._tasks[task_id] = task_info
            self._save_tasks()

            return self._success(
                task_info,
                f"Recurring task scheduled ({schedule_desc}): {message}",
            )
        except Exception as e:
            return self._error(f"Failed to schedule recurring task: {e}")

    def _list_tasks(self) -> Dict[str, Any]:
        tasks = list(self._tasks.values())
        active = [t for t in tasks if t.get("status") in ("scheduled", "active")]
        return self._success(
            {"tasks": tasks, "active_count": len(active), "total_count": len(tasks)},
            f"{len(active)} active scheduled tasks",
        )

    def _cancel_task(self, task_id: str) -> Dict[str, Any]:
        if task_id not in self._tasks:
            return self._error(f"Task not found: {task_id}")

        try:
            if self._scheduler:
                self._scheduler.remove_job(task_id)
        except Exception:
            pass

        self._tasks[task_id]["status"] = "cancelled"
        self._save_tasks()

        return self._success(
            {"cancelled": task_id},
            f"Cancelled task: {task_id}",
        )


# Global instance
scheduler_agent = SchedulerAgent()

