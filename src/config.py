"""Load config.yaml and merge with environment variables."""
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"


def load_config() -> dict[str, Any]:
    """Load config.yaml and merge with .env secrets."""
    load_dotenv(ENV_PATH)

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found at {CONFIG_PATH}. "
            "Copy config.yaml.example and fill in your details."
        )

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # Merge secrets from environment
    config["secrets"] = {
        "testio_email": os.getenv("TESTIO_EMAIL", ""),
        "testio_password": os.getenv("TESTIO_PASSWORD", ""),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "proxy_url": os.getenv("PROXY_URL", ""),
    }

    # Ensure data directories exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "browser_state").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "screenshots").mkdir(parents=True, exist_ok=True)

    return config


def get_data_dir() -> Path:
    """Return the data directory path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
