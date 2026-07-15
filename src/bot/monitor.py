"""Monitor — polls the Test IO dashboard for new test invitations."""
import logging
from playwright.async_api import Page

from ..screenshots.manager import capture
from ..stealth.human import poll_interval

logger = logging.getLogger(__name__)


async def check_for_invitations(page: Page, dashboard_url: str, config: dict) -> list:
    """Navigate to the Available Tasks page and look for test invitations.

    Returns a list of test element locators that can be passed to acceptor.
    """
    testio_config = config.get("testio", {})

    try:
        # Navigate to the Available Tasks page
        await page.goto(dashboard_url, wait_until="domcontentloaded", timeout=30000)
        
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        current_url = page.url.lower()

        # Check if we got redirected to login (session expired)
        login_indicators = ["login", "sign_in", "signin", "cirro.io/users/sign_in", "auth"]
        if any(ind in current_url for ind in login_indicators):
            logger.warning("Session expired during poll — need re-authentication")
            return []

        # Screenshot if configured
        if config.get("screenshots", {}).get("every_poll", False):
            await capture(page, "poll")

        # Check for the explicit "no available jobs" message on the Available Tasks page
        page_text = await page.text_content("body") or ""
        no_jobs_phrases = [
            "you don't have any available jobs",
            "no available jobs",
            "no test invitations",
            "no available tasks",
            "no tests available",
        ]
        page_text_lower = page_text.lower()
        for phrase in no_jobs_phrases:
            if phrase in page_text_lower:
                logger.debug(f"No tests available: '{phrase}' found on page")
                return []

        # ---- Look for test invitation elements on the Available Tasks page ----
        # These selectors cover common patterns for test cards/rows on Test.io
        invitation_selectors = [
            # Links or cards that contain test cycle info
            'a[href*="test_cycle"]',
            'a[href*="available_tasks"]',
            '[data-testid*="test-cycle"]',
            '[data-testid*="task"]',
            '.test-cycle-card',
            # Table rows or list items in the available tasks area
            'table tbody tr',
            '.task-list-item',
            '.available-task',
            # Generic card/row selectors within the main content area
            'main .card',
            '.content .card',
            '#content .card',
            # Any clickable element that looks like a test listing
            '[class*="invitation"]',
            '[class*="task-card"]',
            '[class*="test-card"]',
            '[class*="cycle"]',
            # Seat-related elements
            '[class*="seat"]',
            # Broad fallback: any <a> tag in the main area that isn't navigation
            'main a:not([href="/"])',
        ]

        found_tests = []

        for selector in invitation_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    for el in elements:
                        is_visible = await el.is_visible()
                        if is_visible:
                            # Check element has meaningful text (not just whitespace/navigation)
                            text = (await el.text_content() or "").strip()
                            if len(text) > 10:  # Real test entries have substantial text
                                found_tests.append(el)
                    if found_tests:
                        logger.info(f"Found {len(found_tests)} potential test(s) with selector: {selector}")
                        break
            except Exception:
                continue

        # Apply keyword filters
        filter_keywords = testio_config.get("filter_keywords", [])
        exclude_keywords = testio_config.get("exclude_keywords", [])

        if found_tests and (filter_keywords or exclude_keywords):
            filtered = []
            for test in found_tests:
                try:
                    text = (await test.text_content() or "").lower()

                    if filter_keywords:
                        if not any(kw.lower() in text for kw in filter_keywords):
                            logger.debug(f"Skipped (no keyword match): {text[:50]}")
                            continue

                    if exclude_keywords:
                        if any(kw.lower() in text for kw in exclude_keywords):
                            logger.debug(f"Skipped (excluded keyword): {text[:50]}")
                            continue

                    filtered.append(test)
                except Exception:
                    filtered.append(test)

            found_tests = filtered

        if found_tests:
            logger.info(f"🎯 {len(found_tests)} test invitation(s) available!")
            await capture(page, "tests_found")
        else:
            logger.debug("No test invitations found on Available Tasks page")

        return found_tests

    except Exception as e:
        logger.error(f"Poll failed: {e}")
        return []


async def wait_for_next_poll(config: dict, schedule_mode: str = "normal") -> None:
    """Wait the randomized interval before the next poll cycle."""
    await poll_interval(config, schedule_mode)
