"""Browser fingerprint management — UA rotation, viewport, WebGL spoofing."""
import random
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Real Chrome User-Agent strings (kept current)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

# WebGL renderer/vendor pairs from real machines
WEBGL_RENDERERS = [
    ("Intel Inc.", "Intel Iris OpenGL Engine"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
]


def get_random_user_agent() -> str:
    """Return a random real Chrome user-agent string."""
    ua = random.choice(USER_AGENTS)
    logger.debug(f"Selected UA: {ua[:60]}...")
    return ua


def get_random_webgl() -> tuple[str, str]:
    """Return a random WebGL vendor/renderer pair."""
    return random.choice(WEBGL_RENDERERS)


def build_browser_context_options(config: dict[str, Any]) -> dict[str, Any]:
    """Build Playwright browser context options with realistic fingerprints."""
    stealth_config = config.get("stealth", {})

    user_agent = get_random_user_agent()
    viewport_width = stealth_config.get("viewport_width", 1920)
    viewport_height = stealth_config.get("viewport_height", 1080)
    timezone = stealth_config.get("timezone", "Asia/Kolkata")
    locale = stealth_config.get("locale", "en-US")

    options: dict[str, Any] = {
        "user_agent": user_agent,
        "viewport": {"width": viewport_width, "height": viewport_height},
        "timezone_id": timezone,
        "locale": locale,
        "color_scheme": "light",
        "has_touch": False,
        "is_mobile": False,
        "java_script_enabled": True,
        "ignore_https_errors": True,
        # Permissions that a normal user would have
        "permissions": ["geolocation"],
    }

    # Proxy support
    proxy_config = stealth_config.get("proxy", {})
    if proxy_config.get("enabled") and proxy_config.get("url"):
        proxy_url = proxy_config["url"]
        options["proxy"] = {"server": proxy_url}
        logger.info(f"Proxy enabled: {proxy_url[:30]}...")

    logger.info(
        f"Browser context: {viewport_width}x{viewport_height}, "
        f"tz={timezone}, locale={locale}"
    )
    return options


def get_webgl_spoof_script() -> str:
    """Generate a JS script to spoof WebGL vendor/renderer."""
    vendor, renderer = get_random_webgl()
    return f"""
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
        if (parameter === 37445) return '{vendor}';
        if (parameter === 37446) return '{renderer}';
        return getParameter.call(this, parameter);
    }};
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
        if (parameter === 37445) return '{vendor}';
        if (parameter === 37446) return '{renderer}';
        return getParameter2.call(this, parameter);
    }};
    """
