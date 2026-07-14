"""Authentication handler — Cirro SSO login + cookie persistence."""
import json
import logging
from pathlib import Path
from playwright.async_api import Page, BrowserContext

from ..stealth.human import typing_delay
from ..config import get_data_dir

logger = logging.getLogger(__name__)

COOKIES_PATH = get_data_dir() / "browser_state" / "cookies.json"
LOCAL_STORAGE_PATH = get_data_dir() / "browser_state" / "local_storage.json"


async def save_session(context: BrowserContext) -> None:
    """Save all cookies and storage state to disk for reuse across restarts."""
    try:
        state = await context.storage_state()
        COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        logger.info(f"Session saved: {len(state.get('cookies', []))} cookies")
    except Exception as e:
        logger.error(f"Failed to save session: {e}")


async def load_session(context: BrowserContext) -> bool:
    """Load previously saved cookies into the browser context.

    Returns True if cookies were loaded, False if no saved session exists.
    """
    if not COOKIES_PATH.exists():
        logger.info("No saved session found — will need to login")
        return False

    try:
        with open(COOKIES_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)

        cookies = state.get("cookies", [])
        if cookies:
            await context.add_cookies(cookies)
            logger.info(f"Loaded {len(cookies)} saved cookies")
            return True
        else:
            logger.warning("Saved session file exists but has no cookies")
            return False
    except Exception as e:
        logger.error(f"Failed to load session: {e}")
        return False


async def is_session_valid(page: Page, dashboard_url: str) -> bool:
    """Check if the current session is still valid.

    Navigate to the dashboard — if we get redirected to a login page,
    the session has expired.
    """
    try:
        response = await page.goto(dashboard_url, wait_until="domcontentloaded", timeout=30000)

        # Wait a moment for any redirects to complete
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        current_url = page.url.lower()

        # Check if we landed on a login/auth page (Cirro SSO redirect)
        login_indicators = ["login", "sign_in", "signin", "cirro.io", "auth"]
        is_on_login = any(indicator in current_url for indicator in login_indicators)

        if is_on_login:
            logger.warning(f"Session expired — redirected to: {current_url}")
            return False

        logger.info(f"Session valid — landed on: {current_url}")
        return True
    except Exception as e:
        logger.error(f"Session check failed: {e}")
        return False


async def login_with_credentials(
    page: Page,
    login_url: str,
    email: str,
    password: str,
) -> bool:
    """Perform full login flow through Cirro SSO.

    Steps:
    1. Navigate to app.test.io/login
    2. Get redirected to Cirro SSO
    3. Fill in email + password
    4. Submit and wait for dashboard to load

    Returns True on success, False on failure.
    """
    try:
        logger.info(f"Navigating to login page: {login_url}")
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        current_url = page.url
        logger.info(f"Login page loaded: {current_url}")

        # Look for email input — try multiple selectors for Cirro SSO
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[name="user[email]"]',
            'input[id="user_email"]',
            '#email',
            'input[placeholder*="email" i]',
            'input[placeholder*="Email" i]',
        ]

        email_input = None
        for selector in email_selectors:
            try:
                email_input = await page.wait_for_selector(selector, timeout=3000)
                if email_input:
                    logger.info(f"Found email input with selector: {selector}")
                    break
            except Exception:
                continue

        if not email_input:
            logger.error("Could not find email input on login page")
            return False

        # Type email with realistic speed
        await email_input.click()
        for char in email:
            await email_input.type(char, delay=50)
            await typing_delay()

        # Look for password input
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[name="user[password]"]',
            'input[id="user_password"]',
            '#password',
        ]

        password_input = None
        for selector in password_selectors:
            try:
                password_input = await page.wait_for_selector(selector, timeout=3000)
                if password_input:
                    logger.info(f"Found password input with selector: {selector}")
                    break
            except Exception:
                continue

        if not password_input:
            logger.error("Could not find password input on login page")
            return False

        # Type password
        await password_input.click()
        for char in password:
            await password_input.type(char, delay=50)
            await typing_delay()

        # Look for and click the submit button
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Sign in")',
            'button:has-text("Log in")',
            'button:has-text("Login")',
            'button:has-text("Submit")',
            '[data-testid="login-button"]',
        ]

        submit_button = None
        for selector in submit_selectors:
            try:
                submit_button = await page.wait_for_selector(selector, timeout=3000)
                if submit_button:
                    logger.info(f"Found submit button with selector: {selector}")
                    break
            except Exception:
                continue

        if not submit_button:
            # Fallback: press Enter
            logger.warning("No submit button found — pressing Enter")
            await page.keyboard.press("Enter")
        else:
            await submit_button.click()

        # Wait for navigation after login
        logger.info("Login submitted — waiting for dashboard to load...")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Check if login succeeded
        current_url = page.url.lower()
        login_indicators = ["login", "sign_in", "signin", "cirro.io/users/sign_in", "auth"]
        still_on_login = any(indicator in current_url for indicator in login_indicators)

        if still_on_login:
            # Check for error messages
            error_selectors = ['.alert', '.error', '.flash', '[role="alert"]']
            for sel in error_selectors:
                try:
                    error_el = await page.query_selector(sel)
                    if error_el:
                        error_text = await error_el.text_content()
                        logger.error(f"Login failed with error: {error_text}")
                        return False
                except Exception:
                    continue
            logger.error(f"Login appears to have failed — still on: {current_url}")
            return False

        logger.info(f"✅ Login successful — now at: {current_url}")
        return True

    except Exception as e:
        logger.error(f"Login failed with exception: {e}")
        return False
