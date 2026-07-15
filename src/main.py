"""Test IO Auto-Accept Bot — Main Entry Point.

Usage:
    python -m src.main
"""
import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime

from rich.logging import RichHandler
from rich.console import Console

from .config import load_config, get_data_dir
from .bot.engine import TestIOBot

import uvicorn
from .dashboard.app import app
from .notifications.telegram import start_telegram_listener, stop_telegram_listener

console = Console()


def setup_logging() -> None:
    """Configure logging with both console (rich) and file output."""
    log_file = get_data_dir() / "bot.log"

    # Rich handler for pretty console output
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_path=False,
        markup=True,
    )
    rich_handler.setLevel(logging.INFO)

    # File handler for persistent logs
    file_handler = logging.FileHandler(
        str(log_file), encoding="utf-8", mode="a"
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[rich_handler, file_handler],
    )

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


def main():
    """Entry point — load config and start the bot."""
    # Force UTF-8 on Windows
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    setup_logging()
    logger = logging.getLogger(__name__)

    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/]")
    console.print("[bold cyan]║    Test IO Auto-Accept Bot v0.1.0    ║[/]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/]\n")

    try:
        config = load_config()
        logger.info("Configuration loaded")

        testio_config = config.get("testio", {})
        if not testio_config.get("enabled", True):
            console.print("[yellow]Bot is disabled in config.yaml — exiting[/]")
            return

        mode = testio_config.get("mode", "auto")
        headless = testio_config.get("headless", False)

        console.print(f"  Mode:     [bold]{'🔍 DRY RUN' if mode == 'dry-run' else '🚀 AUTO ACCEPT' if mode == 'auto' else mode.upper()}[/]")
        console.print(f"  Headless: [bold]{'Yes' if headless else 'No (browser visible)'}[/]")
        console.print(f"  Poll:     [bold]{testio_config.get('poll_interval_min', 20)}-{testio_config.get('poll_interval_max', 60)}s[/]")
        console.print(f"  Started:  [bold]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/]")
        console.print("")

        # Check credentials
        secrets = config.get("secrets", {})
        if not secrets.get("testio_email") or not secrets.get("testio_password"):
            console.print("[bold red]❌ TESTIO_EMAIL and TESTIO_PASSWORD must be set in .env[/]")
            console.print("[dim]Copy .env.template to .env and fill in your credentials[/]")
            return

        bot = TestIOBot(config)
        
        async def run_all():
            
            # Inject bot into the FastAPI app state so routes can access it
            app.state.bot = bot
            
            # Setup Uvicorn web server
            server_config = uvicorn.Config(app, host="0.0.0.0", port=8500, log_level="warning")
            server = uvicorn.Server(server_config)
            
            logger.info("Starting Dashboard at http://localhost:8500")
            
            # Initialize Stats Database
            from src.database.stats import init_db
            await init_db()
            
            # Start Email IMAP Listener for instant reload
            from src.email.listener import start_email_listener, stop_email_listener
            start_email_listener(config, bot.trigger_instant_reload)
            
            # Start telegram polling in the background
            await start_telegram_listener()
            
            # Start heartbeat (every 6h) and daily summary (midnight) notifiers
            from src.notifications.telegram import start_background_notifiers
            start_background_notifiers(config)
            
            try:
                # Run main blocking loops concurrently
                await asyncio.gather(
                    bot.start(),
                    server.serve()
                )
            finally:
                # Stop background tasks on shutdown
                await stop_telegram_listener()
                await stop_email_listener()
            
        asyncio.run(run_all())

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/]")
    except FileNotFoundError as e:
        console.print(f"[bold red]❌ {e}[/]")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        console.print(f"[bold red]❌ Fatal error: {e}[/]")


if __name__ == "__main__":
    main()
