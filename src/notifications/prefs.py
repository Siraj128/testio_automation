"""Notification preferences — toggleable on/off per category."""
import json
import logging
from pathlib import Path

from ..config import get_data_dir

logger = logging.getLogger(__name__)

PREFS_PATH = get_data_dir() / "notification_prefs.json"

DEFAULT_PREFS = {
    "on_accept": True,
    "on_error": True,
    "send_screenshot": True,
    "heartbeat": False,
}


def load_prefs() -> dict:
    """Load notification preferences from disk."""
    if not PREFS_PATH.exists():
        save_prefs(DEFAULT_PREFS)
        return DEFAULT_PREFS.copy()

    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load prefs: {e}")
        return DEFAULT_PREFS.copy()


def save_prefs(prefs: dict) -> None:
    """Save notification preferences to disk."""
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save prefs: {e}")


def toggle(category: str) -> bool:
    """Toggle a notification category on/off. Returns new state."""
    prefs = load_prefs()
    current = prefs.get(category, True)
    prefs[category] = not current
    save_prefs(prefs)
    logger.info(f"Notification '{category}' toggled: {not current}")
    return not current


def is_enabled(category: str) -> bool:
    """Check if a notification category is enabled."""
    prefs = load_prefs()
    return prefs.get(category, True)
