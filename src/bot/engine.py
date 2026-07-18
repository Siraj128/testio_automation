"""TestIOBot — main engine that orchestrates everything."""
import asyncio
import logging
from datetime import datetime
from typing import Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .state import BotState, BotStatus
from .auth import login_with_credentials, load_session, save_session, is_session_valid
from .monitor import check_for_invitations, wait_for_next_poll
from .acceptor import accept_test
from ..stealth.patches import apply_stealth_to_context
from ..stealth.fingerprint import build_browser_context_options, get_webgl_spoof_script
from ..screenshots.manager import capture, cleanup_old
from ..intercept.capture import setup_network_interception
from ..config import get_data_dir
from ..database.stats import increment_refresh, increment_accepted, increment_failed

logger = logging.getLogger(__name__)

# Singleton reference for dashboard/telegram control
_bot_instance: "TestIOBot | None" = None


def get_bot() -> "TestIOBot | None":
    return _bot_instance


class TestIOBot:
    """Main Test IO Auto-Accept Bot.

    Lifecycle:
    1. start() → launches browser, authenticates, enters monitor loop
    2. monitor loop polls dashboard → detects invitations → instant accept
    3. stop() → graceful shutdown
    """

    def __init__(self, config: dict[str, Any]):
        global _bot_instance
        self.config = config
        self.status = BotStatus()
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._running = False
        self._paused = False
        self._instant_reload_event = asyncio.Event()
        _bot_instance = self

    @property
    def testio_config(self) -> dict:
        return self.config.get("testio", {})

    @property
    def dashboard_url(self) -> str:
        return self.testio_config.get("dashboard_url", "https://tester.test.io")

    @property
    def login_url(self) -> str:
        return self.testio_config.get("login_url", "https://tester.test.io")

    @property
    def is_dry_run(self) -> bool:
        return self.testio_config.get("mode", "auto") == "dry-run"

    async def start(self) -> None:
        """Launch browser, authenticate, and start the monitoring loop."""
        logger.info("🚀 Starting Test IO Auto-Accept Bot...")
        self.status.set_state(BotState.STARTING)
        self._running = True
        
        try:
            from ..notifications.telegram import notify_status
            await notify_status("🚀 *System Online*\nTest IO Auto-Accept Bot is starting up...", self.config)
        except Exception:
            pass

        try:
            # Launch Playwright + browser
            self._playwright = await async_playwright().start()

            headless = self.testio_config.get("headless", False)
            logger.info(f"Launching Chromium (headless={headless})")

            # Use a persistent user profile (Cache, LocalStorage, History, IndexedDB)
            # This makes the bot virtually indistinguishable from a real installed Chrome browser
            profile_dir = get_data_dir() / "browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info("Loading persistent Chrome profile...")

            # Create context with realistic fingerprints
            context_options = build_browser_context_options(self.config)

            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                **context_options
            )

            # Apply stealth patches to all pages
            await apply_stealth_to_context(self._context)

            # Apply WebGL spoof
            webgl_script = get_webgl_spoof_script()
            await self._context.add_init_script(webgl_script)

            # Get the default page created by the persistent context
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

            # Setup network interception to learn API signatures
            setup_network_interception(self._page)

            # Authenticate
            await self._authenticate()

            # Start the monitoring loop
            await self._monitor_loop()

        except asyncio.CancelledError:
            logger.info("Bot was cancelled")
        except Exception as e:
            logger.error(f"Bot crashed: {e}", exc_info=True)
            self.status.set_state(BotState.ERROR, str(e))
        finally:
            await self.stop()

    async def _authenticate(self) -> None:
        """Ensure we have a valid session — login if needed."""
        self.status.set_state(BotState.LOGGING_IN)

        # Check if saved session is still valid
        logger.info("Checking session validity...")
        session_valid = await is_session_valid(self._page, self.dashboard_url)

        if session_valid:
            self.status.session_valid = True
            logger.info("✅ Existing session is valid — skipping login")
            await capture(self._page, "session_valid")
            return

        # Need to login
        logger.info("Session invalid or expired — logging in...")
        secrets = self.config.get("secrets", {})
        email = secrets.get("testio_email", "")
        password = secrets.get("testio_password", "")

        if not email or not password:
            raise ValueError(
                "TESTIO_EMAIL and TESTIO_PASSWORD must be set in .env"
            )

        success = await login_with_credentials(
            self._page, self.login_url, email, password
        )

        if not success:
            await capture(self._page, "login_failed")
            raise RuntimeError("Login failed — check credentials")

        # Save session for future restarts
        await save_session(self._context)
        self.status.session_valid = True
        await capture(self._page, "login_success")
        logger.info("✅ Logged in and session saved")
        
        try:
            from ..notifications.telegram import notify_status
            await notify_status("✅ *Login Successful*\nSession saved securely.", self.config)
        except Exception:
            pass

    async def _monitor_loop(self) -> None:
        """Main polling loop — check for invitations and accept instantly."""
        self.status.set_state(BotState.IDLE)
        logger.info("🔄 Entering monitoring loop...")
        mode = self.testio_config.get("mode", "auto")
        logger.info(f"Mode: {mode}")

        max_active = self.testio_config.get("max_active_tests", 2)
        _last_schedule_mode = None  # Track schedule transitions

        while self._running:
            # Check if paused
            if self._paused:
                self.status.set_state(BotState.PAUSED)
                await asyncio.sleep(2)
                continue
                
            # Check schedule
            schedule_config = self.testio_config.get("schedule", {})
            schedule_mode = "normal"
            
            if schedule_config.get("enabled", False):
                import zoneinfo
                tz_str = self.config.get("stealth", {}).get("timezone", "UTC")
                try:
                    tz = zoneinfo.ZoneInfo(tz_str)
                except Exception:
                    tz = None
                    
                now = datetime.now(tz).strftime("%H:%M")
                periods = schedule_config.get("periods", [])
                for period in periods:
                    start_time = period.get("start", "00:00")
                    end_time = period.get("end", "23:59")
                    
                    in_period = False
                    if start_time <= end_time:
                        in_period = start_time <= now <= end_time
                    else: # Overnight shift
                        in_period = now >= start_time or now <= end_time
                        
                    if in_period:
                        schedule_mode = period.get("mode", "normal")
                        break
                        
                # Notify on schedule mode transitions
                if _last_schedule_mode is not None and schedule_mode != _last_schedule_mode:
                    try:
                        from ..notifications.telegram import notify_schedule_change
                        await notify_schedule_change(schedule_mode.title(), schedule_mode, self.config)
                    except Exception:
                        pass
                _last_schedule_mode = schedule_mode

                if schedule_mode == "sleep":
                    if self.status.state != BotState.SLEEPING:
                        logger.info("Schedule mode is 'sleep'. Going to sleep...")
                        try:
                            from ..notifications.telegram import notify_status
                            await notify_status("😴 *Sleep Mode*\nSchedule says sleep. Going dark...", self.config)
                        except Exception:
                            pass
                    self.status.set_state(BotState.SLEEPING)
                    await asyncio.sleep(60)
                    continue
                else:
                    if self.status.state == BotState.SLEEPING:
                        try:
                            from ..notifications.telegram import notify_status
                            await notify_status("☀️ *Good Morning!*\nWaking up from sleep mode.", self.config)
                        except Exception:
                            pass

            try:
                # Poll for invitations
                self.status.set_state(BotState.CHECKING)
                await increment_refresh()
                invitations = await check_for_invitations(
                    self._page, self.dashboard_url, self.config
                )

                if not invitations:
                    # Check if session expired (monitor returns empty + redirect)
                    current_url = self._page.url.lower()
                    if any(x in current_url for x in ["login", "sign_in", "cirro"]):
                        logger.warning("Session expired — re-authenticating...")
                        try:
                            from ..notifications.telegram import notify_status
                            await notify_status("⚠️ *Session Expired*\nRe-authenticating...", self.config)
                        except Exception:
                            pass
                        await self._authenticate()
                        try:
                            from ..notifications.telegram import notify_reauth_success
                            await notify_reauth_success(self.config)
                        except Exception:
                            pass
                        continue

                    self.status.set_state(BotState.IDLE)
                    await self._wait_for_next_poll_or_trigger(schedule_mode)
                    continue

                # Check if we've hit the active test limit
                if self.status.active_test_count >= max_active:
                    logger.info(
                        f"At max active tests ({max_active}) — skipping"
                    )
                    try:
                        from ..notifications.telegram import notify_status
                        await notify_status(f"🛑 *Limit Reached*\nMax active tests ({max_active}) reached. Pausing accepts.", self.config)
                    except Exception:
                        pass
                    self.status.set_state(BotState.IDLE)
                    await self._wait_for_next_poll_or_trigger(schedule_mode)
                    continue

                # ⚡ TEST FOUND — ACCEPT INSTANTLY
                for invitation in invitations:
                    if not self._running:
                        break
                    if self.status.active_test_count >= max_active:
                        logger.info("Reached max active tests — stopping acceptance")
                        break

                    self.status.set_state(BotState.FOUND_TEST)

                    # 🔍 Notify: Test Spotted!
                    try:
                        test_name_preview = (await invitation.text_content() or "Unknown").strip()[:100]
                        from ..notifications.telegram import notify_test_spotted
                        await notify_test_spotted(test_name_preview, self.config)
                    except Exception:
                        pass

                    self.status.set_state(BotState.ACCEPTING)

                    result = await accept_test(
                        self._page,
                        invitation,
                        dry_run=self.is_dry_run,
                    )

                    if result["success"]:
                        self.status.set_state(BotState.ACCEPTED)
                        await increment_accepted()
                        self.status.current_test_name = result["test_name"]
                        self.status.active_test_count += 1
                        logger.info(
                            f"🎉 Accepted: {result['test_name']} "
                            f"(total today: {self.status.tests_accepted_today})"
                        )

                        # Try to send notification (import here to avoid circular)
                        try:
                            from ..notifications.telegram import notify_accepted
                            await notify_accepted(
                                result["test_name"],
                                result.get("screenshot_path"),
                                self.config,
                            )
                        except ImportError:
                            pass  # Notifications module not yet built
                        except Exception as e:
                            logger.warning(f"Notification failed: {e}")
                    else:
                        self.status.set_state(
                            BotState.FAILED, result.get("error", "Unknown")
                        )
                        await increment_failed()
                        logger.warning(
                            f"❌ Failed: {result['test_name']} — {result['error']}"
                        )
                        try:
                            from ..notifications.telegram import notify_error
                            await notify_error(
                                result.get("error", "Unknown"),
                                result.get("screenshot_path"),
                                self.config,
                            )
                        except ImportError:
                            pass
                        except Exception as e:
                            logger.warning(f"Error notification failed: {e}")

                    # Navigate back to dashboard for next invitation
                    await self._page.goto(
                        self.dashboard_url,
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )

                # Return to idle
                self.status.set_state(BotState.IDLE)
                await self._wait_for_next_poll_or_trigger(schedule_mode)

            except Exception as e:
                logger.error(f"Monitor loop error: {e}", exc_info=True)
                self.status.set_state(BotState.ERROR, str(e))

                # 🔄 Notify: Crash Recovery
                try:
                    from ..notifications.telegram import notify_crash_recovery
                    await notify_crash_recovery(str(e), self.config)
                except Exception:
                    pass

                # Try to recover
                try:
                    await capture(self._page, "error_recovery")
                except Exception:
                    pass

                # Wait before retrying
                await asyncio.sleep(30)

                # Try re-authenticating
                try:
                    await self._authenticate()
                    try:
                        from ..notifications.telegram import notify_reauth_success
                        await notify_reauth_success(self.config)
                    except Exception:
                        pass
                except Exception as auth_err:
                    logger.error(f"Re-auth failed: {auth_err}")
                    await asyncio.sleep(60)

        logger.info("Monitor loop ended")

    async def stop(self) -> None:
        """Graceful shutdown — save session and close browser."""
        logger.info("Stopping bot...")
        self._running = False

        try:
            if self._context:
                await save_session(self._context)
        except Exception as e:
            logger.error(f"Failed to save session on stop: {e}")

        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        self.status.set_state(BotState.STOPPED)
        logger.info("Bot stopped")
        try:
            from ..notifications.telegram import notify_status
            await notify_status("🛑 *System Offline*\nBot has been stopped.", self.config)
        except Exception:
            pass

    # --- Control methods (called by dashboard/telegram) ---

    def pause(self) -> None:
        """Pause the monitoring loop."""
        self._paused = True
        self.status.set_state(BotState.PAUSED)
        logger.info("Bot paused")

    def resume(self) -> None:
        """Resume the monitoring loop."""
        self._paused = False
        self.status.set_state(BotState.IDLE)
        logger.info("Bot resumed")

    def set_dry_run(self, enabled: bool) -> None:
        """Toggle dry-run mode at runtime."""
        self.config.setdefault("testio", {})["mode"] = "dry-run" if enabled else "auto"
        logger.info(f"Dry-run mode: {'ON' if enabled else 'OFF'}")

    async def force_screenshot(self) -> str | None:
        """Take and return a screenshot of the current page."""
        if self._page:
            path = await capture(self._page, "manual_screenshot")
            return str(path) if path else None
        return None

    async def restart_session(self) -> None:
        """Force re-authentication."""
        logger.info("Forcing session restart...")
        if self._page:
            await self._authenticate()

    async def _wait_for_next_poll_or_trigger(self, schedule_mode: str) -> None:
        """Wait for the next poll, but return early if the instant reload event is triggered."""
        self._instant_reload_event.clear()
        
        poll_task = asyncio.create_task(wait_for_next_poll(self.config, schedule_mode))
        trigger_task = asyncio.create_task(self._instant_reload_event.wait())
        
        done, pending = await asyncio.wait(
            [poll_task, trigger_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for p in pending:
            p.cancel()

    def trigger_instant_reload(self) -> None:
        """Interrupt the current delay and force an immediate dashboard refresh."""
        if not self._instant_reload_event.is_set():
            logger.info("⚡ Instant reload triggered by external event!")
            self._instant_reload_event.set()

    def set_poll_speed(self, min_sec: int, max_sec: int) -> None:
        """Dynamically adjust the polling interval in memory."""
        self.config.setdefault("testio", {})["poll_interval_min"] = min_sec
        self.config["testio"]["poll_interval_max"] = max_sec
        logger.info(f"🏎️ Polling speed set to: {min_sec}-{max_sec}s")
        # Wake up immediately to adopt new speed
        self.trigger_instant_reload()

    def reset_poll_speed(self) -> None:
        """Reset polling speed back to the defaults defined in config.yaml."""
        from ..config import load_config
        fresh_config = load_config()
        min_sec = fresh_config.get("testio", {}).get("poll_interval_min", 30)
        max_sec = fresh_config.get("testio", {}).get("poll_interval_max", 90)
        
        self.config.setdefault("testio", {})["poll_interval_min"] = min_sec
        self.config["testio"]["poll_interval_max"] = max_sec
        logger.info(f"🔄 Polling speed reset to config.yaml schedule defaults: {min_sec}-{max_sec}s")
        self.trigger_instant_reload()
