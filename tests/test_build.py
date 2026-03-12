"""Tests for Chrome extension build phase."""

import json
from pathlib import Path


def test_build_generates_valid_manifest(tmp_path, monkeypatch):
    """Build should produce a valid manifest.json with Manifest V3."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test-discovery.json",
        "rules": [
            {
                "id": "tracker",
                "type": "api_call",
                "action": "block",
                "url_pattern": "px.ads.linkedin.com/*",
                "scope": "url-pattern:px.ads.linkedin.com/*",
                "classification": "tracking-pixel",
            },
            {
                "id": "sidebar-news",
                "type": "ui_component",
                "action": "hide",
                "selector": "[data-test-id='news-module']",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "sidebar-widget",
                "description": "LinkedIn News sidebar",
                "zone": "right-sidebar",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    build_path = Path(build_dir)

    # Check manifest
    manifest = json.loads((build_path / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert manifest["name"] == "LI Lite"
    assert "declarative_net_request" in manifest
    assert "storage" in manifest["permissions"]
    assert "declarativeNetRequest" in manifest["permissions"]
    assert "action" in manifest
    assert manifest["action"]["default_popup"] == "popup.html"

    # Check content.js has the rule
    js = (build_path / "content.js").read_text()
    assert "news-module" in js

    # Check rules.json has the block rule
    rules = json.loads((build_path / "rules.json").read_text())
    assert len(rules) == 1
    assert rules[0]["action"]["type"] == "block"
    assert "px.ads.linkedin.com" in rules[0]["condition"]["urlFilter"]

    # Check icons exist
    assert (build_path / "icons" / "icon16.png").exists()
    assert (build_path / "icons" / "icon128.png").exists()


def test_build_no_block_rules_omits_dnr(tmp_path, monkeypatch):
    """When there are no block rules, manifest should not require declarativeNetRequest."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "widget",
                "type": "ui_component",
                "action": "hide",
                "selector": ".some-widget",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "sidebar-widget",
                "zone": "right-sidebar",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    manifest = json.loads((Path(build_dir) / "manifest.json").read_text())

    assert "declarative_net_request" not in manifest
    assert "storage" in manifest["permissions"]
    assert "declarativeNetRequest" not in manifest["permissions"]


def test_content_js_has_rules_array(tmp_path, monkeypatch):
    """content.js should contain a RULES array with rule objects."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "feed-promo",
                "type": "ui_component",
                "action": "hide",
                "selector": ".promo-card",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "promoted-content",
                "zone": "main-feed",
            },
            {
                "id": "jobs-sidebar",
                "type": "ui_component",
                "action": "hide",
                "selector": ".jobs-sidebar",
                "scope": "url:https://www.linkedin.com/jobs/",
                "classification": "sidebar-widget",
                "zone": "right-sidebar",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    assert "RULES" in js
    # Parse the RULES array from the generated JS
    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    assert match, "RULES not found in content.js"
    rules = json.loads(match.group(1))

    assert len(rules) == 2
    ids = {r["id"] for r in rules}
    assert "feed-promo" in ids
    assert "jobs-sidebar" in ids

    # Check scopes are extracted correctly
    scopes = {r["id"]: r["scope"] for r in rules}
    assert scopes["feed-promo"] == "https://www.linkedin.com/feed/"
    assert scopes["jobs-sidebar"] == "https://www.linkedin.com/jobs/"


def test_content_js_unscoped_rules_go_to_global(tmp_path, monkeypatch):
    """Rules without a scope should have scope '*'."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "global-widget",
                "type": "ui_component",
                "action": "hide",
                "selector": ".global-widget",
                "classification": "other",
                "zone": "other",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    assert rules[0]["scope"] == "*"


def test_content_js_no_hide_rules_empty_rules(tmp_path, monkeypatch):
    """With zero hide rules, content.js should have an empty RULES array."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "tracker",
                "type": "api_call",
                "action": "block",
                "url_pattern": "px.ads.linkedin.com/*",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))
    assert rules == []


def test_content_js_same_scope_groups_rules(tmp_path, monkeypatch):
    """Multiple rules with the same scope should both appear in RULES."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "promo1",
                "type": "ui_component",
                "action": "hide",
                "selector": ".promo-a",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "promoted-content",
                "zone": "main-feed",
            },
            {
                "id": "promo2",
                "type": "ui_component",
                "action": "hide",
                "selector": ".promo-b",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "promoted-content",
                "zone": "main-feed",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    selectors = [r["selector"] for r in rules]
    assert ".promo-a" in selectors
    assert ".promo-b" in selectors
    assert len(rules) == 2


def test_build_with_xpath_only_rules(tmp_path, monkeypatch):
    """Build handles rules that have xpath but no CSS selector."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "linkedin-news",
                "type": "ui_component",
                "action": "hide",
                "xpath": "//div[contains(., 'LinkedIn News')]",
                "selector": None,
                "scope": "url:https://www.linkedin.com/feed/",
                "description": "LinkedIn News widget",
                "zone": "right-sidebar",
            },
            {
                "id": "nav-with-css",
                "type": "ui_component",
                "action": "hide",
                "xpath": "//header//a[@href='/jobs']",
                "selector": 'header a[href*="/jobs"]',
                "scope": "url:https://www.linkedin.com/feed/",
                "description": "Jobs button",
                "zone": "top-nav",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    build_path = Path(build_dir)

    js = (build_path / "content.js").read_text()

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    # Both rules should be in RULES
    assert len(rules) == 2
    xpath_only = next(r for r in rules if r["id"] == "linkedin-news")
    assert xpath_only["xpath"] == "//div[contains(., 'LinkedIn News')]"
    assert xpath_only["selector"] is None

    css_rule = next(r for r in rules if r["id"] == "nav-with-css")
    assert css_rule["selector"] == 'header a[href*="/jobs"]'
    assert css_rule["xpath"] == "//header//a[@href='/jobs']"


def test_build_with_structural_container_selectors(tmp_path, monkeypatch):
    """Build correctly handles structural container selectors."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "sidebar",
                "type": "ui_component",
                "action": "hide",
                "selector": '[role="complementary"]',
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "sidebar-widget",
                "description": "Right sidebar",
                "zone": "right-sidebar",
            },
            {
                "id": "messaging-overlay",
                "type": "ui_component",
                "action": "hide",
                "selector": "#msg-overlay",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "messaging",
                "description": "Messaging overlay",
                "zone": "overlay",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    build_path = Path(build_dir)

    js = (build_path / "content.js").read_text()
    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    selectors = [r["selector"] for r in rules]
    assert '[role="complementary"]' in selectors
    assert "#msg-overlay" in selectors


def test_duplicate_selectors_deduplicated(tmp_path, monkeypatch):
    """Duplicate selector+scope combos should be deduplicated."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "rule-a",
                "type": "ui_component",
                "action": "hide",
                "selector": "div.shared-selector",
                "xpath": "//div[@class='shared']",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "right-sidebar",
            },
            {
                "id": "rule-b",
                "type": "ui_component",
                "action": "hide",
                "selector": "div.shared-selector",
                "xpath": "//div[@class='shared']",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "right-sidebar",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    # Should have only 1 entry after dedup
    assert len(rules) == 1


def test_build_generates_popup_files(tmp_path, monkeypatch):
    """Build should generate popup.html, popup.js, popup.css."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "widget",
                "type": "ui_component",
                "action": "hide",
                "selector": ".widget",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "right-sidebar",
                "description": "Some widget",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))

    assert (build_dir / "popup.html").exists()
    assert (build_dir / "popup.js").exists()
    assert (build_dir / "popup.css").exists()

    # Popup HTML should reference popup.js and popup.css
    popup_html = (build_dir / "popup.html").read_text()
    assert "popup.js" in popup_html
    assert "popup.css" in popup_html


def test_build_generates_rules_meta_json(tmp_path, monkeypatch):
    """Build should generate rules-meta.json with rule metadata."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "news",
                "type": "ui_component",
                "action": "hide",
                "selector": ".news",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "right-sidebar",
                "description": "LinkedIn News",
            },
            {
                "id": "premium",
                "type": "ui_component",
                "action": "hide",
                "xpath": "//div[contains(., 'Premium')]",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "left-sidebar",
                "description": "Try Premium",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))

    meta = json.loads((build_dir / "rules-meta.json").read_text())
    assert len(meta) == 2
    assert meta[0]["id"] == "news"
    assert meta[0]["name"] == "LinkedIn News"
    assert meta[0]["zone"] == "right-sidebar"
    assert meta[1]["id"] == "premium"
    assert meta[1]["zone"] == "left-sidebar"


def test_content_js_uses_storage_api(tmp_path, monkeypatch):
    """content.js should use chrome.storage for toggle support."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "widget",
                "type": "ui_component",
                "action": "hide",
                "selector": ".widget",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "other",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))
    js = (build_dir / "content.js").read_text()

    assert "chrome.storage.local" in js
    assert "disabledRules" in js
    assert "data-lilite-rule" in js
    assert "unapplyRule" in js


def test_content_js_mixed_scoped_and_unscoped(tmp_path, monkeypatch):
    """Mix of scoped and unscoped rules should both appear."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "scoped",
                "type": "ui_component",
                "action": "hide",
                "selector": ".feed-only",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "promoted-content",
                "zone": "main-feed",
            },
            {
                "id": "unscoped",
                "type": "ui_component",
                "action": "hide",
                "selector": ".everywhere",
                "classification": "other",
                "zone": "other",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    scoped = next(r for r in rules if r["id"] == "scoped")
    unscoped = next(r for r in rules if r["id"] == "unscoped")
    assert scoped["scope"] == "https://www.linkedin.com/feed/"
    assert unscoped["scope"] == "*"


def test_styles_css_is_empty_of_hide_rules(tmp_path, monkeypatch):
    """styles.css should not contain display:none rules (all hiding is via JS)."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "widget",
                "type": "ui_component",
                "action": "hide",
                "selector": ".widget",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "other",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))
    css = (build_dir / "styles.css").read_text()

    assert "display: none" not in css


def test_build_strips_root_selectors(tmp_path, monkeypatch):
    """Build must strip #root and other app-root selectors that hide the entire page."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "profile-card",
                "type": "ui_component",
                "action": "hide",
                "selector": "#root",
                "xpath": "//div[.//p[text()='Profile viewers']]",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "left-sidebar",
            },
            {
                "id": "safe-rule",
                "type": "ui_component",
                "action": "hide",
                "selector": "[aria-label='Jobs']",
                "xpath": "//a[contains(@href, '/jobs')]",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "top-nav",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))
    js = (build_dir / "content.js").read_text()

    # #root must not appear as a selector in any rule
    assert '"#root"' not in js

    import re
    match = re.search(r'const RULES = (\[.*?\]);', js, re.DOTALL)
    rules = json.loads(match.group(1))

    # profile-card rule should still exist but with selector stripped to null
    profile = next(r for r in rules if r["id"] == "profile-card")
    assert profile["selector"] is None
    assert profile["xpath"] == "//div[.//p[text()='Profile viewers']]"

    # safe rule should be untouched
    safe = next(r for r in rules if r["id"] == "safe-rule")
    assert safe["selector"] == "[aria-label='Jobs']"


def test_manifest_uses_document_idle(tmp_path, monkeypatch):
    """Content script must run at document_idle to avoid React hydration conflicts."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))
    manifest = json.loads((build_dir / "manifest.json").read_text())

    assert manifest["content_scripts"][0]["run_at"] == "document_idle"


def test_content_js_has_debounced_observer(tmp_path, monkeypatch):
    """MutationObserver should be debounced to avoid mutation storms."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    cfg = {
        "configured_at": "2026-01-01T00:00:00Z",
        "based_on_discovery": "test.json",
        "rules": [
            {
                "id": "widget",
                "type": "ui_component",
                "action": "hide",
                "selector": ".widget",
                "scope": "url:https://www.linkedin.com/feed/",
                "zone": "other",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = Path(build(config_path=str(cfg_file)))
    js = (build_dir / "content.js").read_text()

    assert "OBSERVER_DEBOUNCE_MS" in js
    assert "scheduleApply" in js
    assert "debounceTimer" in js


def test_placeholder_icons_are_valid_png(tmp_path):
    """Generated placeholder icons should be valid PNG files."""
    from src.build import _generate_placeholder_icons
    _generate_placeholder_icons(tmp_path)

    for name in ("icon16.png", "icon48.png", "icon128.png"):
        data = (tmp_path / name).read_bytes()
        # PNG magic bytes
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
