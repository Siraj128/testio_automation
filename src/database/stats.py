"""Stats Database — permanently stores polling and acceptance stats."""
import aiosqlite
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..config import get_data_dir

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """Return the absolute path to the stats database."""
    return get_data_dir() / "stats.db"


async def init_db() -> None:
    """Initialize the SQLite database and create the table if needed."""
    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    refreshes INTEGER DEFAULT 0,
                    tests_accepted INTEGER DEFAULT 0,
                    tests_failed INTEGER DEFAULT 0
                )
                """
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to initialize stats DB: {e}")


async def _ensure_today(db: aiosqlite.Connection, date_str: str) -> None:
    """Ensure a row exists for the given date."""
    await db.execute(
        "INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (date_str,)
    )


async def increment_refresh() -> None:
    """Increment the refresh counter for today."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await _ensure_today(db, date_str)
            await db.execute(
                "UPDATE daily_stats SET refreshes = refreshes + 1 WHERE date = ?", 
                (date_str,)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log refresh to DB: {e}")


async def increment_accepted() -> None:
    """Increment the accepted counter for today."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await _ensure_today(db, date_str)
            await db.execute(
                "UPDATE daily_stats SET tests_accepted = tests_accepted + 1 WHERE date = ?", 
                (date_str,)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log acceptance to DB: {e}")


async def increment_failed() -> None:
    """Increment the failed counter for today."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            await _ensure_today(db, date_str)
            await db.execute(
                "UPDATE daily_stats SET tests_failed = tests_failed + 1 WHERE date = ?", 
                (date_str,)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log failure to DB: {e}")


async def get_today() -> dict:
    """Return the stats for today."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    db_path = get_db_path()
    try:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT refreshes, tests_accepted, tests_failed FROM daily_stats WHERE date = ?", (date_str,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {"refreshes": row[0], "accepted": row[1], "failed": row[2]}
                return {"refreshes": 0, "accepted": 0, "failed": 0}
    except Exception as e:
        logger.error(f"Failed to fetch today's stats: {e}")
        return {"refreshes": 0, "accepted": 0, "failed": 0}


async def get_weekly() -> list[dict]:
    """Return stats for the last 7 days, including days with no activity."""
    db_path = get_db_path()
    report = []
    try:
        async with aiosqlite.connect(db_path) as db:
            for i in range(7):
                target_date = datetime.now() - timedelta(days=i)
                date_str = target_date.strftime("%Y-%m-%d")
                
                async with db.execute("SELECT refreshes, tests_accepted, tests_failed FROM daily_stats WHERE date = ?", (date_str,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        report.append({
                            "date": date_str,
                            "display_date": target_date.strftime("%b %d"),
                            "refreshes": row[0],
                            "accepted": row[1],
                            "failed": row[2]
                        })
                    else:
                        report.append({
                            "date": date_str,
                            "display_date": target_date.strftime("%b %d"),
                            "refreshes": 0,
                            "accepted": 0,
                            "failed": 0
                        })
    except Exception as e:
        logger.error(f"Failed to fetch weekly stats: {e}")
    
    return report
