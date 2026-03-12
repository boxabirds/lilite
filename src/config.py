"""Configuration management. Loads from .env and provides paths."""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Paths ---
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
AUTH_DIR = DATA_DIR / "auth"
CONFIG_DIR = PROJECT_ROOT / "config" / "linkedin.com"

COOKIES_FILE = AUTH_DIR / "linkedin_cookies.json"
CHROME_PROFILE_DIR = AUTH_DIR / "linkedin_chrome_profile"

# Ensure directories exist
for d in [AUTH_DIR, CONFIG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- Telegram (optional) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Auth ---
CREDS_STALE_WARNING_DAYS = int(os.getenv("CREDS_STALE_WARNING_DAYS", "14"))

# --- Discovery ---
DISCOVERY_NAV_DEPTH = int(os.getenv("DISCOVERY_NAV_DEPTH", "1"))
DISCOVERY_PAGE_LOAD_TIMEOUT_MS = int(os.getenv("DISCOVERY_PAGE_LOAD_TIMEOUT_MS", "60000"))
DISCOVERY_IDLE_WAIT_MS = int(os.getenv("DISCOVERY_IDLE_WAIT_MS", "10000"))
DISCOVERY_SCROLL_DISTANCE_PX = int(os.getenv("DISCOVERY_SCROLL_DISTANCE_PX", "2000"))
DISCOVERY_SCROLL_SETTLE_MS = int(os.getenv("DISCOVERY_SCROLL_SETTLE_MS", "3000"))
# Minimum element dimension (px) to include in snapshots
DISCOVERY_MIN_ELEMENT_SIZE_PX = 10

# --- Gemini LLM ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-flash-latest")

# --- LinkedIn ---
LINKEDIN_BASE = "https://www.linkedin.com"
LINKEDIN_FEED = f"{LINKEDIN_BASE}/feed/"
