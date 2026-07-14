"""Screenshot capture and management."""
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import Page

from ..config import get_data_dir

logger = logging.getLogger(__name__)


def _get_screenshot_dir() -> Path:
    """Get today's screenshot directory, creating it if needed."""
    today = datetime.now().strftime("%Y-%m-%d")
    ss_dir = get_data_dir() / "screenshots" / today
    ss_dir.mkdir(parents=True, exist_ok=True)
    return ss_dir


async def capture(page: Page, name: str, test_id: str = "") -> Path | None:
    """Take a screenshot and save it with a descriptive filename.

    Args:
        page: The Playwright page to capture.
        name: Descriptive name (e.g., 'checkbox_checked', 'accept_clicked').
        test_id: Optional test cycle ID to include in filename.

    Returns:
        Path to the saved screenshot, or None on failure.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [name]
        if test_id:
            parts.append(test_id)
        parts.append(timestamp)
        filename = "_".join(parts) + ".png"

        filepath = _get_screenshot_dir() / filename
        await page.screenshot(path=str(filepath), full_page=False)
        logger.info(f"📸 Screenshot saved: {filepath.name}")
        return filepath
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        return None


async def capture_full_page(page: Page, name: str, test_id: str = "") -> Path | None:
    """Take a full-page screenshot (scrolls to capture everything)."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [name]
        if test_id:
            parts.append(test_id)
        parts.append(timestamp)
        filename = "_".join(parts) + "_full.png"

        filepath = _get_screenshot_dir() / filename
        await page.screenshot(path=str(filepath), full_page=True)
        logger.info(f"📸 Full-page screenshot saved: {filepath.name}")
        return filepath
    except Exception as e:
        logger.error(f"Full-page screenshot failed: {e}")
        return None


def list_recent(n: int = 20) -> list[dict]:
    """Return the N most recent screenshots with metadata.

    Returns:
        List of dicts with 'path', 'name', 'date', 'size_kb'.
    """
    ss_base = get_data_dir() / "screenshots"
    if not ss_base.exists():
        return []

    all_files = []
    for date_dir in sorted(ss_base.iterdir(), reverse=True):
        if date_dir.is_dir():
            for f in sorted(date_dir.iterdir(), reverse=True):
                if f.suffix == ".png":
                    all_files.append({
                        "path": str(f),
                        "name": f.name,
                        "date": date_dir.name,
                        "size_kb": round(f.stat().st_size / 1024, 1),
                    })
                    if len(all_files) >= n:
                        return all_files
    return all_files


def cleanup_old(days: int = 7) -> int:
    """Delete screenshot directories older than N days.

    Returns:
        Number of directories removed.
    """
    ss_base = get_data_dir() / "screenshots"
    if not ss_base.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    removed = 0

    for date_dir in ss_base.iterdir():
        if date_dir.is_dir():
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    shutil.rmtree(date_dir)
                    removed += 1
                    logger.info(f"🗑️ Cleaned up old screenshots: {date_dir.name}")
            except (ValueError, OSError) as e:
                logger.warning(f"Skipping directory {date_dir.name}: {e}")

    if removed > 0:
        logger.info(f"Cleaned up {removed} old screenshot directories")
    return removed
