"""Phase D: Build a Chrome extension from configuration.

Generates a Manifest V3 extension with:
- declarativeNetRequest rules for blocking API calls / trackers
- Storage-aware content script for toggling UI component visibility
- Popup UI for per-section on/off toggles
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from . import config
from .discovery import _APP_ROOT_SELECTOR_DENYLIST

log = logging.getLogger(__name__)

_MANIFEST_TEMPLATE = {
    "manifest_version": 3,
    "name": "LI Lite",
    "version": "1.0.0",
    "description": "A lighter LinkedIn experience — hides clutter, blocks trackers",
    "permissions": ["storage"],
    "host_permissions": ["*://*.linkedin.com/*"],
    "action": {
        "default_popup": "popup.html",
    },
    "content_scripts": [
        {
            "matches": ["*://*.linkedin.com/*"],
            "css": ["styles.css"],
            "js": ["content.js"],
            "run_at": "document_idle",
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

# Zone display order and labels (shared with popup)
_ZONE_LABELS = {
    "top-nav": "Top Navigation",
    "left-sidebar": "Left Sidebar",
    "main-feed": "Main Feed",
    "right-sidebar": "Right Sidebar",
    "messaging": "Messaging",
    "footer": "Footer",
    "overlay": "Overlays",
    "other": "Other",
}

# Attribute used to track which rules hid an element
_DATA_ATTR = "data-lilite-rule"


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
    if block_rules:
        manifest["permissions"] = ["storage", "declarativeNetRequest"]
    else:
        manifest.pop("declarative_net_request", None)
    with open(build_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Generate styles.css — empty; all hiding done via JS for toggleability
    css_lines = [
        "/* LI Lite — auto-generated styles */",
        f"/* Based on: {cfg_file.name} */",
        "/* Hiding is done via content.js to support per-rule toggling */",
    ]
    with open(build_dir / "styles.css", "w") as f:
        f.write("\n".join(css_lines))

    # Build deduplicated rules list for content.js
    rules_for_js = _build_rules_for_js(hide_rules)

    # Generate content.js — storage-aware, toggleable
    _generate_content_js(build_dir, rules_for_js)

    # Generate rules-meta.json for popup
    rules_meta = _build_rules_meta(hide_rules)
    with open(build_dir / "rules-meta.json", "w") as f:
        json.dump(rules_meta, f, indent=2)

    # Generate popup files
    _generate_popup(build_dir)

    # Generate rules.json — declarativeNetRequest rules for blocking
    dnr_rules = _build_dnr_rules(block_rules)
    with open(build_dir / "rules.json", "w") as f:
        json.dump(dnr_rules, f, indent=2)

    # Generate placeholder icons
    _generate_placeholder_icons(icons_dir)

    log.info(f"Extension built: {build_dir}")
    print(f"\nExtension built at: {build_dir}")
    print(f"  {len(hide_rules)} UI hide rules ({len(rules_for_js)} deduplicated)")
    print(f"  {len(dnr_rules)} network block rules (declarativeNetRequest)")
    print(f"\nTo install:")
    print(f"  1. Open chrome://extensions")
    print(f"  2. Enable 'Developer mode'")
    print(f"  3. Click 'Load unpacked' -> select {build_dir}")
    return str(build_dir)


def _build_rules_for_js(hide_rules: list[dict]) -> list[dict]:
    """Build deduplicated rules array for content.js."""
    rules = []
    seen = set()  # (selector_or_none, xpath_or_none, scope) for dedup

    for r in hide_rules:
        scope = r.get("scope", "")
        scope_key = scope[4:] if scope.startswith("url:") else "*"
        selector = r.get("selector") or None
        xpath = r.get("xpath") or None

        # Safety net: strip selectors that would hide the entire page
        if selector and selector in _APP_ROOT_SELECTOR_DENYLIST:
            log.warning(f"Stripping dangerous selector {selector} from rule {r.get('id')}")
            selector = None

        # Skip rules with neither selector nor xpath — they can't match anything
        if not selector and not xpath:
            continue

        dedup_key = (selector, xpath, scope_key)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        rules.append({
            "id": r.get("id", "unknown"),
            "selector": selector,
            "xpath": xpath,
            "scope": scope_key,
        })

    return rules


def _build_rules_meta(hide_rules: list[dict]) -> list[dict]:
    """Build metadata for the popup UI."""
    meta = []
    seen_ids = set()
    for r in hide_rules:
        rule_id = r.get("id", "unknown")
        if rule_id in seen_ids:
            continue
        seen_ids.add(rule_id)
        meta.append({
            "id": rule_id,
            "name": r.get("description", r.get("id", "unknown")),
            "zone": r.get("zone", "other"),
        })
    return meta


def _build_dnr_rules(block_rules: list[dict]) -> list[dict]:
    """Build declarativeNetRequest rules for network blocking."""
    dnr_rules = []
    for i, rule in enumerate(block_rules, start=1):
        url_pattern = rule.get("url_pattern", "")
        if not url_pattern:
            continue
        dnr_rules.append({
            "id": i,
            "priority": 1,
            "action": {"type": "block"},
            "condition": {
                "urlFilter": url_pattern,
                "resourceTypes": [
                    "xmlhttprequest", "script", "image", "ping",
                    "sub_frame", "other",
                ],
            },
        })
    return dnr_rules


def _generate_content_js(build_dir: Path, rules: list[dict]) -> None:
    """Generate storage-aware content.js with toggle support."""
    rules_json = json.dumps(rules)
    data_attr = _DATA_ATTR

    content_js = f"""\
// LI Lite — auto-generated content script
// Storage-aware: reads disabled rules from chrome.storage.local
// Supports live toggling via popup without page reload
// Runs at document_idle to avoid interfering with React hydration

(function() {{
  'use strict';

  const RULES = {rules_json};
  const DATA_ATTR = '{data_attr}';
  const OBSERVER_DEBOUNCE_MS = 200;

  let disabledRules = new Set();
  let debounceTimer = null;

  function isApplicable(rule) {{
    const scope = rule.scope;
    if (scope === '*') return true;
    return window.location.href.startsWith(scope);
  }}

  function findElements(rule) {{
    const elements = [];
    if (rule.selector) {{
      try {{
        document.querySelectorAll(rule.selector).forEach(el => elements.push(el));
      }} catch(e) {{ /* invalid selector */ }}
    }}
    if (rule.xpath) {{
      try {{
        const result = document.evaluate(
          rule.xpath, document, null,
          XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
        );
        const xpathMatches = [];
        for (let i = 0; i < result.snapshotLength; i++) {{
          const el = result.snapshotItem(i);
          if (el && el.style) xpathMatches.push(el);
        }}
        // Keep only innermost matches — if A contains B, discard A.
        // XPaths like //div[.//p[text()='X']] match every ancestor div,
        // so without this filter we'd hide the entire page.
        for (const el of xpathMatches) {{
          const isAncestor = xpathMatches.some(other => other !== el && el.contains(other));
          if (!isAncestor && !elements.includes(el)) {{
            elements.push(el);
          }}
        }}
      }} catch(e) {{
        console.warn('[LI Lite] XPath error:', rule.xpath, e);
      }}
    }}
    return elements;
  }}

  function applyRule(rule) {{
    if (disabledRules.has(rule.id)) return;
    if (!isApplicable(rule)) return;

    const elements = findElements(rule);
    for (const el of elements) {{
      el.style.setProperty('display', 'none', 'important');
      const existing = el.getAttribute(DATA_ATTR) || '';
      const ids = existing ? existing.split(',') : [];
      if (!ids.includes(rule.id)) {{
        ids.push(rule.id);
        el.setAttribute(DATA_ATTR, ids.join(','));
      }}
    }}
  }}

  function unapplyRule(ruleId) {{
    document.querySelectorAll('[' + DATA_ATTR + ']').forEach(el => {{
      const ids = (el.getAttribute(DATA_ATTR) || '').split(',');
      const remaining = ids.filter(id => id !== ruleId);
      if (remaining.length === 0) {{
        el.style.removeProperty('display');
        el.removeAttribute(DATA_ATTR);
      }} else {{
        el.setAttribute(DATA_ATTR, remaining.join(','));
      }}
    }});
  }}

  function applyAll() {{
    for (const rule of RULES) applyRule(rule);
  }}

  function scheduleApply() {{
    if (debounceTimer) return;
    debounceTimer = setTimeout(() => {{
      debounceTimer = null;
      applyAll();
    }}, OBSERVER_DEBOUNCE_MS);
  }}

  // Initialize from storage
  if (typeof chrome !== 'undefined' && chrome.storage) {{
    chrome.storage.local.get('disabledRules', (result) => {{
      disabledRules = new Set(result.disabledRules || []);
      applyAll();
    }});

    // React to toggle changes from popup
    chrome.storage.onChanged.addListener((changes, area) => {{
      if (area !== 'local' || !changes.disabledRules) return;
      const oldSet = new Set(changes.disabledRules.oldValue || []);
      const newSet = new Set(changes.disabledRules.newValue || []);
      disabledRules = newSet;

      // Re-show rules that were just disabled
      for (const id of newSet) {{
        if (!oldSet.has(id)) unapplyRule(id);
      }}
      // Re-hide rules that were just enabled
      for (const id of oldSet) {{
        if (!newSet.has(id)) {{
          const rule = RULES.find(r => r.id === id);
          if (rule) applyRule(rule);
        }}
      }}
    }});
  }} else {{
    // Fallback for testing or non-extension context
    applyAll();
  }}

  // Re-apply on dynamic content changes (debounced to avoid mutation storms)
  const observer = new MutationObserver(scheduleApply);
  observer.observe(document.documentElement, {{
    childList: true,
    subtree: true,
  }});
}})();
"""
    with open(build_dir / "content.js", "w") as f:
        f.write(content_js)


def _generate_popup(build_dir: Path) -> None:
    """Generate popup HTML, CSS, and JS files."""
    zone_labels_json = json.dumps(_ZONE_LABELS)

    popup_html = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <div id="app">
    <h1>LI Lite</h1>
    <p id="subtitle">Toggle sections on/off</p>
    <div id="rules-container"></div>
  </div>
  <script src="popup.js"></script>
</body>
</html>
"""

    popup_css = """\
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  width: 320px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
  color: #333;
  background: #fff;
}

#app { padding: 12px 16px 16px; }

h1 {
  font-size: 16px;
  font-weight: 700;
  color: #0a66c2;
  margin-bottom: 2px;
}

#subtitle {
  font-size: 11px;
  color: #666;
  margin-bottom: 12px;
}

.zone-group { margin-bottom: 10px; }

.zone-header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #888;
  padding: 4px 0;
  border-bottom: 1px solid #eee;
  margin-bottom: 4px;
}

.rule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 0;
}

.rule-name {
  flex: 1;
  font-size: 13px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 8px;
}

/* Toggle switch */
.toggle {
  position: relative;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle .slider {
  position: absolute;
  inset: 0;
  background: #ccc;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
}

.toggle .slider::before {
  content: '';
  position: absolute;
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
}

.toggle input:checked + .slider {
  background: #0a66c2;
}

.toggle input:checked + .slider::before {
  transform: translateX(16px);
}
"""

    popup_js = f"""\
// LI Lite popup — toggle hide rules on/off
(function() {{
  'use strict';

  const ZONE_LABELS = {zone_labels_json};
  const ZONE_ORDER = [
    'top-nav', 'left-sidebar', 'main-feed',
    'right-sidebar', 'messaging', 'footer', 'overlay', 'other'
  ];

  async function init() {{
    const response = await fetch(chrome.runtime.getURL('rules-meta.json'));
    const rules = await response.json();

    const result = await chrome.storage.local.get('disabledRules');
    const disabledSet = new Set(result.disabledRules || []);

    // Group rules by zone
    const groups = {{}};
    for (const rule of rules) {{
      const zone = rule.zone || 'other';
      if (!groups[zone]) groups[zone] = [];
      groups[zone].push(rule);
    }}

    // Sort zones
    const sortedZones = Object.keys(groups).sort((a, b) => {{
      const ai = ZONE_ORDER.indexOf(a);
      const bi = ZONE_ORDER.indexOf(b);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    }});

    const container = document.getElementById('rules-container');

    for (const zone of sortedZones) {{
      const group = document.createElement('div');
      group.className = 'zone-group';

      const header = document.createElement('div');
      header.className = 'zone-header';
      header.textContent = ZONE_LABELS[zone] || zone.replace(/-/g, ' ');
      group.appendChild(header);

      for (const rule of groups[zone]) {{
        const row = document.createElement('div');
        row.className = 'rule-row';

        const name = document.createElement('span');
        name.className = 'rule-name';
        name.textContent = rule.name;
        name.title = rule.name;

        const toggle = document.createElement('label');
        toggle.className = 'toggle';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        // Checked = rule is ACTIVE (hiding), unchecked = disabled (showing)
        checkbox.checked = !disabledSet.has(rule.id);

        checkbox.addEventListener('change', async () => {{
          const stored = await chrome.storage.local.get('disabledRules');
          const disabled = new Set(stored.disabledRules || []);
          if (checkbox.checked) {{
            disabled.delete(rule.id);
          }} else {{
            disabled.add(rule.id);
          }}
          await chrome.storage.local.set({{ disabledRules: [...disabled] }});
        }});

        const slider = document.createElement('span');
        slider.className = 'slider';

        toggle.appendChild(checkbox);
        toggle.appendChild(slider);

        row.appendChild(name);
        row.appendChild(toggle);
        group.appendChild(row);
      }}

      container.appendChild(group);
    }}
  }}

  init();
}})();
"""

    with open(build_dir / "popup.html", "w") as f:
        f.write(popup_html)
    with open(build_dir / "popup.css", "w") as f:
        f.write(popup_css)
    with open(build_dir / "popup.js", "w") as f:
        f.write(popup_js)


def _find_latest_config() -> Path | None:
    """Find the most recent configuration JSON."""
    files = sorted(config.CONFIG_DIR.glob("*-configuration.json"), reverse=True)
    return files[0] if files else None


def _generate_placeholder_icons(icons_dir: Path) -> None:
    """Generate minimal PNG placeholder icons (1x1 blue pixel, just for manifest validity)."""
    import struct
    import zlib

    def make_png(size: int) -> bytes:
        """Generate a minimal valid PNG of given size with a blue square."""
        raw = b""
        for _y in range(size):
            raw += b"\x00"  # filter: none
            for _x in range(size):
                raw += b"\x00\x77\xc2\xff"  # LinkedIn blue RGBA

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
        ihdr = _png_chunk(b"IHDR", ihdr_data)
        compressed = zlib.compress(raw)
        idat = _png_chunk(b"IDAT", compressed)
        iend = _png_chunk(b"IEND", b"")

        return sig + ihdr + idat + iend

    def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

    for size, name in [(16, "icon16.png"), (48, "icon48.png"), (128, "icon128.png")]:
        with open(icons_dir / name, "wb") as f:
            f.write(make_png(size))
