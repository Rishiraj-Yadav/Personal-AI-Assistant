"""
Google Calendar Service - Full calendar control: list, create, update, delete events.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from loguru import logger

from googleapiclient.discovery import build

from app.services.google_auth_service import google_auth_service


class CalendarService:
    """Full Google Calendar control per user"""

    def _get_service(self, user_id: str):
        creds = google_auth_service.get_credentials(user_id)
        if not creds:
            raise PermissionError(
                "Google account not connected. "
                "Please connect via Settings → Connect Google Account."
            )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # -------- List / Query --------

    def list_events(
        self,
        user_id: str,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
        calendar_id: str = "primary",
    ) -> List[Dict]:
        """List upcoming events in a time range"""
        service = self._get_service(user_id)

        if not time_min:
            time_min = datetime.now(timezone.utc)
        if not time_max:
            time_max = time_min + timedelta(days=7)

        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        result = []
        for event in events:
            start = event.get("start", {})
            end = event.get("end", {})
            result.append({
                "id": event["id"],
                "summary": event.get("summary", "(no title)"),
                "description": event.get("description", ""),
                "location": event.get("location", ""),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "attendees": [
                    {"email": a["email"], "status": a.get("responseStatus", "")}
                    for a in event.get("attendees", [])
                ],
                "status": event.get("status", ""),
                "html_link": event.get("htmlLink", ""),
                "reminders": event.get("reminders", {}),
            })

        logger.info(f"📅 Listed {len(result)} events for {user_id}")
        return result

    def get_today_events(self, user_id: str) -> List[Dict]:
        """Get all events for today"""
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.list_events(user_id, time_min=start, time_max=end, max_results=50)

    # -------- Create --------

    def create_event(
        self,
        user_id: str,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        reminder_minutes: int = 15,
        calendar_id: str = "primary",
        recurrence: Optional[List[str]] = None,
        time_zone: str = "Asia/Kolkata",
    ) -> Dict:
        """Create a calendar event.
        
        start_time / end_time: ISO 8601 format e.g. '2026-03-10T09:00:00'
        time_zone: IANA timezone e.g. 'Asia/Kolkata', 'America/New_York'
        recurrence: e.g. ['RRULE:FREQ=WEEKLY;COUNT=10']
        """
        service = self._get_service(user_id)

        event_body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_time, "timeZone": time_zone},
            "end": {"dateTime": end_time, "timeZone": time_zone},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": reminder_minutes},
                ],
            },
        }

        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]
        if recurrence:
            event_body["recurrence"] = recurrence

        event = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body)
            .execute()
        )
        logger.info(f"📅 Event created for {user_id}: {summary}")
        return {
            "id": event["id"],
            "summary": event.get("summary", ""),
            "start": event.get("start", {}).get("dateTime", ""),
            "end": event.get("end", {}).get("dateTime", ""),
            "html_link": event.get("htmlLink", ""),
            "status": "created",
        }

    # -------- Update --------

    def update_event(
        self,
        user_id: str,
        event_id: str,
        updates: Dict,
        calendar_id: str = "primary",
    ) -> Dict:
        """Update an existing event. updates can contain: summary, description, location, start, end"""
        service = self._get_service(user_id)

        # Get existing event
        event = (
            service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute()
        )

        # Apply updates
        for key in ["summary", "description", "location"]:
            if key in updates:
                event[key] = updates[key]
        if "start" in updates:
            event["start"] = {"dateTime": updates["start"], "timeZone": updates.get("timeZone", "Asia/Kolkata")}
        if "end" in updates:
            event["end"] = {"dateTime": updates["end"], "timeZone": updates.get("timeZone", "Asia/Kolkata")}

        updated = (
            service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=event)
            .execute()
        )
        logger.info(f"📅 Event updated for {user_id}: {event_id}")
        return {
            "id": updated["id"],
            "summary": updated.get("summary", ""),
            "status": "updated",
        }

    # -------- Delete --------

    def delete_event(
        self,
        user_id: str,
        event_id: str,
        calendar_id: str = "primary",
    ) -> bool:
        """Delete / cancel an event"""
        service = self._get_service(user_id)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info(f"🗑️ Event deleted for {user_id}: {event_id}")
        return True

    # -------- Free/Busy --------

    def check_free_busy(
        self,
        user_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> Dict:
        """Check if user is free or busy in a time range"""
        service = self._get_service(user_id)
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": "primary"}],
        }
        result = service.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get("primary", {}).get("busy", [])
        return {
            "is_free": len(busy) == 0,
            "busy_slots": busy,
        }


calendar_service = CalendarService()
