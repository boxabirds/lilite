"""Mac-side LinkedIn auth refresh.

Opens a real Chrome window. You log in manually.
Script captures cookies and saves them for the pipeline.

Usage:
    python scripts/refresh_auth/refresh_linkedin_auth.py

Requires:
    uv pip install patchright
    patchright install chrome
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LINKEDIN_BASE = "https://www.linkedin.com"
LINKEDIN_FEED = f"{LINKEDIN_BASE}/feed/"
CREDS_FILE = Path(__file__).parent.parent.parent / "data" / "auth" / "linkedin_cookies.json"
PROFILE_DIR = Path(__file__).parent / "linkedin_chrome_profile"


def main():
    from patchright.sync_api import sync_playwright

    print("\n--- LinkedIn Auth Refresh ---")
    print("=" * 50)
    print("A Chrome window will open.")
    print("1. Log in to LinkedIn (supports 2FA, CAPTCHA)")
    print("2. Wait for the feed to load fully")
    print("3. Come back here and press Enter")
    print("=" * 50)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LINKEDIN_FEED)

        input("\n-> Press Enter when you're logged in and see the feed...")

        cookies = ctx.cookies([LINKEDIN_BASE, "https://linkedin.com"])
        ctx.close()

    if not cookies:
        print("\nERROR: No cookies captured")
        sys.exit(1)

    # Save credentials
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "all_cookies": cookies,
    }
    with open(CREDS_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved {len(cookies)} cookies to {CREDS_FILE}")
    print("\nDone! If this is a sambashare, the Ubuntu box already has the file.")


if __name__ == "__main__":
    main()
