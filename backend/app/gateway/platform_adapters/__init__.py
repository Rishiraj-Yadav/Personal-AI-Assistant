"""
Platform Adapters - Phase 4

Adapters for different platforms (Web, Desktop, CLI, Mobile).
"""

from .web_adapter import WebAdapter, web_adapter
from .desktop_adapter import DesktopAdapter, desktop_adapter

__all__ = [
    "WebAdapter",
    "web_adapter",
    "DesktopAdapter",
    "desktop_adapter",
]
