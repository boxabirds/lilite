"""Phase B: Discover page sections and network calls using LLM analysis.

Launches an authenticated browser session, grabs the rendered DOM,
strips noise (scripts, styles, SVGs), sends the cleaned HTML to Gemini
to identify semantic page blocks with XPaths. Also sends intercepted
network calls to Gemini for semantic classification. Follows top-level
nav links (depth 1) and repeats. Saves everything to a datestamped JSON.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from google import genai

from . import config
from . import auth

log = logging.getLogger(__name__)

_STATIC_EXTENSIONS = {".js", ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg",
                      ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif"}

# URL substrings that must NEVER be blocked — blocking these breaks LinkedIn's
# client-side error handling and React hydration, causing cascading failures.
# Gemini repeatedly misclassifies these as "analytics" due to "track" in the name.
_INFRASTRUCTURE_URL_PATTERNS = frozenset({
    "trackO11y",
    "trackObserve",
    "sensorCollect",
    "psettings/policy",
    "realtimeFrontendClientConnectivityTracking",
    "li/track",           # LinkedIn's internal tracking infra (not ad tracking)
    "voyagerGuardService",
})

# CSS selectors that are too generic — they match many unrelated elements
_GENERIC_SELECTOR_DENYLIST = frozenset({
    'div[role="menu"]',
    'div[role="button"]',
    'div[role="listitem"]',
    'div[role="list"]',
    'div[role="option"]',
    'div[role="presentation"]',
    'div[role="group"]',
    'span[role="button"]',
    'li[role="listitem"]',
    'button',
    'div',
    'span',
    'a',
})

# ID-based selectors for app-root containers — hiding these hides the entire page
_APP_ROOT_SELECTOR_DENYLIST = frozenset({
    '#root', '#app', '#__next', '#main', '#content',
    '#application', '#wrapper', '#page',
})

# Maximum number of DOM elements a CSS selector may match before we discard it
MAX_CSS_SELECTOR_MATCHES = 3

# Domains whose requests are always static assets (CDN images, fonts, etc.)
_STATIC_DOMAINS = {"media.licdn.com", "static.licdn.com", "media-exp1.licdn.com"}

_PAGE_ANALYSIS_PROMPT = """You are an expert at analyzing web page structure. You will receive the cleaned HTML of a web page with scripts, styles, and SVGs removed.

Your task: identify every distinct semantic block/section that a user might want to show or hide. Think of it as "what are the independent visual sections of this page?"

For each block, provide:
1. **name**: Short human-readable name (e.g., "Jobs button", "LinkedIn News", "Profile card")
2. **xpath**: An XPath expression that selects the outermost container of this block.
3. **zone**: One of: "top-nav", "left-sidebar", "main-feed", "right-sidebar", "messaging", "footer", "overlay"
4. **description**: One sentence describing what this section contains or does.
5. **default_action**: "keep" or "hide" — suggest "hide" for ads, promotions, trackers, and noise; "keep" for core content and navigation.

XPath rules (CRITICAL — read carefully):
- NEVER use @componentkey, @data-id with hash values, @data-view-name, @data-urn, or any attribute whose value looks like a hash, UUID, or random token. These are framework-generated and change every session — your XPath will break immediately.
- NEVER use CSS class names — they are hashed and change on deploy.
- PREFER these stable anchors (in order):
  1. Text content: //section[.//h2[text()='LinkedIn News']], //div[.//span[contains(text(), 'Profile viewers')]]
  2. @aria-label: //button[@aria-label='For Business']
  3. @role combined with text: //aside[@role='complementary'][.//h2[text()='Trending']]
  4. @href paths: //a[contains(@href, '/jobs')]
  5. @data-test-id, @data-control-name (these are stable test attributes)
  6. Heading hierarchy: //section[h2[text()='People also viewed']]
  7. Structural patterns: //nav//a[3] (only as last resort)
- For sidebar panels, ALWAYS anchor by the heading or label text inside them.
- XPaths must use // for robustness. Avoid positional indices when text anchors exist.

Guidelines:
- For navigation bars, identify INDIVIDUAL buttons/links as separate blocks (e.g., "Home button", "Jobs button", "Messaging button") so users can toggle each independently.
- For sidebars, identify each distinct card/panel separately (e.g., "Profile card", "Profile stats", "LinkedIn News").
- The main feed container should be ONE block, not individual posts.
- Identify ad slots, promoted content, and "Try Premium" CTAs as separate blocks.
- Overlays (like messaging) should be identified.
- Do NOT include invisible elements, script artifacts, or meta tags.

Return valid JSON only — an array of objects. No markdown fences, no commentary."""

_NETWORK_ANALYSIS_PROMPT = """You are an expert at analyzing web application network traffic. You will receive a list of network API calls made by a web page.

Your task: classify each call with a human-readable name and semantic category so a user can decide which to keep or block.

For each call, provide:
1. **url_pattern**: The URL pattern (copy from input)
2. **name**: Short human-readable name (e.g., "Feed data API", "Profile analytics", "Ad tracking beacon", "Notification polling")
3. **category**: One of: "core-data" (essential page data), "analytics" (usage tracking), "advertising" (ad serving/tracking), "social" (likes, comments, shares), "messaging" (chat/messaging), "notifications" (alerts), "media" (images, video loading), "authentication" (login/session), "infrastructure" (CSP, error reporting, config, bot detection, session management), "other"
4. **description**: One sentence explaining what this call likely does.
5. **default_action**: "keep" or "block" — rules:
   - ALWAYS "keep": core-data, social, messaging, notifications, authentication, infrastructure, media. These are essential for the page to function. Blocking them will break the site.
   - "block" ONLY for: analytics and advertising. These are safe to remove without breaking functionality.
   - When in doubt, default to "keep".

Return valid JSON only — an array of objects. No markdown fences, no commentary."""


def discover() -> str:
    """Run full discovery. Returns path to the output JSON file."""
    from patchright.sync_api import sync_playwright

    cookies = auth.load_cookies()
    if not cookies:
        raise RuntimeError("No saved cookies — run 'lilite auth' first")

    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set — add it to .env")

    auth.check_credentials_age()

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    pages_data = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(config.CHROME_PROFILE_DIR),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.add_cookies(cookies)

        # Discover the feed page
        feed_data = _discover_page(page, config.LINKEDIN_FEED, client)
        if not feed_data:
            ctx.close()
            raise RuntimeError("Could not load feed — re-authenticate with 'lilite auth'")
        pages_data.append(feed_data)

        # Follow top-level nav links (depth 1)
        nav_urls = _extract_nav_links(page)
        for url in nav_urls:
            log.info(f"Discovering nav link: {url}")
            page_data = _discover_page(page, url, client)
            if page_data:
                pages_data.append(page_data)

        ctx.close()

    # Save results
    datestamp = datetime.now().strftime("%Y%m%d-%H%M")
    output_path = config.CONFIG_DIR / f"{datestamp}-discovery.json"
    result = {
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages_data,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    section_count = sum(
        len(pd.get("ui_components", []))
        for pd in pages_data
    )
    api_count = sum(
        len(pd.get("api_calls", []))
        for pd in pages_data
    )
    print(f"\nDiscovery complete: {len(pages_data)} pages, "
          f"{section_count} page sections, {api_count} network calls")
    print(f"Saved to {output_path}")
    return str(output_path)


def _discover_page(page, url: str, client) -> dict | None:
    """Discover a single page: grab HTML, send to Gemini, intercept network."""
    api_calls = []
    request_log = {}

    def on_request(request):
        request_log[request.url] = {
            "method": request.method,
            "resource_type": request.resource_type,
        }

    def on_response(response):
        resp_url = response.url
        entry = request_log.get(resp_url, {})

        # Filter static assets before recording
        if _is_static_asset(resp_url):
            return

        api_calls.append({
            "url": resp_url,
            "url_pattern": _url_to_pattern(resp_url),
            "method": entry.get("method", "GET"),
            "status": response.status,
            "content_type": response.headers.get("content-type", ""),
        })

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded",
                  timeout=config.DISCOVERY_PAGE_LOAD_TIMEOUT_MS)
    except Exception as e:
        print(f"  ✗ Failed to load {url}: {e}")
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)
        return None

    if not auth.validate_session(page):
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)
        return None

    # Wait for dynamic content to settle
    page.wait_for_timeout(config.DISCOVERY_IDLE_WAIT_MS)

    # --- Page section analysis via LLM ---
    raw_html = page.content()
    cleaned_html = _strip_html_noise(raw_html)
    print(f"  HTML: {len(raw_html):,} → {len(cleaned_html):,} chars "
          f"({len(cleaned_html) / max(len(raw_html), 1) * 100:.0f}%)")

    # Save cleaned HTML for debugging
    datestamp = datetime.now().strftime("%Y%m%d-%H%M")
    debug_path = config.CONFIG_DIR / f"{datestamp}-cleaned.html"
    debug_path.write_text(cleaned_html)
    print(f"  Cleaned HTML saved to {debug_path.name}")

    print(f"  Analyzing page structure with {config.GEMINI_MODEL_ID}...")
    ui_components = _identify_blocks_with_llm(client, cleaned_html, page.url)
    print(f"  → {len(ui_components)} blocks identified")

    # Validate XPaths against the live page
    ui_components = _validate_xpaths(page, ui_components)
    print(f"  → {len(ui_components)} blocks validated against live DOM")

    # --- Network call analysis via LLM ---
    # Deduplicate API calls by url_pattern first
    seen_patterns = set()
    unique_api_calls = []
    for call in api_calls:
        key = f"{call['method']}:{call['url_pattern']}"
        if key not in seen_patterns:
            seen_patterns.add(key)
            call["id"] = _make_id(call["url_pattern"])
            unique_api_calls.append(call)

    if unique_api_calls:
        print(f"  Classifying {len(unique_api_calls)} network calls with {config.GEMINI_MODEL_ID}...")
        unique_api_calls = _classify_network_calls_with_llm(
            client, unique_api_calls, page.url
        )
        print(f"  → {len(unique_api_calls)} calls classified")

    page.remove_listener("request", on_request)
    page.remove_listener("response", on_response)

    return {
        "url": page.url,
        "ui_components": ui_components,
        "api_calls": unique_api_calls,
    }


def _strip_html_noise(html: str) -> str:
    """Strip scripts, styles, SVGs, comments, data URIs, and inline styles from HTML."""
    # Remove script tags and contents
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove style tags and contents
    html = re.sub(r'<style\b[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove SVG tags and contents
    html = re.sub(r'<svg\b[^>]*>.*?</svg>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # Remove inline style attributes
    html = re.sub(r'\sstyle="[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\sstyle='[^']*'", '', html, flags=re.IGNORECASE)
    # Remove data: URIs (base64 images etc.)
    html = re.sub(r'(src|href)="data:[^"]*"', r'\1=""', html, flags=re.IGNORECASE)
    # Remove noscript tags
    html = re.sub(r'<noscript\b[^>]*>.*?</noscript>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove class attributes (hashed, useless, and huge)
    html = re.sub(r'\sclass="[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\sclass='[^']*'", '', html, flags=re.IGNORECASE)
    # Collapse whitespace runs
    html = re.sub(r'\s{2,}', ' ', html)

    return html.strip()


def _identify_blocks_with_llm(client, html: str, page_url: str) -> list[dict]:
    """Send cleaned HTML to Gemini and parse the response into UI components."""
    user_prompt = (
        f"Analyze this web page ({page_url}) and identify all semantic blocks.\n\n"
        f"{html}"
    )
    print(f"  Sending {len(user_prompt):,} chars to Gemini...")

    t0 = time.monotonic()
    try:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL_ID,
            contents=user_prompt,
            config={
                "system_instruction": _PAGE_ANALYSIS_PROMPT,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        )
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"  ✗ Gemini page analysis failed after {elapsed:.1f}s: {e}")
        return []

    elapsed = time.monotonic() - t0
    print(f"  Gemini responded in {elapsed:.1f}s ({len(response.text):,} chars)")
    return _parse_page_blocks(response.text, page_url)


def _parse_page_blocks(raw_text: str, page_url: str) -> list[dict]:
    """Parse Gemini's page block response into component dicts."""
    raw_text = raw_text.strip()

    try:
        blocks = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if match:
            try:
                blocks = json.loads(match.group(0))
            except json.JSONDecodeError:
                print(f"  ✗ Failed to parse Gemini page response as JSON")
                print(f"    First 300 chars: {raw_text[:300]}")
                return []
        else:
            print(f"  ✗ No JSON array in Gemini page response")
            print(f"    First 300 chars: {raw_text[:300]}")
            return []

    if not isinstance(blocks, list):
        print(f"  ✗ Gemini returned {type(blocks).__name__}, expected list")
        return []

    components = []
    for block in blocks:
        if not isinstance(block, dict):
            continue

        name = block.get("name", "").strip()
        xpath = block.get("xpath", "").strip()
        if not name or not xpath:
            continue

        zone = block.get("zone", "other")
        default_action = block.get("default_action", "keep")

        components.append({
            "id": _slugify(name),
            "name": name,
            "xpath": xpath,
            "selector": None,
            "zone": zone,
            "description": block.get("description", name),
            "default_action": default_action,
            "element_type": "structural",
            "classification": _zone_to_classification(zone, default_action),
            "scope": f"url:{page_url}",
        })

    return components


def _classify_network_calls_with_llm(
    client, calls: list[dict], page_url: str,
) -> list[dict]:
    """Send network call list to Gemini for semantic classification."""
    # Build a compact summary for the LLM
    call_summaries = []
    for call in calls:
        call_summaries.append({
            "url_pattern": call["url_pattern"],
            "method": call["method"],
            "status": call.get("status"),
            "content_type": call.get("content_type", ""),
        })

    user_prompt = (
        f"These network calls were made by {page_url}. "
        f"Classify each one.\n\n"
        f"{json.dumps(call_summaries, indent=2)}"
    )
    print(f"  Sending {len(call_summaries)} calls ({len(user_prompt):,} chars) to Gemini...")

    t0 = time.monotonic()
    try:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL_ID,
            contents=user_prompt,
            config={
                "system_instruction": _NETWORK_ANALYSIS_PROMPT,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        )
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"  ✗ Gemini network classification failed after {elapsed:.1f}s: {e}")
        for call in calls:
            call["name"] = call["url_pattern"]
            call["category"] = "other"
            call["description"] = call["url_pattern"]
            call["default_action"] = "keep"
            call["scope"] = f"url-pattern:{call['url_pattern']}"
        return calls

    elapsed = time.monotonic() - t0
    print(f"  Gemini responded in {elapsed:.1f}s")
    return _merge_network_classifications(calls, response.text)


def _merge_network_classifications(
    calls: list[dict], raw_text: str,
) -> list[dict]:
    """Merge Gemini's network classifications back into our call dicts."""
    raw_text = raw_text.strip()

    try:
        classifications = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if match:
            try:
                classifications = json.loads(match.group(0))
            except json.JSONDecodeError:
                print(f"  ✗ Failed to parse Gemini network response as JSON")
                classifications = []
        else:
            classifications = []

    if not isinstance(classifications, list):
        classifications = []

    # Index classifications by url_pattern for lookup
    cls_by_pattern = {}
    for cls in classifications:
        if isinstance(cls, dict) and "url_pattern" in cls:
            cls_by_pattern[cls["url_pattern"]] = cls

    for call in calls:
        pattern = call["url_pattern"]
        cls = cls_by_pattern.get(pattern, {})

        call["name"] = cls.get("name", pattern)
        call["category"] = cls.get("category", "other")
        call["description"] = cls.get("description", pattern)
        call["default_action"] = cls.get("default_action", "keep")
        call["scope"] = f"url-pattern:{pattern}"

        # Override: force infrastructure classification for known-critical endpoints
        # that Gemini repeatedly misclassifies as "analytics"
        if _is_infrastructure_url(pattern):
            if call["category"] != "infrastructure":
                log.info(f"Overriding category for {pattern}: "
                         f"{call['category']} → infrastructure")
            call["category"] = "infrastructure"
            call["default_action"] = "keep"

    return calls


def _is_infrastructure_url(url_pattern: str) -> bool:
    """Check if a URL pattern matches a known-critical infrastructure endpoint."""
    return any(substr in url_pattern for substr in _INFRASTRUCTURE_URL_PATTERNS)


def _is_selector_too_broad(selector: str | None, match_count: int) -> bool:
    """Check if a CSS selector is too generic to use safely."""
    if selector is None:
        return False
    if selector in _GENERIC_SELECTOR_DENYLIST:
        return True
    if selector in _APP_ROOT_SELECTOR_DENYLIST:
        return True
    return match_count > MAX_CSS_SELECTOR_MATCHES


def _validate_xpaths(page, components: list[dict]) -> list[dict]:
    """Validate XPaths against the live page and generate CSS selectors where possible."""
    validated = []
    for comp in components:
        xpath = comp.get("xpath", "")
        try:
            elements = page.locator(f"xpath={xpath}")
            count = elements.count()
            if count == 0:
                print(f"    ✗ XPath matched 0 elements: {comp['name']}")
                continue

            # Get bounding box of the first match
            try:
                box = elements.first.bounding_box()
                if box:
                    comp["bounding_box"] = {
                        "x": round(box["x"]),
                        "y": round(box["y"]),
                        "w": round(box["width"]),
                        "h": round(box["height"]),
                    }
            except Exception:
                pass

            # Try to generate a CSS selector from stable attributes
            css_selector = page.evaluate("""(xpath) => {
                const result = document.evaluate(xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                const el = result.singleNodeValue;
                if (!el) return null;

                if (el.id && !/^[a-f0-9-]{6,}$/.test(el.id) && !/^ember/.test(el.id)) {
                    return '#' + CSS.escape(el.id);
                }
                const ariaLabel = el.getAttribute('aria-label');
                if (ariaLabel) {
                    return '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]';
                }
                for (const attr of ['data-test-id', 'data-control-name', 'data-resource-context']) {
                    const val = el.getAttribute(attr);
                    if (val) return '[' + attr + '="' + val + '"]';
                }
                const role = el.getAttribute('role');
                const tag = el.tagName.toLowerCase();
                if (role && role !== tag) {
                    return tag + '[role="' + role + '"]';
                }
                if (tag === 'a' && el.href) {
                    try {
                        const path = new URL(el.href).pathname;
                        return 'a[href*="' + path + '"]';
                    } catch(e) {}
                }
                return null;
            }""", xpath)

            # Validate CSS selector specificity — discard overly broad ones
            if css_selector:
                css_match_count = page.evaluate(
                    """(sel) => {
                        try { return document.querySelectorAll(sel).length; }
                        catch(e) { return -1; }
                    }""",
                    css_selector,
                )
                if _is_selector_too_broad(css_selector, css_match_count):
                    print(f"    ⚠ Discarding broad CSS selector for {comp['name']}: "
                          f"{css_selector} ({css_match_count} matches)")
                    css_selector = None

            comp["selector"] = css_selector
            comp["xpath_match_count"] = count
            validated.append(comp)
            print(f"    ✓ {comp['name']} ({count} match{'es' if count > 1 else ''})")

        except Exception as e:
            print(f"    ✗ XPath error for {comp['name']}: {e}")
            continue

    return validated


def _is_static_asset(url: str) -> bool:
    """Check if a URL is a static asset (CDN image, font, stylesheet, etc.)."""
    parsed = urlparse(url)
    if parsed.netloc in _STATIC_DOMAINS:
        return True
    path = parsed.path.lower()
    for ext in _STATIC_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def _slugify(name: str) -> str:
    """Convert a name to a URL-safe slug."""
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', name.lower()).strip('-')
    return slug[:50] or "unknown"


def _zone_to_classification(zone: str, default_action: str) -> str:
    """Map zone + default_action to a classification for configure defaults."""
    if default_action == "hide":
        return "promoted-content"
    zone_map = {
        "top-nav": "navigation",
        "left-sidebar": "sidebar-widget",
        "right-sidebar": "sidebar-widget",
        "main-feed": "feed-card",
        "messaging": "messaging",
        "footer": "footer",
        "overlay": "modal",
    }
    return zone_map.get(zone, "other")


def _url_to_pattern(url: str) -> str:
    """Convert a URL to a pattern by replacing IDs/hashes with wildcards."""
    parsed = urlparse(url)
    path = re.sub(r'/[0-9a-f]{8,}', '/*', parsed.path)
    path = re.sub(r'/\d+', '/*', path)
    return f"{parsed.netloc}{path}"


def _make_id(url_pattern: str) -> str:
    """Generate a stable ID from a URL pattern."""
    parts = [p for p in url_pattern.split("/") if p and p != "*"]
    if parts:
        return re.sub(r'[^a-zA-Z0-9-]', '-', parts[-1].split("?")[0])[:40]
    return "unknown"


def _extract_nav_links(page) -> list[str]:
    """Extract top-level navigation links from the current page."""
    links = page.evaluate("""() => {
        const nav = document.querySelector('#global-nav, nav[role="navigation"], [role="banner"] nav');
        if (!nav) return [];
        const anchors = nav.querySelectorAll('a[href]');
        const urls = [];
        for (const a of anchors) {
            const href = a.href;
            if (href.startsWith('https://www.linkedin.com/')
                && !href.includes('/login')
                && !href.includes('/signup')
                && !href.includes('#')
                && href !== window.location.href) {
                urls.push(href);
            }
        }
        return [...new Set(urls)];
    }""")

    log.info(f"Found {len(links)} nav links")
    return links[:10]
