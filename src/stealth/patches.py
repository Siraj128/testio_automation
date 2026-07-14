"""Playwright stealth patches — masks automation fingerprints."""
import logging
from playwright.async_api import Page, BrowserContext

logger = logging.getLogger(__name__)


# JavaScript to inject before any page script runs
STEALTH_SCRIPTS = [
    # 1. Mask navigator.webdriver
    """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
    """,

    # 2. Mask chrome automation indicators
    """
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
    };
    """,

    # 3. Override permissions query to avoid headless detection
    """
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
    """,

    # 4. Mask plugins to look like a real browser
    """
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ],
    });
    """,

    # 5. Mask languages
    """
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });
    """,

    # 6. Prevent iframe contentWindow detection
    """
    const originalAttachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function() {
        return originalAttachShadow.apply(this, arguments);
    };
    """,

    # 7. Fix broken outerWidth/outerHeight in headless
    """
    if (window.outerWidth === 0) {
        Object.defineProperty(window, 'outerWidth', { get: () => window.innerWidth });
    }
    if (window.outerHeight === 0) {
        Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 85 });
    }
    """,
]


async def apply_stealth_scripts(page: Page) -> None:
    """Inject all stealth scripts into the page before any content loads."""
    for script in STEALTH_SCRIPTS:
        await page.add_init_script(script)
    logger.debug("Stealth scripts injected into page")


async def apply_stealth_to_context(context: BrowserContext) -> None:
    """Apply stealth scripts to a browser context (all pages created from it)."""
    combined_script = "\n".join(STEALTH_SCRIPTS)
    await context.add_init_script(combined_script)
    logger.debug("Stealth scripts injected into browser context")
