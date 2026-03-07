"""
Per-User Permission Service — OpenClaw-style access control.
Manages permission tiers, agent access, rate limits per user.
"""
from datetime import datetime, timezone, timedelta
from loguru import logger
from app.database.base import SessionLocal
from app.database.models import UserPermission, User


# All agents available
ALL_AGENTS = ["general", "coding", "web", "email", "calendar", "desktop"]

# Default permission profiles — everyone gets full access
PERMISSION_PROFILES = {
    "local": {
        "tier": "local",
        "allowed_agents": ALL_AGENTS,
        "desktop_access": "host",
        "sandbox_enabled": False,
        "daily_message_limit": 10000,
    },
    "remote": {
        "tier": "remote",
        "allowed_agents": ALL_AGENTS,
        "desktop_access": "host",
        "sandbox_enabled": False,
        "daily_message_limit": 10000,
    },
    "admin": {
        "tier": "admin",
        "allowed_agents": ALL_AGENTS,
        "desktop_access": "host",
        "sandbox_enabled": False,
        "daily_message_limit": 10000,
    },
}


class PermissionService:
    """Manages per-user permission tiers and access control."""

    def get_permissions(self, user_id: str) -> dict:
        """Get or create permissions for a user, returns a plain dict."""
        db = SessionLocal()
        try:
            perm = db.query(UserPermission).filter_by(user_id=user_id).first()
            if not perm:
                perm = self._create_default(db, user_id)
            return {
                "user_id": perm.user_id,
                "tier": perm.tier,
                "allowed_agents": perm.allowed_agents or [],
                "desktop_access": perm.desktop_access,
                "sandbox_enabled": perm.sandbox_enabled,
                "daily_message_limit": perm.daily_message_limit,
                "messages_today": perm.messages_today,
            }
        finally:
            db.close()

    def check_agent_access(self, user_id: str, agent_type: str) -> tuple[bool, str]:
        """Check if a user can use a specific agent.
        Returns (allowed: bool, reason: str).
        """
        perms = self.get_permissions(user_id)
        allowed_agents = perms.get("allowed_agents", [])

        if agent_type not in allowed_agents:
            return False, (
                f"🔒 **{agent_type.title()} agent is not available for your account.**\n"
                f"Your permission tier ({perms['tier']}) allows: {', '.join(allowed_agents)}.\n"
                f"Contact the admin to upgrade your access."
            )
        return True, ""

    def check_rate_limit(self, user_id: str) -> tuple[bool, str]:
        """Check if user has exceeded daily message limit.
        Returns (allowed: bool, reason: str).
        """
        db = SessionLocal()
        try:
            perm = db.query(UserPermission).filter_by(user_id=user_id).first()
            if not perm:
                perm = self._create_default(db, user_id)

            now = datetime.now(timezone.utc)

            # Reset counter if a new day (handle naive datetimes from SQLite)
            reset_at = perm.limit_reset_at
            if reset_at is not None and reset_at.tzinfo is None:
                reset_at = reset_at.replace(tzinfo=timezone.utc)
            if reset_at is None or now >= reset_at:
                perm.messages_today = 0
                perm.limit_reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                db.commit()

            if perm.messages_today >= perm.daily_message_limit:
                return False, (
                    f"⏳ **Daily message limit reached ({perm.daily_message_limit}).**\n"
                    f"Resets at {perm.limit_reset_at.strftime('%H:%M UTC')}."
                )

            # Increment
            perm.messages_today += 1
            db.commit()
            return True, ""
        finally:
            db.close()

    def set_tier(self, user_id: str, tier: str) -> dict:
        """Set a user's permission tier (admin action)."""
        profile = PERMISSION_PROFILES.get(tier)
        if not profile:
            return {"error": f"Unknown tier: {tier}. Available: {list(PERMISSION_PROFILES.keys())}"}

        db = SessionLocal()
        try:
            perm = db.query(UserPermission).filter_by(user_id=user_id).first()
            if not perm:
                perm = self._create_default(db, user_id)

            perm.tier = profile["tier"]
            perm.allowed_agents = profile["allowed_agents"]
            perm.desktop_access = profile["desktop_access"]
            perm.sandbox_enabled = profile["sandbox_enabled"]
            perm.daily_message_limit = profile["daily_message_limit"]
            db.commit()

            logger.info(f"🔑 Set permission tier '{tier}' for user {user_id}")
            return {"success": True, "tier": tier, "user_id": user_id}
        finally:
            db.close()

    def grant_agent(self, user_id: str, agent_type: str) -> dict:
        """Grant a specific agent to a user."""
        db = SessionLocal()
        try:
            perm = db.query(UserPermission).filter_by(user_id=user_id).first()
            if not perm:
                perm = self._create_default(db, user_id)

            agents = list(perm.allowed_agents or [])
            if agent_type not in agents:
                agents.append(agent_type)
                perm.allowed_agents = agents
                db.commit()
                logger.info(f"✅ Granted {agent_type} agent to {user_id}")
            return {"success": True, "allowed_agents": agents}
        finally:
            db.close()

    def revoke_agent(self, user_id: str, agent_type: str) -> dict:
        """Revoke a specific agent from a user."""
        db = SessionLocal()
        try:
            perm = db.query(UserPermission).filter_by(user_id=user_id).first()
            if not perm:
                return {"error": "User has no permissions record."}

            agents = list(perm.allowed_agents or [])
            if agent_type in agents:
                agents.remove(agent_type)
                perm.allowed_agents = agents
                db.commit()
                logger.info(f"🚫 Revoked {agent_type} agent from {user_id}")
            return {"success": True, "allowed_agents": agents}
        finally:
            db.close()

    # --- Internal ---

    def _create_default(self, db, user_id: str) -> UserPermission:
        """Create default permissions for a new user."""
        # Ensure user exists
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(user_id=user_id, name=user_id)
            db.add(user)
            db.flush()

        # Determine default profile
        if user_id.startswith("discord_"):
            profile = PERMISSION_PROFILES["remote"]
        else:
            profile = PERMISSION_PROFILES["local"]

        perm = UserPermission(
            user_id=user_id,
            tier=profile["tier"],
            allowed_agents=profile["allowed_agents"],
            desktop_access=profile["desktop_access"],
            sandbox_enabled=profile["sandbox_enabled"],
            daily_message_limit=profile["daily_message_limit"],
        )
        db.add(perm)
        db.commit()
        db.refresh(perm)

        logger.info(f"🆕 Created {profile['tier']} permissions for {user_id}")
        return perm


# Global instance
permission_service = PermissionService()
