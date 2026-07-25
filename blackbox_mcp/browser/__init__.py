"""Browser control layer: session lifecycle, event listeners, selector logic."""

from .session import ACTION_LOCK, BrowserSession, get_session

__all__ = ["ACTION_LOCK", "BrowserSession", "get_session"]
