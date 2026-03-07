"""
API Routes for Google OAuth, Gmail, Calendar, and Scheduler
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from loguru import logger

from app.services.google_auth_service import google_auth_service
from app.services.gmail_service import gmail_service
from app.services.calendar_service import calendar_service
from app.services.scheduler_service import scheduler_service

router = APIRouter()


# ============ Pydantic Models ============

class GoogleConnectResponse(BaseModel):
    auth_url: str


class GoogleStatusResponse(BaseModel):
    connected: bool
    user_id: str


class EmailListRequest(BaseModel):
    user_id: str
    query: str = ""
    max_results: int = 10
    label: str = "INBOX"


class ComposeEmailRequest(BaseModel):
    user_id: str
    to: str
    subject: str
    body: str
    cc: str = ""
    bcc: str = ""
    is_html: bool = False


class SendDraftRequest(BaseModel):
    user_id: str
    draft_id: str


class ConfirmSendRequest(BaseModel):
    user_id: str
    to: str
    subject: str
    body: str
    cc: str = ""
    bcc: str = ""
    is_html: bool = False
    confirmed: bool = False  # Must be True to actually send


class EmailActionRequest(BaseModel):
    user_id: str
    message_id: str


class CreateEventRequest(BaseModel):
    user_id: str
    summary: str
    start_time: str
    end_time: str
    description: str = ""
    location: str = ""
    attendees: Optional[List[str]] = None
    reminder_minutes: int = 15
    recurrence: Optional[List[str]] = None


class UpdateEventRequest(BaseModel):
    user_id: str
    event_id: str
    updates: Dict[str, Any]


class DeleteEventRequest(BaseModel):
    user_id: str
    event_id: str


class ReminderRequest(BaseModel):
    user_id: str
    description: str
    run_at: str  # ISO format datetime


class CronJobRequest(BaseModel):
    user_id: str
    description: str
    action_type: str
    action_data: Dict[str, Any] = {}
    cron_args: Dict[str, Any]  # {hour: 9, minute: 0, day_of_week: 'mon-fri'}


class RemoveJobRequest(BaseModel):
    user_id: str
    job_id: str


class DisconnectRequest(BaseModel):
    user_id: str


# ============ Google OAuth Routes ============

@router.get("/google/connect")
async def google_connect(user_id: str = Query(...)):
    """Start Google OAuth flow — redirects to Google consent screen"""
    try:
        auth_url = google_auth_service.get_auth_url(user_id)
        return {"auth_url": auth_url}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/google/callback")
async def google_callback(code: str = Query(...), state: str = Query("")):
    """OAuth callback from Google. state = user_id"""
    try:
        user_id = state
        if not user_id:
            raise HTTPException(status_code=400, detail="Missing user_id in state")
        google_auth_service.handle_callback(code, user_id)
        # Redirect to frontend with success
        return RedirectResponse(url="http://localhost:3000?google_connected=true")
    except Exception as e:
        logger.error(f"❌ Google callback error: {e}")
        return RedirectResponse(url=f"http://localhost:3000?google_error={str(e)}")


@router.get("/google/status")
async def google_status(user_id: str = Query(...)):
    """Check if user has connected Google"""
    connected = google_auth_service.is_connected(user_id)
    return {"connected": connected, "user_id": user_id}


@router.post("/google/disconnect")
async def google_disconnect(request: DisconnectRequest):
    """Disconnect Google account"""
    google_auth_service.disconnect(request.user_id)
    return {"disconnected": True, "user_id": request.user_id}


# ============ Gmail Routes ============

@router.post("/gmail/list")
async def list_emails(req: EmailListRequest):
    """List emails from inbox"""
    try:
        emails = gmail_service.list_emails(
            user_id=req.user_id,
            query=req.query,
            max_results=req.max_results,
            label=req.label,
        )
        return {"emails": emails, "count": len(emails)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/read/{message_id}")
async def read_email(message_id: str, user_id: str = Query(...)):
    """Read a single email in full"""
    try:
        email = gmail_service.read_email(user_id, message_id)
        return email
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/gmail/unread-count")
async def unread_count(user_id: str = Query(...)):
    """Get unread email count"""
    try:
        count = gmail_service.get_unread_count(user_id)
        return {"unread_count": count}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/compose")
async def compose_email(req: ComposeEmailRequest):
    """Compose an email as DRAFT (not sent yet). Returns draft_id for confirmation."""
    try:
        draft = gmail_service.compose_draft(
            user_id=req.user_id,
            to=req.to,
            subject=req.subject,
            body=req.body,
            cc=req.cc,
            bcc=req.bcc,
            is_html=req.is_html,
        )
        return {
            **draft,
            "confirmation_required": True,
            "message": f"📝 Draft created. Email to {req.to} about '{req.subject}' is ready. Please confirm to send.",
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/send-draft")
async def send_draft(req: SendDraftRequest):
    """Send a previously created draft (after user confirmation)"""
    try:
        result = gmail_service.send_draft(req.user_id, req.draft_id)
        return {**result, "message": "✅ Email sent successfully!"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/send")
async def send_email_confirmed(req: ConfirmSendRequest):
    """Send email only if confirmed=True. Otherwise returns preview."""
    if not req.confirmed:
        return {
            "status": "pending_confirmation",
            "preview": {
                "to": req.to,
                "subject": req.subject,
                "body_preview": req.body[:300],
                "cc": req.cc,
                "bcc": req.bcc,
            },
            "message": (
                f"📧 Ready to send email:\n"
                f"  To: {req.to}\n"
                f"  Subject: {req.subject}\n"
                f"  Body: {req.body[:100]}...\n\n"
                f"Please confirm to send this email."
            ),
        }
    try:
        result = gmail_service.send_email_direct(
            user_id=req.user_id,
            to=req.to,
            subject=req.subject,
            body=req.body,
            cc=req.cc,
            bcc=req.bcc,
            is_html=req.is_html,
        )
        return {**result, "message": "✅ Email sent successfully!"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/mark-read")
async def mark_read(req: EmailActionRequest):
    try:
        gmail_service.mark_as_read(req.user_id, req.message_id)
        return {"success": True}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/archive")
async def archive_email(req: EmailActionRequest):
    try:
        gmail_service.archive_email(req.user_id, req.message_id)
        return {"success": True}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/trash")
async def trash_email(req: EmailActionRequest):
    try:
        gmail_service.trash_email(req.user_id, req.message_id)
        return {"success": True}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/gmail/search")
async def search_emails(req: EmailListRequest):
    """Search emails with Gmail query syntax"""
    try:
        emails = gmail_service.search_emails(req.user_id, req.query, req.max_results)
        return {"emails": emails, "count": len(emails)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ============ Calendar Routes ============

@router.get("/calendar/events")
async def list_events(
    user_id: str = Query(...),
    days: int = Query(7, ge=1, le=90),
    max_results: int = Query(20, ge=1, le=100),
):
    """List upcoming events for next N days"""
    try:
        now = datetime.now(timezone.utc)
        events = calendar_service.list_events(
            user_id=user_id,
            time_min=now,
            time_max=now + timedelta(days=days),
            max_results=max_results,
        )
        return {"events": events, "count": len(events)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/calendar/today")
async def today_events(user_id: str = Query(...)):
    """Get today's events"""
    try:
        events = calendar_service.get_today_events(user_id)
        return {"events": events, "count": len(events)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/calendar/create")
async def create_event(req: CreateEventRequest):
    """Create a calendar event"""
    try:
        event = calendar_service.create_event(
            user_id=req.user_id,
            summary=req.summary,
            start_time=req.start_time,
            end_time=req.end_time,
            description=req.description,
            location=req.location,
            attendees=req.attendees,
            reminder_minutes=req.reminder_minutes,
            recurrence=req.recurrence,
        )
        return event
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/calendar/update")
async def update_event(req: UpdateEventRequest):
    try:
        result = calendar_service.update_event(
            user_id=req.user_id,
            event_id=req.event_id,
            updates=req.updates,
        )
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/calendar/delete")
async def delete_event(req: DeleteEventRequest):
    try:
        calendar_service.delete_event(req.user_id, req.event_id)
        return {"deleted": True}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ============ Scheduler Routes ============

@router.post("/scheduler/reminder")
async def add_reminder(req: ReminderRequest):
    """Set a one-time reminder"""
    try:
        run_at = datetime.fromisoformat(req.run_at)
        result = scheduler_service.add_reminder(
            user_id=req.user_id,
            description=req.description,
            run_at=run_at,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/cron")
async def add_cron(req: CronJobRequest):
    """Add a recurring cron job"""
    try:
        result = scheduler_service.add_cron_job(
            user_id=req.user_id,
            description=req.description,
            action_type=req.action_type,
            action_data=req.action_data,
            cron_args=req.cron_args,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/jobs")
async def list_jobs(user_id: str = Query(...)):
    """List all scheduled jobs for a user"""
    jobs = scheduler_service.list_jobs(user_id)
    return {"jobs": jobs, "count": len(jobs)}


@router.post("/scheduler/remove")
async def remove_job(req: RemoveJobRequest):
    """Remove a scheduled job"""
    scheduler_service.remove_job(req.user_id, req.job_id)
    return {"removed": True}
