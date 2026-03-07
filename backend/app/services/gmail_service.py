"""
Gmail Service - Full inbox control: read, search, send, draft, label, attachments.
All operations require valid Google OAuth credentials for the user.
"""
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from loguru import logger

from googleapiclient.discovery import build

from app.services.google_auth_service import google_auth_service


class GmailService:
    """Full Gmail inbox control per user"""

    def _get_service(self, user_id: str):
        """Build Gmail API client for a user"""
        creds = google_auth_service.get_credentials(user_id)
        if not creds:
            raise PermissionError(
                "Google account not connected. "
                "Please connect via Settings → Connect Google Account."
            )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    # -------- Read --------

    def list_emails(
        self,
        user_id: str,
        query: str = "",
        max_results: int = 10,
        label: str = "INBOX",
    ) -> List[Dict]:
        """List emails matching an optional Gmail query.
        
        query examples: 'from:alice', 'is:unread', 'subject:invoice after:2026/01/01'
        """
        service = self._get_service(user_id)
        
        # Don't add label filter when query already specifies a location (in:sent, in:trash, etc.)
        use_label = None
        if label and not any(q in (query or '').lower() for q in ['in:', 'label:']):
            use_label = [label]
        
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                labelIds=use_label,
                maxResults=max_results,
            )
            .execute()
        )
        messages = results.get("messages", [])

        emails = []
        for msg_meta in messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="metadata",
                     metadataHeaders=["Subject", "From", "To", "Date"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            emails.append({
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "snippet": msg.get("snippet", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "date": headers.get("Date", ""),
                "labels": msg.get("labelIds", []),
                "is_unread": "UNREAD" in msg.get("labelIds", []),
            })

        logger.info(f"📧 Listed {len(emails)} emails for {user_id} (query='{query}')")
        return emails

    def read_email(self, user_id: str, message_id: str) -> Dict:
        """Read full content of a single email"""
        service = self._get_service(user_id)
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = self._extract_body(msg.get("payload", {}))
        attachments = self._extract_attachments_meta(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "thread_id": msg["threadId"],
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "body": body,
            "labels": msg.get("labelIds", []),
            "attachments": attachments,
        }

    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread emails"""
        service = self._get_service(user_id)
        results = (
            service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=1)
            .execute()
        )
        return results.get("resultSizeEstimate", 0)

    # -------- Compose (draft only — requires confirmation) --------

    def compose_draft(
        self,
        user_id: str,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        is_html: bool = False,
    ) -> Dict:
        """Create a draft email (NOT sent). Returns draft ID for later send."""
        service = self._get_service(user_id)

        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        mime_type = "html" if is_html else "plain"
        message.attach(MIMEText(body, mime_type))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
        logger.info(f"📝 Draft created for {user_id}: to={to}, subject={subject}")
        return {
            "draft_id": draft["id"],
            "message_id": draft["message"]["id"],
            "to": to,
            "subject": subject,
            "body_preview": body[:200],
            "status": "draft",
        }

    def send_draft(self, user_id: str, draft_id: str) -> Dict:
        """Send a previously created draft (called after user confirms)"""
        service = self._get_service(user_id)
        sent = (
            service.users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )
        logger.info(f"✅ Draft {draft_id} sent for user {user_id}")
        return {
            "message_id": sent["id"],
            "thread_id": sent["threadId"],
            "status": "sent",
        }

    def send_email_direct(
        self,
        user_id: str,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        is_html: bool = False,
    ) -> Dict:
        """Send email directly (use only after explicit user confirmation)"""
        service = self._get_service(user_id)

        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        mime_type = "html" if is_html else "plain"
        message.attach(MIMEText(body, mime_type))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        logger.info(f"📤 Email sent for {user_id}: to={to}, subject={subject}")
        return {
            "message_id": sent["id"],
            "thread_id": sent["threadId"],
            "status": "sent",
        }

    # -------- Labels & Actions --------

    def mark_as_read(self, user_id: str, message_id: str) -> bool:
        service = self._get_service(user_id)
        service.users().messages().modify(
            userId="me", id=message_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return True

    def mark_as_unread(self, user_id: str, message_id: str) -> bool:
        service = self._get_service(user_id)
        service.users().messages().modify(
            userId="me", id=message_id,
            body={"addLabelIds": ["UNREAD"]}
        ).execute()
        return True

    def archive_email(self, user_id: str, message_id: str) -> bool:
        service = self._get_service(user_id)
        service.users().messages().modify(
            userId="me", id=message_id,
            body={"removeLabelIds": ["INBOX"]}
        ).execute()
        return True

    def trash_email(self, user_id: str, message_id: str) -> bool:
        service = self._get_service(user_id)
        service.users().messages().trash(userId="me", id=message_id).execute()
        return True

    def list_labels(self, user_id: str) -> List[Dict]:
        service = self._get_service(user_id)
        results = service.users().labels().list(userId="me").execute()
        return [
            {"id": lbl["id"], "name": lbl["name"], "type": lbl.get("type", "")}
            for lbl in results.get("labels", [])
        ]

    # -------- Search --------

    def search_emails(
        self,
        user_id: str,
        query: str,
        max_results: int = 10,
    ) -> List[Dict]:
        """Search emails using Gmail query syntax"""
        return self.list_emails(user_id, query=query, max_results=max_results, label="")

    # -------- Internals --------

    def _extract_body(self, payload: Dict) -> str:
        """Extract text body from message payload"""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Fallback to HTML
        for part in parts:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        # Nested multipart
        for part in parts:
            body = self._extract_body(part)
            if body:
                return body
        return ""

    def _extract_attachments_meta(self, payload: Dict) -> List[Dict]:
        """Return metadata of attachments (not content)"""
        attachments = []
        for part in payload.get("parts", []):
            if part.get("filename"):
                attachments.append({
                    "filename": part["filename"],
                    "mime_type": part.get("mimeType", ""),
                    "size": part.get("body", {}).get("size", 0),
                })
            # Nested
            attachments.extend(self._extract_attachments_meta(part))
        return attachments


gmail_service = GmailService()
