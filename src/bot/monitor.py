"""Monitor — polls the Test IO dashboard for new test invitations."""
import logging
from playwright.async_api import Page

from ..screenshots.manager import capture
from ..stealth.human import poll_interval

logger = logging.getLogger(__name__)


async def check_for_invitations(page: Page, dashboard_url: str, config: dict) -> list:
    """Navigate to the dashboard and look for test invitations.

    Returns a list of test element locators that can be passed to acceptor.
    """
    testio_config = config.get("testio", {})

    try:
        # Navigate to dashboard
        await page.goto(dashboard_url, wait_until="domcontentloaded", timeout=30000)
        
        try:
            # Modern web apps sometimes never reach networkidle due to tracking/websockets
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass  # It's fine if this times out, DOM is already loaded

        current_url = page.url.lower()

        # Check if we got redirected to login (session expired)
        login_indicators = ["login", "sign_in", "signin", "cirro.io", "auth"]
        if any(ind in current_url for ind in login_indicators):
            logger.warning("Session expired during poll — need re-authentication")
            return []  # Engine will handle re-auth

        # Screenshot if configured to screenshot every poll
        if config.get("screenshots", {}).get("every_poll", False):
            await capture(page, "poll")

        # Check if there are explicitly NO tests
        try:
            no_tests = await page.query_selector('text="No test invitations"')
            if no_tests and await no_tests.is_visible():
                logger.debug("Explicit 'No test invitations' message found.")
                return []
        except Exception:
            pass

        # Look for test invitation elements on the dashboard
        invitation_selectors = [
            # Primary selectors for test cycle cards
            '[data-testid*="test-cycle"]',
            '.test-cycle-card',
            # Invitation-specific selectors
            '[class*="invitation"]',
            '[data-testid*="invitation"]',
            '.invitation-card',
            # Generic card selectors in the invitation area (strict sibling)
            'div:has-text("Available Test Cycles") + div .card',
            '.available-tests .card',
        ]

        found_tests = []

        for selector in invitation_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    logger.info(f"Found {len(elements)} potential test(s) with: {selector}")
                    for el in elements:
                        # Check if element is visible
                        is_visible = await el.is_visible()
                        if is_visible:
                            found_tests.append(el)
                    if found_tests:
                        break  # Use the first selector that finds results
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

                    # Apply include filter (must match at least one keyword)
                    if filter_keywords:
                        if not any(kw.lower() in text for kw in filter_keywords):
                            logger.debug(f"Skipped (no keyword match): {text[:50]}")
                            continue

                    # Apply exclude filter (must not match any keyword)
                    if exclude_keywords:
                        if any(kw.lower() in text for kw in exclude_keywords):
                            logger.debug(f"Skipped (excluded keyword): {text[:50]}")
                            continue

                    filtered.append(test)
                except Exception:
                    filtered.append(test)  # Include if we can't read text

            found_tests = filtered

        if found_tests:
            logger.info(f"🎯 {len(found_tests)} test invitation(s) available!")
        else:
            logger.debug("No test invitations found")

        return found_tests

    except Exception as e:
        logger.error(f"Poll failed: {e}")
        return []


async def wait_for_next_poll(config: dict, schedule_mode: str = "normal") -> None:
    """Wait the randomized interval before the next poll cycle."""
    await poll_interval(config, schedule_mode)
