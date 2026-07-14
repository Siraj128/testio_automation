"""Acceptor — handles the instant acceptance flow.

This is the CRITICAL PATH. Zero delays here.
Checkbox → Accept button → Verify, as fast as possible.
"""
import asyncio
import logging
from playwright.async_api import Page, TimeoutError

from ..screenshots.manager import capture
from ..intercept.replay import fast_accept_test

logger = logging.getLogger(__name__)


async def accept_test(page: Page, test_element, dry_run: bool = False) -> dict:
    """Execute the full acceptance flow for a single test invitation.

    Flow:
    1. Click the test card to open the overview page
    2. Scroll to the "Join this Test" section
    3. Check the checkbox ("I have read all instructions...")
    4. Click "Accept and take seat"
    5. Verify success
    6. Screenshot everything

    This runs at MAXIMUM SPEED — no artificial delays.

    Args:
        page: The current Playwright page.
        test_element: The locator/element for the test card on the dashboard.
        dry_run: If True, detect but don't click accept.

    Returns:
        Dict with keys: success, test_name, test_id, screenshot_path, error
    """
    result = {
        "success": False,
        "test_name": "",
        "test_id": "",
        "screenshot_path": None,
        "error": "",
    }

    try:
        # --- Step 1: Extract test info and click into it ---
        try:
            test_name = await test_element.text_content() or "Unknown Test"
            test_name = test_name.strip()[:100]  # Truncate for sanity
            result["test_name"] = test_name
            logger.info(f"🎯 Found test: {test_name}")
        except Exception:
            result["test_name"] = "Unknown Test"

        # Click the test card to navigate to the overview page
        await test_element.click()
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # Try to extract test ID from URL
        current_url = page.url
        # URLs typically like: app.test.io/tester/test_cycles/12345
        url_parts = current_url.rstrip("/").split("/")
        for part in reversed(url_parts):
            if part.isdigit():
                result["test_id"] = part
                break

        logger.info(f"Test overview loaded: {current_url}")
        await capture(page, "test_overview", result["test_id"])

        # ⚡ PHASE 3: Attempt API Fast-Accept first
        if result["test_id"]:
            fast_success = await fast_accept_test(page, result["test_id"])
            if fast_success:
                logger.info(f"⚡🚀 API Fast-Accept SUCCEEDED for test {result['test_id']}!")
                result["success"] = True
                return result

        # --- Step 2: Scroll to "Join this Test" section ---
        # Scroll to bottom where the join section lives
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # Brief wait for lazy-loaded content
        await page.wait_for_timeout(500)

        # --- Step 3: Find and check the checkbox ---
        checkbox_selectors = [
            'input[type="checkbox"]',
            'label:has-text("read all instructions") input[type="checkbox"]',
            'label:has-text("agree") input[type="checkbox"]',
            '[class*="checkbox"]',
            'label:has-text("read") input',
            # Broader fallback: any checkbox near the accept button
            'form input[type="checkbox"]',
        ]

        checkbox = None
        for selector in checkbox_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    # Find the checkbox that is NOT already checked
                    is_checked = await el.is_checked()
                    if not is_checked:
                        checkbox = el
                        logger.info(f"Found unchecked checkbox: {selector}")
                        break
                    else:
                        # Already checked — might be the right one
                        checkbox = el
                        logger.info(f"Checkbox already checked: {selector}")
                if checkbox:
                    break
            except Exception:
                continue

        if not checkbox:
            # Try clicking any label that mentions instructions/agreement
            label_selectors = [
                'label:has-text("read")',
                'label:has-text("agree")',
                'label:has-text("instructions")',
                '.checkbox',
                '[data-testid*="checkbox"]',
            ]
            for selector in label_selectors:
                try:
                    label = await page.query_selector(selector)
                    if label:
                        await label.click()
                        checkbox = label
                        logger.info(f"Clicked label as checkbox: {selector}")
                        break
                except Exception:
                    continue

        if checkbox:
            is_checked = False
            try:
                is_checked = await checkbox.is_checked()
            except Exception:
                pass

            if not is_checked:
                await checkbox.click()
                logger.info("✅ Checkbox clicked (agree to instructions)")
            else:
                logger.info("✅ Checkbox was already checked")

            await capture(page, "checkbox_checked", result["test_id"])
        else:
            logger.warning("⚠️ Could not find checkbox — attempting accept anyway")

        # --- Step 4: Click "Accept and take seat" ---
        if dry_run:
            logger.info("🔍 DRY RUN — skipping accept button click")
            result["success"] = True
            result["error"] = "dry_run"
            await capture(page, "dry_run_detected", result["test_id"])
            return result

        accept_selectors = [
            'button:has-text("Accept and take seat")',
            'button:has-text("Accept")',
            'button:has-text("Take seat")',
            'button:has-text("Join")',
            'button:has-text("Yes, I will test")',
            'a:has-text("Accept and take seat")',
            'a:has-text("Accept")',
            '[data-testid*="accept"]',
            '[class*="accept"]',
            '.action-bar button',
            'button.btn-primary',
            'button.btn-success',
        ]

        accept_button = None
        for selector in accept_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    is_visible = await btn.is_visible()
                    is_enabled = await btn.is_enabled()
                    if is_visible and is_enabled:
                        accept_button = btn
                        logger.info(f"Found accept button: {selector}")
                        break
                    elif is_visible and not is_enabled:
                        logger.warning(f"Accept button found but disabled: {selector}")
            except Exception:
                continue

        if not accept_button:
            error = "Could not find the 'Accept and take seat' button"
            logger.error(f"❌ {error}")
            result["error"] = error
            await capture(page, "accept_button_not_found", result["test_id"])
            return result

        # ⚡ CLICK — INSTANT, NO DELAY
        await accept_button.click()
        logger.info("🚀 Accept button clicked!")
        await capture(page, "accept_clicked", result["test_id"])

        # --- Step 5: Verify success ---
        # Wait briefly for the page to respond
        await page.wait_for_timeout(2000)

        # Check for success indicators
        success_indicators = [
            'text="You have joined"',
            'text="Successfully joined"',
            'text="You are now part"',
            'text="Congratulations"',
            '.success',
            '.alert-success',
            '[class*="success"]',
        ]

        is_success = False
        for indicator in success_indicators:
            try:
                el = await page.query_selector(indicator)
                if el:
                    is_success = True
                    logger.info(f"✅ Success confirmed: {indicator}")
                    break
            except Exception:
                continue

        # Also check for error indicators
        error_indicators = [
            'text="seats are full"',
            'text="no more seats"',
            'text="limit reached"',
            'text="already joined"',
            'text="not available"',
            '.alert-danger',
            '.alert-error',
            '.error',
        ]

        for indicator in error_indicators:
            try:
                el = await page.query_selector(indicator)
                if el:
                    error_text = await el.text_content()
                    result["error"] = error_text or "Unknown error"
                    logger.error(f"❌ Acceptance failed: {result['error']}")
                    await capture(page, "accept_failed", result["test_id"])
                    return result
            except Exception:
                continue

        # If no explicit success or error found, check URL change or page content
        if not is_success:
            # Assume success if we didn't hit an error and the page changed
            page_content = await page.content()
            if "accept" not in page_content.lower() or "joined" in page_content.lower():
                is_success = True
                logger.info("✅ Acceptance likely succeeded (no error detected)")

        result["success"] = is_success
        screenshot_path = await capture(page, "result_success" if is_success else "result_uncertain", result["test_id"])
        result["screenshot_path"] = str(screenshot_path) if screenshot_path else None

        if is_success:
            logger.info(f"🎉 Successfully accepted: {result['test_name']}")
        else:
            logger.warning(f"⚠️ Acceptance uncertain for: {result['test_name']}")

        return result

    except Exception as e:
        error_msg = f"Acceptance flow error: {e}"
        logger.error(f"❌ {error_msg}")
        result["error"] = error_msg
        await capture(page, "accept_exception", result.get("test_id", ""))
        return result
