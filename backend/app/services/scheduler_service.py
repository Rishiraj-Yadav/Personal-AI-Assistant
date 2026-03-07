"""
Scheduler Service - APScheduler-based cron jobs / reminders
Persists jobs to SQLite so they survive restarts.
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

from app.database.base import SessionLocal
from app.database.models import ScheduledJob


class SchedulerService:
    """Manages scheduled jobs (reminders, recurring tasks) with APScheduler"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._callbacks: Dict[str, Callable] = {}
        self._started = False
        logger.info("⏰ Scheduler Service initialized")

    def start(self):
        """Start the scheduler and reload persisted jobs"""
        if self._started:
            return
        self.scheduler.start()
        self._started = True
        self._reload_persisted_jobs()
        logger.info("✅ Scheduler started")

    def shutdown(self):
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False

    def register_callback(self, action_type: str, callback: Callable):
        """Register a callback for a given action type"""
        self._callbacks[action_type] = callback
        logger.info(f"📌 Registered callback: {action_type}")

    # -------- Create Jobs --------

    def add_reminder(
        self,
        user_id: str,
        description: str,
        run_at: datetime,
        action_data: Optional[Dict] = None,
    ) -> Dict:
        """One-time reminder at a specific time"""
        job_id = f"reminder_{uuid.uuid4().hex[:12]}"
        trigger = DateTrigger(run_date=run_at)

        self.scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            kwargs={"job_id": job_id, "user_id": user_id},
            replace_existing=True,
        )

        self._persist_job(
            user_id=user_id,
            job_id=job_id,
            job_type="reminder",
            description=description,
            trigger_type="date",
            trigger_args={"run_date": run_at.isoformat()},
            action_type="notify",
            action_data=action_data or {"message": description},
            next_run=run_at,
        )

        logger.info(f"⏰ Reminder set for {user_id}: '{description}' at {run_at}")
        return {"job_id": job_id, "description": description, "run_at": run_at.isoformat()}

    def add_cron_job(
        self,
        user_id: str,
        description: str,
        action_type: str,
        action_data: Dict,
        cron_args: Dict,
    ) -> Dict:
        """Recurring job with cron schedule.
        
        cron_args: {hour: 9, minute: 0, day_of_week: 'mon-fri'} etc.
        """
        job_id = f"cron_{uuid.uuid4().hex[:12]}"
        trigger = CronTrigger(**cron_args)

        self.scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            kwargs={"job_id": job_id, "user_id": user_id},
            replace_existing=True,
        )

        self._persist_job(
            user_id=user_id,
            job_id=job_id,
            job_type="cron",
            description=description,
            trigger_type="cron",
            trigger_args=cron_args,
            action_type=action_type,
            action_data=action_data,
        )

        logger.info(f"🔄 Cron job added for {user_id}: {description}")
        return {"job_id": job_id, "description": description, "schedule": cron_args}

    def add_interval_job(
        self,
        user_id: str,
        description: str,
        action_type: str,
        action_data: Dict,
        interval_seconds: int,
    ) -> Dict:
        """Recurring job at fixed interval"""
        job_id = f"interval_{uuid.uuid4().hex[:12]}"
        trigger = IntervalTrigger(seconds=interval_seconds)

        self.scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            kwargs={"job_id": job_id, "user_id": user_id},
            replace_existing=True,
        )

        self._persist_job(
            user_id=user_id,
            job_id=job_id,
            job_type="interval",
            description=description,
            trigger_type="interval",
            trigger_args={"seconds": interval_seconds},
            action_type=action_type,
            action_data=action_data,
        )

        logger.info(f"🔄 Interval job added for {user_id}: every {interval_seconds}s")
        return {"job_id": job_id, "description": description, "interval_seconds": interval_seconds}

    # -------- Manage Jobs --------

    def list_jobs(self, user_id: str) -> List[Dict]:
        """List all active jobs for a user"""
        session = SessionLocal()
        try:
            jobs = session.query(ScheduledJob).filter_by(user_id=user_id, is_active=True).all()
            return [
                {
                    "job_id": j.job_id,
                    "type": j.job_type,
                    "description": j.description,
                    "trigger": j.trigger_type,
                    "schedule": j.trigger_args,
                    "action": j.action_type,
                    "next_run": j.next_run.isoformat() if j.next_run else None,
                }
                for j in jobs
            ]
        finally:
            session.close()

    def remove_job(self, user_id: str, job_id: str) -> bool:
        """Remove a scheduled job"""
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass  # may already be gone from scheduler

        session = SessionLocal()
        try:
            job = session.query(ScheduledJob).filter_by(job_id=job_id, user_id=user_id).first()
            if job:
                job.is_active = False
                session.commit()
            logger.info(f"🗑️ Job removed: {job_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error removing job: {e}")
            return False
        finally:
            session.close()

    # -------- Internal --------

    async def _execute_job(self, job_id: str, user_id: str):
        """Dispatcher called by APScheduler when a job fires"""
        session = SessionLocal()
        try:
            job = session.query(ScheduledJob).filter_by(job_id=job_id).first()
            if not job or not job.is_active:
                return

            action_type = job.action_type
            action_data = job.action_data or {}
            action_data["user_id"] = user_id
            action_data["job_id"] = job_id
            action_data["description"] = job.description

            callback = self._callbacks.get(action_type)
            if callback:
                await callback(action_data)
                logger.info(f"✅ Job executed: {job_id} (action={action_type})")
            else:
                logger.warning(f"⚠️ No callback for action type: {action_type}")

            # Deactivate one-time jobs
            if job.trigger_type == "date":
                job.is_active = False
                session.commit()
        except Exception as e:
            logger.error(f"❌ Job execution error ({job_id}): {e}")
        finally:
            session.close()

    def _persist_job(self, **kwargs):
        """Save job to DB for restart persistence"""
        session = SessionLocal()
        try:
            job = ScheduledJob(**kwargs)
            session.add(job)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error persisting job: {e}")
        finally:
            session.close()

    def _reload_persisted_jobs(self):
        """Reload active jobs from DB on startup"""
        session = SessionLocal()
        try:
            jobs = session.query(ScheduledJob).filter_by(is_active=True).all()
            count = 0
            for job in jobs:
                try:
                    if job.trigger_type == "date":
                        run_date = datetime.fromisoformat(job.trigger_args.get("run_date", ""))
                        if run_date < datetime.now(timezone.utc):
                            job.is_active = False
                            continue
                        trigger = DateTrigger(run_date=run_date)
                    elif job.trigger_type == "cron":
                        trigger = CronTrigger(**job.trigger_args)
                    elif job.trigger_type == "interval":
                        trigger = IntervalTrigger(seconds=job.trigger_args.get("seconds", 3600))
                    else:
                        continue

                    self.scheduler.add_job(
                        self._execute_job,
                        trigger=trigger,
                        id=job.job_id,
                        kwargs={"job_id": job.job_id, "user_id": job.user_id},
                        replace_existing=True,
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Could not reload job {job.job_id}: {e}")

            session.commit()
            logger.info(f"🔄 Reloaded {count} scheduled jobs from DB")
        except Exception as e:
            logger.error(f"❌ Error reloading jobs: {e}")
        finally:
            session.close()


scheduler_service = SchedulerService()
