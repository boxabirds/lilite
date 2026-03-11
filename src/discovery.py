"""Phase B: Discover UI components and API calls on LinkedIn pages.

Launches an authenticated browser session, intercepts all network traffic,
walks the DOM for stable UI components, then follows top-level nav links
(depth 1) and repeats. Saves everything to a datestamped JSON file.
"""

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import config
from . import auth

log = logging.getLogger(__name__)

# Network call classification rules (order matters — first match wins)
_TRACKING_PATTERNS = [
    (r"px\.ads\.linkedin\.com", "tracking-pixel", "linkedin-ads"),
    (r"snap\.licdn\.com", "tracking-pixel", "linkedin-snap"),
    (r"google-analytics\.com|googletagmanager\.com", "analytics", "google-analytics"),
    (r"doubleclick\.net", "ad-network", "doubleclick"),
    (r"facebook\.com/tr", "tracking-pixel", "meta-pixel"),
    (r"bat\.bing\.com", "tracking-pixel", "microsoft-ads"),
    (r"analytics|tracking|telemetry|beacon", "analytics", None),
    (r"ads\.|ad-|adserver", "ad-network", None),
]

_STATIC_EXTENSIONS = {".js", ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg",
                      ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif"}


def discover() -> str:
    """Run full discovery. Returns path to the output JSON file."""
    from patchright.sync_api import sync_playwright

    cookies = auth.load_cookies()
    if not cookies:
        raise RuntimeError("No saved cookies — run 'lilite auth' first")

    auth.check_credentials_age()

    pages_data = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir="/tmp/lilite_discovery",
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.add_cookies(cookies)

        # Discover the feed page
        feed_data = _discover_page(page, config.LINKEDIN_FEED)
        if not feed_data:
            ctx.close()
            raise RuntimeError("Could not load feed — re-authenticate with 'lilite auth'")
        pages_data.append(feed_data)

        # Follow top-level nav links (depth 1)
        nav_urls = _extract_nav_links(page)
        for url in nav_urls:
            log.info(f"Discovering nav link: {url}")
            page_data = _discover_page(page, url)
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

    log.info(f"Discovery saved to {output_path}")
    print(f"\nDiscovery complete: {len(pages_data)} pages, saved to {output_path}")
    return str(output_path)


def _discover_page(page, url: str) -> dict | None:
    """Discover a single page: intercept network calls, walk the DOM."""
    api_calls = []
    request_log = {}

    def on_request(request):
        request_log[request.url] = {
            "method": request.method,
            "resource_type": request.resource_type,
            "headers": {k: v for k, v in request.headers.items()
                        if k.lower() not in ("cookie", "authorization")},
        }

    def on_response(response):
        url = response.url
        entry = request_log.get(url, {})
        classification, vendor = _classify_network_call(url, entry)
        if classification == "static-asset":
            return  # skip static assets from output

        api_calls.append({
            "url": url,
            "url_pattern": _url_to_pattern(url),
            "method": entry.get("method", "GET"),
            "status": response.status,
            "content_type": response.headers.get("content-type", ""),
            "classification": classification,
            "vendor": vendor,
        })

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        page.goto(url, wait_until="networkidle",
                  timeout=config.DISCOVERY_PAGE_LOAD_TIMEOUT_MS)
    except Exception as e:
        log.warning(f"Failed to load {url}: {e}")
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)
        return None

    if not auth.validate_session(page):
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)
        return None

    # Wait for dynamic content to settle
    page.wait_for_timeout(config.DISCOVERY_IDLE_WAIT_MS)

    # Walk the DOM for UI components
    ui_components = _discover_ui_components(page)

    # Deduplicate API calls by url_pattern
    seen_patterns = set()
    unique_api_calls = []
    for call in api_calls:
        key = f"{call['method']}:{call['url_pattern']}"
        if key not in seen_patterns:
            seen_patterns.add(key)
            call["scope"] = f"url-pattern:{call['url_pattern']}"
            # Generate stable ID
            call["id"] = _make_id(call["url_pattern"])
            unique_api_calls.append(call)

    page.remove_listener("request", on_request)
    page.remove_listener("response", on_response)

    return {
        "url": page.url,
        "ui_components": ui_components,
        "api_calls": unique_api_calls,
    }


def _discover_ui_components(page) -> list[dict]:
    """Walk the DOM and identify stable, distinct UI components."""
    components = page.evaluate("""() => {
        const results = [];
        const seen = new Set();

        // Strategy 1: data-test-id and data-control-name attributes
        document.querySelectorAll('[data-test-id], [data-control-name], [data-resource-context]').forEach(el => {
            const id = el.getAttribute('data-test-id')
                     || el.getAttribute('data-control-name')
                     || el.getAttribute('data-resource-context');
            if (seen.has(id)) return;
            seen.add(id);
            const rect = el.getBoundingClientRect();
            if (rect.width < 10 || rect.height < 10) return;
            results.push({
                id: id,
                selector: _buildSelector(el),
                text_summary: (el.textContent || '').trim().substring(0, 120),
                bounding_box: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role'),
                aria_label: el.getAttribute('aria-label'),
            });
        });

        // Strategy 2: semantic sections / landmarks
        document.querySelectorAll('section, aside, nav, header, footer, [role="navigation"], [role="complementary"], [role="banner"], [role="contentinfo"], [role="main"]').forEach(el => {
            const role = el.getAttribute('role') || el.tagName.toLowerCase();
            const label = el.getAttribute('aria-label') || '';
            const id = label ? `${role}:${label}` : `${role}:${el.className.split(' ')[0] || 'anon'}`;
            if (seen.has(id)) return;
            seen.add(id);
            const rect = el.getBoundingClientRect();
            if (rect.width < 10 || rect.height < 10) return;
            results.push({
                id: id,
                selector: _buildSelector(el),
                text_summary: (el.textContent || '').trim().substring(0, 120),
                bounding_box: {x: Math.round(rect.x), y: Math.round(rect.y),
                               w: Math.round(rect.width), h: Math.round(rect.height)},
                tag: el.tagName.toLowerCase(),
                role: role,
                aria_label: label || null,
            });
        });

        function _buildSelector(el) {
            if (el.id) return '#' + el.id;
            const testId = el.getAttribute('data-test-id');
            if (testId) return `[data-test-id="${testId}"]`;
            const controlName = el.getAttribute('data-control-name');
            if (controlName) return `[data-control-name="${controlName}"]`;
            // Fallback: tag + class
            const cls = el.className ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
            return el.tagName.toLowerCase() + cls;
        }

        return results;
    }""")

    # Classify each component
    for comp in components:
        comp["classification"] = _classify_ui_component(comp)
        comp["scope"] = f"url:{page.url}"
        # Clean up: generate description from available info
        comp["description"] = _describe_component(comp)

    return components


def _classify_ui_component(comp: dict) -> str:
    """Classify a UI component based on its attributes."""
    cid = (comp.get("id") or "").lower()
    role = (comp.get("role") or "").lower()
    tag = (comp.get("tag") or "").lower()
    label = (comp.get("aria_label") or "").lower()
    text = (comp.get("text_summary") or "").lower()

    if role in ("navigation", "nav") or tag == "nav":
        return "navigation"
    if role in ("banner",) or tag == "header":
        return "navigation"
    if role in ("contentinfo",) or tag == "footer":
        return "footer"
    if role in ("complementary",) or tag == "aside":
        return "sidebar-widget"
    if "ad" in cid or "promote" in cid or "sponsor" in cid:
        return "promoted-content"
    if "ad" in label or "sponsor" in label or "promot" in label:
        return "promoted-content"
    if "message" in cid or "messaging" in cid or "msg" in cid:
        return "messaging"
    if "notification" in cid or "notif" in cid:
        return "notification"
    if "feed" in cid or "update" in cid:
        return "feed-card"
    if "modal" in cid or "overlay" in cid:
        return "modal"
    return "other"


def _describe_component(comp: dict) -> str:
    """Generate a plain English description of a component."""
    label = comp.get("aria_label") or ""
    text = (comp.get("text_summary") or "")[:80]
    cid = comp.get("id") or ""
    if label:
        return label
    if text and len(text) > 5:
        return text
    return cid


def _classify_network_call(url: str, entry: dict) -> tuple[str, str | None]:
    """Classify a network request. Returns (classification, vendor)."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check tracking/ad patterns
    for pattern, classification, vendor in _TRACKING_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return classification, vendor

    # Static assets
    for ext in _STATIC_EXTENSIONS:
        if path.endswith(ext):
            return "static-asset", None

    # WebSocket
    if url.startswith("wss://") or url.startswith("ws://"):
        return "websocket", None

    # GraphQL
    if "graphql" in path:
        return "graphql", None

    # LinkedIn Voyager API
    if "/voyager/" in path or "/api/" in path:
        return "rest-api", None

    # Remaining linkedin.com calls
    if "linkedin.com" in parsed.netloc:
        return "rest-api", None

    # Third-party
    return "other", None


def _url_to_pattern(url: str) -> str:
    """Convert a URL to a pattern by replacing IDs/hashes with wildcards."""
    parsed = urlparse(url)
    # Remove query params, replace numeric/hash path segments
    path = re.sub(r'/[0-9a-f]{8,}', '/*', parsed.path)
    path = re.sub(r'/\d+', '/*', path)
    return f"{parsed.netloc}{path}"


def _make_id(url_pattern: str) -> str:
    """Generate a stable ID from a URL pattern."""
    # Take the last meaningful path segment
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
    return links[:10]  # cap at 10 to avoid runaway discovery
