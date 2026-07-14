"""Captures Test IO API requests to learn their signature."""
import logging
import json
from pathlib import Path
from playwright.async_api import Page, Request

from ..config import get_data_dir

logger = logging.getLogger(__name__)

def get_signatures_file() -> Path:
    return get_data_dir() / "api_signatures.json"

def get_learned_signature() -> dict | None:
    """Load the learned API signature if it exists."""
    sig_file = get_signatures_file()
    if sig_file.exists():
        try:
            # For MVP, just return the most recently captured signature
            signatures = json.loads(sig_file.read_text(encoding="utf-8"))
            if signatures and len(signatures) > 0:
                return signatures[-1]
        except Exception:
            return None
    return None

async def _on_request(request: Request):
    """Event handler for all outgoing requests."""
    # We only care about POST/PUT/PATCH mutations
    if request.method not in ["POST", "PUT", "PATCH"]:
        return
        
    url = request.url
    
    # Filter out obvious analytics/tracking
    if any(x in url for x in ["google", "hotjar", "sentry", "nr-data", "datadog", "pendo"]):
        return
        
    # We want to capture the test acceptance request.
    # Since we don't know the exact endpoint, we capture potential matches.
    if "test.io" in url and ("api" in url or "graphql" in url or "accept" in url or "invitations" in url or "cycles" in url):
        try:
            post_data = request.post_data
            headers = request.headers
            
            # Don't save duplicate identical requests if it polls the same thing
            if post_data is None:
                return
                
            logger.info(f"🕵️ CAPTURED API REQUEST: {request.method} {url}")
            
            sig_file = get_signatures_file()
            signatures = []
            if sig_file.exists():
                try:
                    signatures = json.loads(sig_file.read_text(encoding="utf-8"))
                except:
                    signatures = []
                    
            signatures.append({
                "url": url,
                "method": request.method,
                # Strip pseudo-headers (like :authority) which httpx/requests reject
                "headers": {k: v for k, v in headers.items() if not k.startswith(":")}, 
                "payload": post_data
            })
            
            # Keep only the last 10 signatures to avoid massive files
            signatures = signatures[-10:]
            
            sig_file.write_text(json.dumps(signatures, indent=2), encoding="utf-8")
            
        except Exception as e:
            logger.error(f"Failed to capture request: {e}")

def setup_network_interception(page: Page) -> None:
    """Attach the request listener to the page."""
    page.on("request", _on_request)
    logger.info("Network interception active — listening for API signatures...")
