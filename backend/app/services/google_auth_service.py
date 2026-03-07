"""
Google OAuth Service - Manages OAuth 2.0 flow for Gmail + Calendar
Stores tokens per user in SQLite, refreshes automatically.
"""
import os
from datetime import datetime, timezone
from typing import Optional, Dict
from loguru import logger

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.database.base import SessionLocal
from app.database.models import GoogleOAuthToken

# Scopes for Gmail + Calendar
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleAuthService:
    """Handles Google OAuth flow and token management per user"""

    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://localhost:8000/api/v1/auth/google/callback"
        )
        # Store PKCE code_verifier per user during OAuth flow
        self._pending_verifiers: Dict[str, str] = {}

    def _get_client_config(self) -> Dict:
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.redirect_uri],
            }
        }

    # -------- OAuth flow --------

    def get_auth_url(self, user_id: str) -> str:
        """Generate Google OAuth consent URL"""
        if not self.client_id or not self.client_secret:
            raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")

        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=GOOGLE_SCOPES,
            redirect_uri=self.redirect_uri,
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=user_id,  # pass user_id through state
            include_granted_scopes="true",
        )
        # Store the PKCE code_verifier so handle_callback can use it
        if hasattr(flow, 'code_verifier') and flow.code_verifier:
            self._pending_verifiers[user_id] = flow.code_verifier
        
        logger.info(f"🔗 Generated Google auth URL for user {user_id}")
        return auth_url

    def handle_callback(self, code: str, user_id: str) -> bool:
        """Exchange authorization code for tokens and save them"""
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=GOOGLE_SCOPES,
            redirect_uri=self.redirect_uri,
        )
        # Restore the PKCE code_verifier from the auth URL step
        code_verifier = self._pending_verifiers.pop(user_id, None)
        if code_verifier:
            flow.code_verifier = code_verifier
        
        flow.fetch_token(code=code)
        creds = flow.credentials

        self._save_token(user_id, creds)
        logger.info(f"✅ Google tokens saved for user {user_id}")
        return True

    # -------- Token management --------

    def get_credentials(self, user_id: str) -> Optional[Credentials]:
        """Load credentials for a user, refreshing if expired"""
        session = SessionLocal()
        try:
            row = (
                session.query(GoogleOAuthToken)
                .filter_by(user_id=user_id)
                .first()
            )
            if not row:
                return None

            creds = Credentials(
                token=row.access_token,
                refresh_token=row.refresh_token,
                token_uri=row.token_uri or "https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=row.scopes,
            )

            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                self._save_token(user_id, creds)
                logger.info(f"🔄 Refreshed Google token for {user_id}")

            return creds
        except Exception as e:
            logger.error(f"❌ Error loading Google credentials: {e}")
            return None
        finally:
            session.close()

    def is_connected(self, user_id: str) -> bool:
        """Check if user has valid Google OAuth tokens"""
        creds = self.get_credentials(user_id)
        return creds is not None and creds.valid

    def disconnect(self, user_id: str) -> bool:
        """Remove user's Google OAuth tokens"""
        session = SessionLocal()
        try:
            session.query(GoogleOAuthToken).filter_by(user_id=user_id).delete()
            session.commit()
            logger.info(f"🔌 Disconnected Google for user {user_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error disconnecting: {e}")
            return False
        finally:
            session.close()

    def _save_token(self, user_id: str, creds: Credentials):
        """Upsert token in DB"""
        session = SessionLocal()
        try:
            row = (
                session.query(GoogleOAuthToken)
                .filter_by(user_id=user_id)
                .first()
            )
            if row:
                row.access_token = creds.token
                row.refresh_token = creds.refresh_token or row.refresh_token
                row.scopes = list(creds.scopes) if creds.scopes else GOOGLE_SCOPES
                row.expiry = creds.expiry
                row.updated_at = datetime.now(timezone.utc)
            else:
                row = GoogleOAuthToken(
                    user_id=user_id,
                    access_token=creds.token,
                    refresh_token=creds.refresh_token,
                    scopes=list(creds.scopes) if creds.scopes else GOOGLE_SCOPES,
                    expiry=creds.expiry,
                )
                session.add(row)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error saving token: {e}")
            raise
        finally:
            session.close()


google_auth_service = GoogleAuthService()
