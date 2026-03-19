"""
User Dashboard API — OpenClaw-style web dashboard for chat users.
Provides token-authenticated endpoints so Telegram users can view their
conversation history, permissions, preferences, and link Google accounts.
"""
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from loguru import logger

from app.database.base import SessionLocal
from app.database.models import User, Conversation, Message, UserPreference, TaskHistory


router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# In-memory token store: token_hash → {user_id, expires}
_dashboard_tokens: dict[str, dict] = {}
TOKEN_TTL_HOURS = 24


def generate_dashboard_token(user_id: str) -> str:
    """Generate a short-lived dashboard access token for a user."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    _dashboard_tokens[token_hash] = {
        "user_id": user_id,
        "expires": datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS),
    }
    # Clean expired tokens
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _dashboard_tokens.items() if v["expires"] < now]
    for k in expired:
        del _dashboard_tokens[k]
    return token


def _verify_token(token: str) -> str:
    """Verify token and return user_id. Raises HTTPException on failure."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    entry = _dashboard_tokens.get(token_hash)
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if datetime.now(timezone.utc) > entry["expires"]:
        del _dashboard_tokens[token_hash]
        raise HTTPException(status_code=401, detail="Token expired")
    return entry["user_id"]


# ─── API Endpoints ────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard_page(token: str = Query(...)):
    """Render the user dashboard as a self-contained HTML page."""
    user_id = _verify_token(token)

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(user_id=user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Gather data
        conversations = (
            db.query(Conversation)
            .filter_by(user_id=user_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(20)
            .all()
        )

        recent_messages = (
            db.query(Message)
            .join(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Message.timestamp.desc())
            .limit(50)
            .all()
        )

        preferences = db.query(UserPreference).filter_by(user_id=user_id).all()

        tasks = (
            db.query(TaskHistory)
            .filter_by(user_id=user_id)
            .order_by(TaskHistory.timestamp.desc())
            .limit(20)
            .all()
        )

        # Get permissions
        from app.services.permission_service import permission_service
        perms = permission_service.get_permissions(user_id)

        # Build HTML
        html = _render_dashboard(user, conversations, recent_messages, preferences, tasks, perms, token)
        return HTMLResponse(content=html)
    finally:
        db.close()


@router.get("/api/permissions")
async def get_permissions(token: str = Query(...)):
    """Get user's permissions as JSON."""
    user_id = _verify_token(token)
    from app.services.permission_service import permission_service
    return permission_service.get_permissions(user_id)


@router.get("/api/conversations")
async def get_conversations(token: str = Query(...)):
    """Get user's recent conversations as JSON."""
    user_id = _verify_token(token)
    db = SessionLocal()
    try:
        convos = (
            db.query(Conversation)
            .filter_by(user_id=user_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(20)
            .all()
        )
        return [
            {
                "conversation_id": c.conversation_id,
                "title": c.title,
                "message_count": c.message_count,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            }
            for c in convos
        ]
    finally:
        db.close()


@router.get("/api/history/{conversation_id}")
async def get_conversation_history(conversation_id: str, token: str = Query(...)):
    """Get messages for a specific conversation."""
    user_id = _verify_token(token)
    db = SessionLocal()
    try:
        convo = db.query(Conversation).filter_by(
            conversation_id=conversation_id, user_id=user_id
        ).first()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = (
            db.query(Message)
            .filter_by(conversation_id=conversation_id)
            .order_by(Message.timestamp.asc())
            .all()
        )
        return [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in messages
        ]
    finally:
        db.close()


# ─── HTML Renderer ────────────────────────────────────────────

def _render_dashboard(user, conversations, messages, preferences, tasks, perms, token):
    """Render a self-contained HTML dashboard."""
    conv_rows = ""
    for c in conversations:
        last = c.last_message_at.strftime("%Y-%m-%d %H:%M") if c.last_message_at else "—"
        conv_rows += f"""
        <tr>
            <td>{_esc(c.title or c.conversation_id)}</td>
            <td>{c.message_count or 0}</td>
            <td>{last}</td>
        </tr>"""

    msg_rows = ""
    for m in messages[:30]:
        ts = m.timestamp.strftime("%m-%d %H:%M") if m.timestamp else ""
        role_badge = "🧑" if m.role == "user" else "🤖"
        content_preview = (m.content or "")[:120]
        msg_rows += f"""
        <tr>
            <td>{role_badge}</td>
            <td>{_esc(content_preview)}</td>
            <td>{ts}</td>
        </tr>"""

    task_rows = ""
    for t in tasks:
        ts = t.timestamp.strftime("%Y-%m-%d %H:%M") if t.timestamp else ""
        status = "✅" if t.success else "❌"
        task_rows += f"""
        <tr>
            <td>{status}</td>
            <td>{_esc(t.task_type or '')}</td>
            <td>{_esc(t.agent_used or '')}</td>
            <td>{_esc((t.task_description or '')[:80])}</td>
            <td>{ts}</td>
        </tr>"""

    pref_items = ""
    for p in preferences:
        pref_items += f"<li><strong>{_esc(p.preference_key)}</strong>: {_esc(str(p.preference_value))}</li>"

    agents_list = ", ".join(perms.get("allowed_agents", []))
    tier = perms.get("tier", "unknown")
    desktop = perms.get("desktop_access", "none")
    rate = f"{perms.get('messages_today', 0)} / {perms.get('daily_message_limit', 100)}"

    created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SonarBot Dashboard</title>
<style>
  :root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 20px; }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ color: var(--accent); margin-bottom: 8px; }}
  h2 {{ color: var(--accent); margin: 24px 0 12px; font-size: 1.2em; }}
  .subtitle {{ color: #8b949e; margin-bottom: 20px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .card-label {{ color: #8b949e; font-size: 0.85em; }}
  .card-value {{ font-size: 1.3em; font-weight: 600; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.9em; }}
  th {{ color: #8b949e; font-weight: 500; }}
  tr:hover {{ background: rgba(88,166,255,0.05); }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 4px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 600; }}
  .badge-tier {{ background: rgba(88,166,255,0.15); color: var(--accent); }}
  .badge-desktop {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="container">
  <h1>🤖 SonarBot Dashboard</h1>
  <p class="subtitle">User: <strong>{_esc(user.name or user.user_id)}</strong> &middot; Member since {created}</p>

  <div class="cards">
    <div class="card">
      <div class="card-label">Permission Tier</div>
      <div class="card-value"><span class="badge badge-tier">{_esc(tier)}</span></div>
    </div>
    <div class="card">
      <div class="card-label">Desktop Access</div>
      <div class="card-value"><span class="badge badge-desktop">{_esc(desktop)}</span></div>
    </div>
    <div class="card">
      <div class="card-label">Messages Today</div>
      <div class="card-value">{_esc(rate)}</div>
    </div>
    <div class="card">
      <div class="card-label">Allowed Agents</div>
      <div class="card-value" style="font-size:0.9em">{_esc(agents_list)}</div>
    </div>
  </div>

  <h2>📝 Recent Conversations</h2>
  <table>
    <tr><th>Title</th><th>Messages</th><th>Last Active</th></tr>
    {conv_rows if conv_rows else '<tr><td colspan="3">No conversations yet.</td></tr>'}
  </table>

  <h2>💬 Recent Messages</h2>
  <table>
    <tr><th></th><th>Content</th><th>Time</th></tr>
    {msg_rows if msg_rows else '<tr><td colspan="3">No messages yet.</td></tr>'}
  </table>

  <h2>📊 Task History</h2>
  <table>
    <tr><th></th><th>Type</th><th>Agent</th><th>Description</th><th>Time</th></tr>
    {task_rows if task_rows else '<tr><td colspan="5">No tasks yet.</td></tr>'}
  </table>

  <h2>⚙️ Learned Preferences</h2>
  <ul>
    {pref_items if pref_items else '<li>No preferences learned yet.</li>'}
  </ul>

  <br>
  <p style="color:#8b949e; font-size:0.85em">
    🔗 <a href="/api/v1/auth/google/login?user_id={_esc(user.user_id)}">Link Google Account</a> &middot;
    Token valid for {TOKEN_TTL_HOURS}h
  </p>
</div>
</body>
</html>"""


def _esc(text: str) -> str:
    """Escape HTML entities."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
