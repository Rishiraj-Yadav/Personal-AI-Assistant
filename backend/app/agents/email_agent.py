"""
Email Agent — Send, read, and search emails via Gmail API or SMTP fallback.

Supports:
- Gmail API (OAuth2) for full inbox access
- SMTP fallback for send-only (uses app passwords)
"""
import os
import asyncio
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import base64
    GMAIL_API_AVAILABLE = True
except ImportError:
    GMAIL_API_AVAILABLE = False
    logger.info("Gmail API libraries not installed — SMTP fallback only")


class EmailAgent:
    """
    Email Agent — handles send, read, search, and reply.
    
    Configuration via environment variables:
    - EMAIL_ADDRESS: Your email address
    - EMAIL_APP_PASSWORD: App password for SMTP (Gmail: generate at myaccount.google.com)
    - GMAIL_CREDENTIALS_FILE: Path to OAuth2 credentials.json (for full Gmail API)
    """

    GMAIL_SCOPES = ["https://mail.google.com/"]
    TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "gmail_token.json")

    def __init__(self):
        self.email_address = os.getenv("EMAIL_ADDRESS", "")
        self.app_password = os.getenv("EMAIL_APP_PASSWORD", "")
        self.credentials_file = os.getenv("GMAIL_CREDENTIALS_FILE", "")
        self.gmail_service = None
        self._init_gmail()
        logger.info(f"✅ Email Agent initialized (address: {self.email_address or 'not configured'})")

    def _init_gmail(self):
        """Initialize Gmail API if credentials are available."""
        if not GMAIL_API_AVAILABLE or not self.credentials_file:
            return

        try:
            creds = None
            if os.path.exists(self.TOKEN_FILE):
                creds = Credentials.from_authorized_user_file(self.TOKEN_FILE, self.GMAIL_SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                elif os.path.exists(self.credentials_file):
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.GMAIL_SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                    # Save for next time
                    os.makedirs(os.path.dirname(self.TOKEN_FILE), exist_ok=True)
                    with open(self.TOKEN_FILE, "w") as f:
                        f.write(creds.to_json())

            if creds:
                self.gmail_service = build("gmail", "v1", credentials=creds)
                logger.info("Gmail API authenticated successfully")
        except Exception as e:
            logger.warning(f"Gmail API init failed: {e}. Using SMTP fallback.")

    async def execute(self, action: str, params: Dict[str, Any] = None, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Route to the correct email action."""
        params = params or {}
        context = context or {}

        action_map = {
            "send": self._send_email,
            "read": self._read_inbox,
            "search": self._search_emails,
            "reply": self._reply,
        }

        handler = action_map.get(action)
        if not handler:
            return {"success": False, "error": f"Unknown email action: {action}"}

        if not self.email_address:
            return {
                "success": False,
                "error": "Email not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env",
            }

        try:
            return await handler(params, context)
        except Exception as e:
            logger.error(f"❌ Email Agent error ({action}): {e}")
            return {"success": False, "error": str(e)}

    async def _send_email(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Send an email."""
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        html = params.get("html", False)

        if not to:
            return {"success": False, "error": "No recipient specified (use 'to' param)"}
        if not subject and not body:
            return {"success": False, "error": "No subject or body specified"}

        # Try Gmail API first
        if self.gmail_service:
            return await self._send_via_gmail_api(to, subject, body, html)

        # Fallback to SMTP
        if self.app_password:
            return await self._send_via_smtp(to, subject, body, html)

        return {"success": False, "error": "No email credentials configured (need Gmail API or SMTP app password)"}

    async def _send_via_smtp(self, to: str, subject: str, body: str, html: bool = False) -> Dict[str, Any]:
        """Send via SMTP (Gmail)."""
        msg = MIMEMultipart("alternative")
        msg["From"] = self.email_address
        msg["To"] = to
        msg["Subject"] = subject

        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type))

        def _send():
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.email_address, self.app_password)
                server.send_message(msg)

        await asyncio.to_thread(_send)

        return {
            "success": True,
            "action": "send",
            "to": to,
            "subject": subject,
            "method": "smtp",
            "message": f"Email sent to {to}",
        }

    async def _send_via_gmail_api(self, to: str, subject: str, body: str, html: bool = False) -> Dict[str, Any]:
        """Send via Gmail API."""
        msg = MIMEMultipart("alternative")
        msg["From"] = self.email_address
        msg["To"] = to
        msg["Subject"] = subject

        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        def _send():
            self.gmail_service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

        await asyncio.to_thread(_send)

        return {
            "success": True,
            "action": "send",
            "to": to,
            "subject": subject,
            "method": "gmail_api",
            "message": f"Email sent to {to}",
        }

    async def _read_inbox(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Read recent inbox emails."""
        count = params.get("count", 10)

        if not self.gmail_service:
            return {"success": False, "error": "Gmail API not configured for reading inbox"}

        def _fetch():
            results = self.gmail_service.users().messages().list(
                userId="me", labelIds=["INBOX"], maxResults=count
            ).execute()

            messages = []
            for msg_summary in results.get("messages", []):
                msg = self.gmail_service.users().messages().get(
                    userId="me", id=msg_summary["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                messages.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                })

            return messages

        emails = await asyncio.to_thread(_fetch)

        return {
            "success": True,
            "action": "read",
            "count": len(emails),
            "emails": emails,
        }

    async def _search_emails(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Search emails using Gmail query syntax."""
        query = params.get("query", "")
        count = params.get("count", 10)

        if not query:
            return {"success": False, "error": "No search query specified"}
        if not self.gmail_service:
            return {"success": False, "error": "Gmail API not configured for search"}

        def _search():
            results = self.gmail_service.users().messages().list(
                userId="me", q=query, maxResults=count
            ).execute()

            messages = []
            for msg_summary in results.get("messages", []):
                msg = self.gmail_service.users().messages().get(
                    userId="me", id=msg_summary["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                messages.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                })

            return messages

        emails = await asyncio.to_thread(_search)

        return {
            "success": True,
            "action": "search",
            "query": query,
            "count": len(emails),
            "emails": emails,
        }

    async def _reply(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Reply to an email by message ID."""
        message_id = params.get("message_id", "")
        body = params.get("body", "")

        if not message_id or not body:
            return {"success": False, "error": "Need message_id and body to reply"}
        if not self.gmail_service:
            return {"success": False, "error": "Gmail API not configured for reply"}

        def _do_reply():
            # Fetch original message
            original = self.gmail_service.users().messages().get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["From", "Subject", "Message-ID"]
            ).execute()

            headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
            to = headers.get("From", "")
            subject = headers.get("Subject", "")
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            msg = MIMEText(body)
            msg["From"] = self.email_address
            msg["To"] = to
            msg["Subject"] = subject
            msg["In-Reply-To"] = headers.get("Message-ID", "")
            msg["References"] = headers.get("Message-ID", "")

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            self.gmail_service.users().messages().send(
                userId="me",
                body={"raw": raw, "threadId": original.get("threadId")}
            ).execute()

            return to, subject

        to, subject = await asyncio.to_thread(_do_reply)

        return {
            "success": True,
            "action": "reply",
            "to": to,
            "subject": subject,
            "message": f"Replied to {to}",
        }


# Global instance
email_agent = EmailAgent()
