"""Human-like delays for the POLLING phase ONLY. NOT used during acceptance."""
import asyncio
import random
import logging

logger = logging.getLogger(__name__)


async def stealth_delay(min_sec: float, max_sec: float) -> None:
    """Sleep for a random duration between min and max seconds.

    Uses a slightly gaussian distribution so the delay clusters
    around the midpoint rather than being uniformly random.
    This is used ONLY during polling/navigation, NEVER during acceptance.
    """
    midpoint = (min_sec + max_sec) / 2
    std_dev = (max_sec - min_sec) / 4
    delay = random.gauss(midpoint, std_dev)
    delay = max(min_sec, min(max_sec, delay))  # clamp
    logger.debug(f"Stealth delay: {delay:.1f}s")
    await asyncio.sleep(delay)


async def poll_interval(config: dict, schedule_mode: str = "normal") -> None:
    """Wait between dashboard poll cycles with randomized interval.

    Occasionally inserts a longer pause (2-5 min) to simulate
    a human stepping away from the screen. Adjusts based on schedule_mode.
    """
    testio_config = config.get("testio", {})
    min_sec = testio_config.get("poll_interval_min", 20)
    max_sec = testio_config.get("poll_interval_max", 60)

    if schedule_mode == "strict":
        # Strict mode: tighter intervals, no coffee breaks
        logger.debug("Strict mode active: no breaks")
        await stealth_delay(min_sec, max_sec)
        return

    if schedule_mode == "light":
        # Light mode: double the intervals, 15% chance of a longer break
        min_sec *= 2
        max_sec *= 2
        if random.random() < 0.15:
            break_duration = random.uniform(180, 400)
            logger.info(f"Light mode active: Taking a long break: {break_duration:.0f}s")
            await asyncio.sleep(break_duration)
            return
        # If no break, do normal delay and return
        await stealth_delay(min_sec, max_sec)
        return

    # Normal mode: 5% chance of a "break" pause (2-5 minutes)
    if random.random() < 0.05:
        break_duration = random.uniform(120, 300)
        logger.info(f"Taking a stealth break: {break_duration:.0f}s")
        await asyncio.sleep(break_duration)
    else:
        await stealth_delay(min_sec, max_sec)


async def typing_delay() -> None:
    """Short delay between keystrokes during login (stealth typing)."""
    await asyncio.sleep(random.uniform(0.05, 0.15))
