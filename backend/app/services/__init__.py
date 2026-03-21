"""
Services Module
"""
try:
    from .sandbox_services import sandbox_service as sandbox_service
except Exception:  # pragma: no cover - optional dependency in local/test environments
    sandbox_service = None

__all__ = ['sandbox_service']
