import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Test IO Auto-Accept Dashboard")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Mount screenshots directory to serve images directly
project_root = BASE_DIR.parent.parent
screenshots_dir = project_root / "data" / "screenshots"
screenshots_dir.mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(screenshots_dir)), name="screenshots")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the main dashboard HTML."""
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={},
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

from src.database.stats import get_today

@app.get("/api/status")
async def get_status(request: Request):
    """Get the current status of the bot."""
    bot = request.app.state.bot
    data = bot.status.to_dict()
    data["is_paused"] = bot._paused
    
    # Pull persistent stats from SQLite database to override in-memory counters
    db_stats = await get_today()
    data["poll_count"] = db_stats["refreshes"]
    data["tests_accepted_today"] = db_stats["accepted"]
    data["tests_failed"] = db_stats["failed"]
    
    return data

@app.post("/api/pause")
async def pause_bot(request: Request):
    """Pause the bot."""
    bot = request.app.state.bot
    bot.pause()
    return {"status": "paused"}

@app.post("/api/resume")
async def resume_bot(request: Request):
    """Resume the bot."""
    bot = request.app.state.bot
    bot.resume()
    return {"status": "resumed"}

@app.get("/api/screenshots")
async def list_screenshots():
    """List recent screenshots."""
    # Find all png files recursively (since they are saved in date folders)
    files = list(screenshots_dir.rglob("*.png"))
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    # Return relative paths for the top 10
    return {"screenshots": [f.relative_to(screenshots_dir).as_posix() for f in files[:10]]}
