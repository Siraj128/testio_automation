"""Replays API requests for fast test acceptance."""
import logging
from playwright.async_api import Page
from .capture import get_learned_signature

logger = logging.getLogger(__name__)

async def fast_accept_test(page: Page, test_id: str) -> bool:
    """Attempt to accept a test by injecting the raw API request.
    
    Args:
        page: The active Playwright page (contains auth context).
        test_id: The ID of the test we want to accept.
        
    Returns:
        True if successfully accepted via API, False to fallback to UI clicker.
    """
    signature = get_learned_signature()
    
    if not signature:
        logger.warning("No API signature learned yet. Falling back to UI clicker.")
        return False
        
    logger.info(f"⚡ FAST ACCEPT: Injecting raw API request for test {test_id}...")
    
    try:
        url = signature["url"]
        method = signature["method"]
        headers = signature["headers"]
        payload_str = signature.get("payload", "")
        
        # WARNING: This is a simplistic naive replacement.
        # If the payload contains the test ID, we need to inject the new test_id.
        # But we don't know the original test ID that was captured!
        # We will need the user to manually verify api_signatures.json first.
        
        # For safety, until we have inspected a real signature, we will abort
        # and fallback to the UI.
        logger.warning("🚨 FAST ACCEPT ABORTED: Cannot replay blindly until we analyze the first captured signature.")
        logger.warning("Please check data/api_signatures.json when it appears!")
        
        return False
        
        # The real code would look something like this:
        # response = await page.request.fetch(
        #     url,
        #     method=method,
        #     headers=headers,
        #     data=payload_str # modified with new test_id
        # )
        # return response.ok
        
    except Exception as e:
        logger.error(f"Fast accept failed: {e}")
        return False
