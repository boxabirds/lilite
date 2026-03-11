# LI Lite — Baseline Spec

Strip LinkedIn down to what you actually use. LI Lite discovers every UI component and API call on your LinkedIn home page, lets you choose what stays, and builds a Chrome extension that removes the rest.

## Architecture

Built on the same browser automation stack as [x-bookmark-to-substack](../x-bookmark-to-substack):

- **Patchright** (Playwright wrapper) for browser control
- Persistent Chrome profiles for session reuse
- Cookie extraction/injection for auth persistence
- Request/response interception for API discovery

## Phases

### Phase A: Auth

Authenticate with LinkedIn and persist credentials for reuse.

**Flow:**
1. Launch Patchright with a persistent Chrome profile at `data/auth/linkedin_chrome_profile/`
2. Navigate to `linkedin.com/login`
3. User logs in manually (supports 2FA, CAPTCHA — no automation of the login form)
4. On successful navigation to the feed, extract and save all cookies to `data/auth/linkedin_cookies.json`
5. Validate auth on subsequent runs by loading cookies and checking for a 200 on `/feed`

**Credential format** (`data/auth/linkedin_cookies.json`):
```json
{
  "captured_at": "2026-03-11T10:00:00Z",
  "all_cookies": [
    {"name": "li_at", "value": "...", "domain": ".linkedin.com", ...}
  ]
}
```

**Reuse pattern:** On next run, inject saved cookies into a fresh context. If `/feed` returns a redirect to `/login`, prompt the user to re-authenticate.

---

### Phase B: Discovery

Explore the authenticated LinkedIn home page, cataloguing every distinct UI component and every API/network call.

**Flow:**
1. Load auth cookies (from Phase A)
2. Navigate to `linkedin.com/feed`
3. Intercept **all network requests/responses** via `page.on("request")` / `page.on("response")`:
   - URL, method, request headers (sans cookie values), response status, content-type
   - Classify each as: `graphql` | `rest-api` | `static-asset` | `tracking-pixel` | `analytics` | `ad-network` | `websocket` | `other`
   - For tracking/analytics, record the vendor (e.g. `google-analytics`, `linkedin-insight`, `doubleclick`)
4. Walk the DOM to identify **stable, distinct UI components**:
   - Use semantic selectors: `[data-test-id]`, `[data-control-name]`, `section`, `aside`, landmark roles
   - For each component: CSS selector path, bounding box, visible text summary, screenshot thumbnail (optional)
   - Classify each as: `navigation` | `feed-card` | `sidebar-widget` | `modal` | `ad-unit` | `promoted-content` | `messaging` | `notification` | `footer` | `other`
5. Click every **top-level navigation link** and repeat steps 3–4 on each destination (bounded to same-origin, max depth 1)
6. Save results to `config/linkedin.com/<datestamp>-discovery.json`

**Discovery output format:**
```json
{
  "discovered_at": "2026-03-11T10:05:00Z",
  "pages": [
    {
      "url": "https://www.linkedin.com/feed/",
      "ui_components": [
        {
          "id": "feed-sort-toggle",
          "selector": "div[data-control-name='feed_sort_toggle']",
          "classification": "navigation",
          "description": "Toggle between Top and Recent feed sorting",
          "bounding_box": {"x": 200, "y": 150, "w": 120, "h": 40},
          "scope": "url:https://www.linkedin.com/feed/"
        }
      ],
      "api_calls": [
        {
          "id": "feed-updates",
          "url_pattern": "https://www.linkedin.com/voyager/api/feed/updates",
          "method": "GET",
          "classification": "rest-api",
          "description": "Fetches main feed content",
          "scope": "url-pattern:linkedin.com/voyager/api/feed/*"
        },
        {
          "id": "li-tracking-pixel",
          "url_pattern": "https://px.ads.linkedin.com/*",
          "method": "GET",
          "classification": "tracking-pixel",
          "vendor": "linkedin-ads",
          "description": "LinkedIn advertising tracker",
          "scope": "url-pattern:px.ads.linkedin.com/*"
        }
      ]
    }
  ]
}
```

**Scope assignment:** Each component and API call is assigned a scope — the URL or URL pattern where it was observed. This scope carries through to configuration and build phases.

---

### Phase C: Configure

Present discovery results to the user for interactive enable/disable decisions.

**Flow:**
1. Load the most recent `config/linkedin.com/<datestamp>-discovery.json`
2. Display a terminal menu (e.g. via `rich` or `inquirer`) grouped by page, then by classification:
   ```
   linkedin.com/feed/
   ├─ Navigation
   │  ├─ [x] Main nav bar — Top-level site navigation
   │  ├─ [x] Feed sort toggle — Toggle between Top and Recent
   │  └─ [x] Search bar — Global search
   ├─ Feed Cards
   │  ├─ [x] Post card — User/company posts in feed
   │  ├─ [ ] Promoted post — Sponsored content in feed
   │  └─ [x] Poll card — Interactive polls
   ├─ Sidebar Widgets
   │  ├─ [x] Profile card — Your profile summary
   │  ├─ [ ] LinkedIn News — Trending articles sidebar
   │  └─ [ ] People You May Know — Connection suggestions
   ├─ API Calls
   │  ├─ [x] Feed updates — Core feed data
   │  ├─ [ ] Ad serving — Delivers sponsored content
   │  └─ [ ] Analytics beacon — Usage tracking
   └─ Tracking / Analytics
      ├─ [ ] LinkedIn Insight Tag — linkedin-insight
      ├─ [ ] Google Analytics — google-analytics
      └─ [ ] DoubleClick — doubleclick
   ```
3. Sensible defaults: core content and navigation enabled; ads, promoted content, tracking pixels, and analytics disabled
4. User toggles items on/off, then confirms
5. Save to `config/linkedin.com/<datestamp>-configuration.json`

**Configuration output format:**
```json
{
  "configured_at": "2026-03-11T10:10:00Z",
  "based_on_discovery": "2026-03-11-discovery.json",
  "rules": [
    {
      "id": "li-tracking-pixel",
      "type": "api_call",
      "action": "block",
      "scope": "url-pattern:px.ads.linkedin.com/*",
      "description": "LinkedIn advertising tracker"
    },
    {
      "id": "promoted-post",
      "type": "ui_component",
      "action": "hide",
      "selector": "div[data-control-name='sponsored_update']",
      "scope": "url:https://www.linkedin.com/feed/",
      "description": "Sponsored content in feed"
    },
    {
      "id": "feed-updates",
      "type": "api_call",
      "action": "allow",
      "scope": "url-pattern:linkedin.com/voyager/api/feed/*",
      "description": "Core feed data"
    }
  ]
}
```

---

### Phase D: Build

Generate a Chrome extension from the configuration that hides unwanted UI and blocks unwanted network calls.

**Output:** `config/linkedin.com/<datestamp>-build/` containing a loadable Chrome extension.

**Extension structure:**
```
<datestamp>-build/
├── manifest.json          # Manifest V3
├── background.js          # Service worker: declarativeNetRequest rules
├── content.js             # Content script: CSS injection + DOM mutation observer
├── styles.css             # Hide rules for UI components
├── rules.json             # declarativeNetRequest rule definitions
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

**Mechanisms:**

| User choice | Implementation |
|---|---|
| Hide UI component | CSS `display:none` rule in `styles.css`, plus `MutationObserver` in `content.js` for dynamically loaded elements |
| Block API call | `declarativeNetRequest` rule in `rules.json` (Manifest V3) |
| Block tracker | `declarativeNetRequest` rule in `rules.json` |

**manifest.json sketch:**
```json
{
  "manifest_version": 3,
  "name": "LI Lite",
  "version": "1.0.0",
  "description": "A lighter LinkedIn experience",
  "permissions": ["declarativeNetRequest", "activeTab"],
  "host_permissions": ["*://*.linkedin.com/*"],
  "content_scripts": [
    {
      "matches": ["*://*.linkedin.com/*"],
      "css": ["styles.css"],
      "js": ["content.js"],
      "run_at": "document_start"
    }
  ],
  "declarative_net_request": {
    "rule_resources": [
      {"id": "block_rules", "enabled": true, "path": "rules.json"}
    ]
  },
  "background": {
    "service_worker": "background.js"
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

**Content script behaviour:**
- Inject `styles.css` at `document_start` to prevent flash of unwanted content
- `MutationObserver` watches for dynamically inserted nodes matching configured selectors
- Scoped to URL patterns from configuration (only activate rules on matching pages)

**Loading the extension:**
1. Open `chrome://extensions`
2. Enable "Developer mode"
3. Click "Load unpacked" and select the `<datestamp>-build/` directory

---

## Project Structure

```
lilite/
├── LICENSE
├── pyproject.toml
├── docs/
│   └── baseline-spec.md
├── src/
│   ├── auth.py              # Phase A: LinkedIn authentication
│   ├── discovery.py          # Phase B: UI + API discovery
│   ├── configure.py          # Phase C: Interactive configuration
│   └── build.py              # Phase D: Chrome extension generation
├── config/
│   └── linkedin.com/         # Discovery, config, and build outputs
├── data/
│   └── auth/
│       ├── linkedin_chrome_profile/   # Persistent browser profile
│       └── linkedin_cookies.json      # Extracted credentials
└── tests/
    ├── test_auth.py
    ├── test_discovery.py
    ├── test_configure.py
    └── test_build.py
```

## Dependencies

- `patchright` — Browser automation (Playwright wrapper, matches x-bookmark-to-substack)
- `httpx` — HTTP client for validation requests
- `rich` — Terminal UI for configuration menu
- `python >=3.11`

## CLI

```bash
# Full pipeline
uv run python -m lilite auth
uv run python -m lilite discover
uv run python -m lilite configure
uv run python -m lilite build

# Or all at once
uv run python -m lilite run
```

## Cross-Platform Notes

Same Mac/Ubuntu split as x-bookmark-to-substack:
- **Auth (Phase A):** Run on Mac (has display for manual login)
- **Discovery (Phase B):** Run on Mac (needs display for clicking)
- **Configure (Phase C):** Run anywhere (terminal menu)
- **Build (Phase D):** Run anywhere (pure file generation)
- Credentials sync via sambashare (`/Volumes/sambashare/expts/lilite/` on Mac)
