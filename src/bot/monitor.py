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
        logger.info("🔍 Checking for invitations on dashboard...")
        await page.goto(dashboard_url, wait_until="domcontentloaded", timeout=30000)
        
        try:
            # We don't use networkidle because it's too slow. Instead, we'll fast-poll for tests.
            # But first, give a tiny buffer for React to mount
            await page.wait_for_timeout(500)
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

        invitation_selectors = [
            'a[href*="test_cycle"]', 'a[href*="available_tasks"]',
            '[data-testid*="test-cycle"]', '[data-testid*="task"]', '.test-cycle-card',
            'table tbody tr', '.task-list-item', '.available-task',
            'main .card', '.content .card', '#content .card',
            '[class*="invitation"]', '[class*="task-card"]', '[class*="test-card"]',
            '[class*="cycle"]', '[class*="seat"]', 'main a:not([href="/"])',
        ]

        # Fast polling loop: check for "no jobs" or "available jobs" instantly as they render
        import time
        start_time = time.time()
        found_tests = []
        
        while time.time() - start_time < 10.0:  # 10 second max wait
            page_text = await page.text_content("body") or ""
            page_text_lower = page_text.lower()
            
            # 1. Check if the empty state rendered
            no_jobs_phrases = [
                "you don't have any available jobs", "no available jobs",
                "no test invitations", "no available tasks", "no tests available"
            ]
            if any(phrase in page_text_lower for phrase in no_jobs_phrases):
                logger.info("❌ No tests available (empty state rendered)")
                return []

            # 2. Check if test cards rendered
            for selector in invitation_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        for el in elements:
                            if await el.is_visible():
                                text = (await el.text_content() or "").strip()
                                if len(text) > 10:
                                    found_tests.append(el)
                        if found_tests:
                            logger.info(f"⚡ Found {len(found_tests)} test(s) in {time.time() - start_time:.1f}s via {selector}")
                            return found_tests
                except Exception:
                    continue
            
            await page.wait_for_timeout(250)

        logger.warning("⏳ Timeout waiting for tests or empty state to render.")
        return []

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


async def check_notifications_dropdown(page, config: dict) -> list:
    """Phase 1: Click the notification bell and look for test invitations in the dropdown."""
    import time
    from ..screenshots.manager import capture
    
    logger.info("🔔 Phase 1: Checking notification dropdown...")
    
    # A wide net of standard notification bell selectors
    bell_selectors = [
        '[aria-label*="notification" i]',
        '[data-testid*="notification"]',
        '.notifications-bell',
        '.fa-bell',
        'i[class*="bell"]',
        'a[href*="notifications"]',
        'button[class*="notification"]'
    ]
    
    bell_clicked = False
    for selector in bell_selectors:
        try:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    await el.click(timeout=3000)
                    logger.info(f"👉 Clicked notification bell using selector: {selector}")
                    bell_clicked = True
                    break
        except Exception:
            continue
        if bell_clicked:
            break
            
    if not bell_clicked:
        logger.warning("❌ Could not find/click the notification bell icon.")
        return []
        
    # Wait briefly for dropdown to animate/render
    await page.wait_for_timeout(1000)
    
    if config.get("screenshots", {}).get("every_poll", False):
        await capture(page, "notification_dropdown")
        
    # Look for invitation links inside the dropdown
    dropdown_selectors = [
        '.dropdown-menu a[href*="test_cycle"]',
        '[class*="notification"] a[href*="test_cycle"]',
        '[class*="dropdown"] a[href*="test_cycle"]',
        '.notifications-list-item a',
        'a[href*="test_cycle"]',
        'div[class*="notification"] a'
    ]
    
    start_time = time.time()
    found_tests = []
    
    while time.time() - start_time < 5.0:  # 5 second wait for dropdown content
        for selector in dropdown_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    if await el.is_visible():
                        text = (await el.text_content() or "").lower()
                        if "invitation" in text or "cycle" in text or "test" in text or "#" in text:
                            found_tests.append(el)
                
                if found_tests:
                    logger.info(f"⚡ Found {len(found_tests)} test(s) in dropdown via {selector}")
                    return found_tests
            except Exception:
                continue
        await page.wait_for_timeout(250)
        
    logger.warning("⏳ No tests found in notification dropdown.")
    
    # Try to close the dropdown
    try:
        await page.mouse.click(0, 0)
    except Exception:
        pass
        
    return []
