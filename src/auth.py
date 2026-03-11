"""LinkedIn auth — cookie persistence, validation, staleness checks.

Pattern from x-bookmark-to-substack: save full cookie objects from Patchright,
inject them on subsequent runs, validate by checking for login redirect.
"""

import json
import logging
import time
from datetime import datetime, timezone

from . import config

log = logging.getLogger(__name__)


def authenticate() -> list[dict]:
    """Launch browser, let user log in to LinkedIn, capture and save cookies.

    Returns the captured cookie list, or raises on failure.
    """
    from patchright.sync_api import sync_playwright

    print("\n--- LI Lite: LinkedIn Authentication ---")
    print("A Chrome window will open.")
    print("1. Log in to LinkedIn (supports 2FA)")
    print("2. Wait for the feed to load")
    print("3. Come back here and press Enter")
    print("-" * 40)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(config.CHROME_PROFILE_DIR),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(config.LINKEDIN_FEED)

        input("\n-> Press Enter when you're logged in and see the feed...")

        cookies = ctx.cookies([config.LINKEDIN_BASE])
        ctx.close()

    if not cookies:
        raise RuntimeError("No cookies captured from LinkedIn session")

    _save_cookies(cookies)
    log.info(f"Captured {len(cookies)} LinkedIn cookies")
    return cookies


def load_cookies() -> list[dict]:
    """Load saved LinkedIn cookies from file. Returns [] if none."""
    if not config.COOKIES_FILE.exists():
        return []
    try:
        with open(config.COOKIES_FILE) as f:
            data = json.load(f)
        return data.get("all_cookies", []) if isinstance(data, dict) else data
    except (json.JSONDecodeError, IOError) as e:
        log.error(f"Failed to load cookies: {e}")
        return []


def validate_session(page) -> bool:
    """Check if we're logged in after navigation (not redirected to login)."""
    time.sleep(3)

    if "/login" in page.url or "/checkpoint" in page.url:
        log.warning(f"Redirected to login: {page.url}")
        return False

    # Look for the feed — presence means we're authenticated
    try:
        page.wait_for_selector('[role="main"]', timeout=8000)
        return True
    except Exception:
        pass

    # Fallback: check for global nav
    try:
        page.wait_for_selector("#global-nav", timeout=5000)
        return True
    except Exception:
        pass

    log.warning("Could not confirm LinkedIn authentication")
    return False


def check_credentials_age() -> None:
    """Warn if credentials are getting stale."""
    if not config.COOKIES_FILE.exists():
        return
    age_days = (time.time() - config.COOKIES_FILE.stat().st_mtime) / 86400
    if age_days > config.CREDS_STALE_WARNING_DAYS:
        log.warning(
            f"LinkedIn cookies are {int(age_days)} days old — "
            "consider re-authenticating"
        )


def _save_cookies(cookies: list[dict]) -> None:
    """Save cookies with metadata."""
    config.COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "all_cookies": cookies,
    }
    with open(config.COOKIES_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Saved {len(cookies)} cookies to {config.COOKIES_FILE}")
