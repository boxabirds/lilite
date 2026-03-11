"""Phase D: Build a Chrome extension from configuration.

Generates a Manifest V3 extension with:
- declarativeNetRequest rules for blocking API calls / trackers
- CSS + MutationObserver content script for hiding UI components
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_MANIFEST_TEMPLATE = {
    "manifest_version": 3,
    "name": "LI Lite",
    "version": "1.0.0",
    "description": "A lighter LinkedIn experience — hides clutter, blocks trackers",
    "permissions": ["declarativeNetRequest"],
    "host_permissions": ["*://*.linkedin.com/*"],
    "content_scripts": [
        {
            "matches": ["*://*.linkedin.com/*"],
            "css": ["styles.css"],
            "js": ["content.js"],
            "run_at": "document_start",
        }
    ],
    "declarative_net_request": {
        "rule_resources": [
            {"id": "block_rules", "enabled": True, "path": "rules.json"}
        ]
    },
    "icons": {
        "16": "icons/icon16.png",
        "48": "icons/icon48.png",
        "128": "icons/icon128.png",
    },
}


def build(config_path: str | None = None) -> str:
    """Build Chrome extension from configuration. Returns build directory path."""
    if config_path:
        cfg_file = Path(config_path)
    else:
        cfg_file = _find_latest_config()

    if not cfg_file or not cfg_file.exists():
        raise FileNotFoundError("No configuration file found — run 'lilite configure' first")

    with open(cfg_file) as f:
        cfg = json.load(f)

    rules = cfg.get("rules", [])
    hide_rules = [r for r in rules if r["action"] == "hide"]
    block_rules = [r for r in rules if r["action"] == "block"]

    # Create build directory
    datestamp = datetime.now().strftime("%Y%m%d-%H%M")
    build_dir = config.CONFIG_DIR / f"{datestamp}-build"
    build_dir.mkdir(parents=True, exist_ok=True)
    icons_dir = build_dir / "icons"
    icons_dir.mkdir(exist_ok=True)

    # Generate manifest.json
    manifest = dict(_MANIFEST_TEMPLATE)
    if not block_rules:
        # No network rules needed — remove declarativeNetRequest
        manifest.pop("declarative_net_request", None)
        manifest["permissions"] = []
    with open(build_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Generate styles.css — hide UI components
    css_lines = [
        "/* LI Lite — auto-generated hide rules */",
        "/* Based on: {} */".format(cfg_file.name),
        "",
    ]
    for rule in hide_rules:
        selector = rule.get("selector", "")
        if selector:
            desc = rule.get("description", rule.get("id", ""))
            css_lines.append(f"/* {desc} */")
            css_lines.append(f"{selector} {{ display: none !important; }}")
            css_lines.append("")
    with open(build_dir / "styles.css", "w") as f:
        f.write("\n".join(css_lines))

    # Generate content.js — scope-aware MutationObserver for dynamic elements
    # Group selectors by their scope (URL prefix), with '*' as the global fallback
    scope_map = {}
    for r in hide_rules:
        selector = r.get("selector")
        if not selector:
            continue
        scope = r.get("scope", "")
        if scope.startswith("url:"):
            scope_key = scope[4:]  # strip 'url:' prefix
        else:
            scope_key = "*"
        scope_map.setdefault(scope_key, []).append(selector)

    scope_map_json = json.dumps(scope_map)
    content_js = f"""\
// LI Lite — auto-generated content script
// Hides dynamically-loaded elements matching configured selectors
// Scope-aware: only applies rules on pages where elements were discovered

(function() {{
  'use strict';

  const SCOPE_MAP = {scope_map_json};

  function getApplicableSelectors() {{
    const url = window.location.href;
    const selectors = [];
    // Always include global (unscoped) rules
    if (SCOPE_MAP['*']) selectors.push(...SCOPE_MAP['*']);
    // Include rules whose scope is a prefix of the current URL
    for (const [scope, sels] of Object.entries(SCOPE_MAP)) {{
      if (scope !== '*' && url.startsWith(scope)) {{
        selectors.push(...sels);
      }}
    }}
    return selectors;
  }}

  function hideMatching(root) {{
    const selectors = getApplicableSelectors();
    if (!selectors.length) return;
    const combined = selectors.join(', ');
    root.querySelectorAll(combined).forEach(el => {{
      el.style.setProperty('display', 'none', 'important');
    }});
  }}

  // Initial pass
  if (document.body) hideMatching(document.body);

  // Watch for dynamically added elements
  const observer = new MutationObserver(mutations => {{
    const selectors = getApplicableSelectors();
    if (!selectors.length) return;
    const combined = selectors.join(', ');
    for (const mutation of mutations) {{
      for (const node of mutation.addedNodes) {{
        if (node.nodeType === Node.ELEMENT_NODE) {{
          if (node.matches && node.matches(combined)) {{
            node.style.setProperty('display', 'none', 'important');
          }}
          hideMatching(node);
        }}
      }}
    }}
  }});

  observer.observe(document.documentElement, {{
    childList: true,
    subtree: true,
  }});
}})();
"""
    with open(build_dir / "content.js", "w") as f:
        f.write(content_js)

    # Generate rules.json — declarativeNetRequest rules for blocking
    dnr_rules = []
    for i, rule in enumerate(block_rules, start=1):
        url_pattern = rule.get("url_pattern", "")
        if not url_pattern:
            continue
        # Convert our url_pattern to a urlFilter
        url_filter = url_pattern.replace("*", "*")
        dnr_rules.append({
            "id": i,
            "priority": 1,
            "action": {"type": "block"},
            "condition": {
                "urlFilter": url_filter,
                "resourceTypes": [
                    "xmlhttprequest", "script", "image", "ping",
                    "sub_frame", "other",
                ],
            },
        })
    with open(build_dir / "rules.json", "w") as f:
        json.dump(dnr_rules, f, indent=2)

    # Copy icons if they exist, otherwise generate placeholder SVGs
    _generate_placeholder_icons(icons_dir)

    log.info(f"Extension built: {build_dir}")
    print(f"\nExtension built at: {build_dir}")
    print(f"  {len(hide_rules)} UI hide rules (CSS + MutationObserver)")
    print(f"  {len(dnr_rules)} network block rules (declarativeNetRequest)")
    print(f"\nTo install:")
    print(f"  1. Open chrome://extensions")
    print(f"  2. Enable 'Developer mode'")
    print(f"  3. Click 'Load unpacked' -> select {build_dir}")
    return str(build_dir)


def _find_latest_config() -> Path | None:
    """Find the most recent configuration JSON."""
    files = sorted(config.CONFIG_DIR.glob("*-configuration.json"), reverse=True)
    return files[0] if files else None


def _generate_placeholder_icons(icons_dir: Path) -> None:
    """Generate minimal PNG placeholder icons (1x1 blue pixel, just for manifest validity)."""
    # Minimal valid PNG: 1x1 blue pixel
    # For a real extension you'd replace these with proper icons
    import struct
    import zlib

    def make_png(size: int) -> bytes:
        """Generate a minimal valid PNG of given size with a blue square."""
        # We create a simple raw image and wrap in PNG format
        # Each row: filter byte (0) + RGBA pixels
        raw = b""
        for _y in range(size):
            raw += b"\x00"  # filter: none
            for _x in range(size):
                raw += b"\x00\x77\xc2\xff"  # LinkedIn blue RGBA

        # PNG signature
        sig = b"\x89PNG\r\n\x1a\n"

        # IHDR chunk
        ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
        ihdr = _png_chunk(b"IHDR", ihdr_data)

        # IDAT chunk (compressed image data)
        compressed = zlib.compress(raw)
        idat = _png_chunk(b"IDAT", compressed)

        # IEND chunk
        iend = _png_chunk(b"IEND", b"")

        return sig + ihdr + idat + iend

    def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

    for size, name in [(16, "icon16.png"), (48, "icon48.png"), (128, "icon128.png")]:
        with open(icons_dir / name, "wb") as f:
            f.write(make_png(size))
