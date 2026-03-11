"""Tests for Chrome extension build phase."""

import json
from pathlib import Path


def test_build_generates_valid_manifest(tmp_path, monkeypatch):
    """Build should produce a valid manifest.json with Manifest V3."""
    import src.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    # Create a minimal configuration file
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

    # Check CSS has the hide rule
    css = (build_path / "styles.css").read_text()
    assert "news-module" in css
    assert "display: none" in css

    # Check content.js has the selector
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
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    manifest = json.loads((Path(build_dir) / "manifest.json").read_text())

    assert "declarative_net_request" not in manifest
    assert manifest["permissions"] == []


def test_content_js_groups_selectors_by_scope(tmp_path, monkeypatch):
    """content.js should contain a SCOPE_MAP grouping selectors by URL scope."""
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
            },
            {
                "id": "jobs-sidebar",
                "type": "ui_component",
                "action": "hide",
                "selector": ".jobs-sidebar",
                "scope": "url:https://www.linkedin.com/jobs/",
                "classification": "sidebar-widget",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    assert "SCOPE_MAP" in js
    # Parse the SCOPE_MAP from the generated JS
    import re
    match = re.search(r'const SCOPE_MAP = ({.*?});', js, re.DOTALL)
    assert match, "SCOPE_MAP not found in content.js"
    scope_map = json.loads(match.group(1))

    assert "https://www.linkedin.com/feed/" in scope_map
    assert "https://www.linkedin.com/jobs/" in scope_map
    assert ".promo-card" in scope_map["https://www.linkedin.com/feed/"]
    assert ".jobs-sidebar" in scope_map["https://www.linkedin.com/jobs/"]


def test_content_js_unscoped_rules_go_to_global_key(tmp_path, monkeypatch):
    """Rules without a scope should be placed under the '*' global key."""
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
                # no scope field
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const SCOPE_MAP = ({.*?});', js, re.DOTALL)
    scope_map = json.loads(match.group(1))

    assert "*" in scope_map
    assert ".global-widget" in scope_map["*"]


def test_content_js_mixed_scoped_and_unscoped(tmp_path, monkeypatch):
    """Mix of scoped and unscoped rules should produce both URL keys and '*'."""
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
            },
            {
                "id": "unscoped",
                "type": "ui_component",
                "action": "hide",
                "selector": ".everywhere",
                "classification": "other",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const SCOPE_MAP = ({.*?});', js, re.DOTALL)
    scope_map = json.loads(match.group(1))

    assert "https://www.linkedin.com/feed/" in scope_map
    assert "*" in scope_map
    assert ".feed-only" in scope_map["https://www.linkedin.com/feed/"]
    assert ".everywhere" in scope_map["*"]


def test_content_js_no_hide_rules_is_noop(tmp_path, monkeypatch):
    """With zero hide rules, content.js should have an empty SCOPE_MAP."""
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
    match = re.search(r'const SCOPE_MAP = ({.*?});', js, re.DOTALL)
    scope_map = json.loads(match.group(1))
    assert scope_map == {}


def test_content_js_same_scope_groups_selectors(tmp_path, monkeypatch):
    """Multiple rules with the same scope should be grouped into one array."""
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
            },
            {
                "id": "promo2",
                "type": "ui_component",
                "action": "hide",
                "selector": ".promo-b",
                "scope": "url:https://www.linkedin.com/feed/",
                "classification": "promoted-content",
            },
        ],
    }
    cfg_file = tmp_path / "20260101-0000-configuration.json"
    cfg_file.write_text(json.dumps(cfg))

    from src.build import build
    build_dir = build(config_path=str(cfg_file))
    js = (Path(build_dir) / "content.js").read_text()

    import re
    match = re.search(r'const SCOPE_MAP = ({.*?});', js, re.DOTALL)
    scope_map = json.loads(match.group(1))

    feed_selectors = scope_map["https://www.linkedin.com/feed/"]
    assert ".promo-a" in feed_selectors
    assert ".promo-b" in feed_selectors
    assert len(feed_selectors) == 2


def test_placeholder_icons_are_valid_png(tmp_path):
    """Generated placeholder icons should be valid PNG files."""
    from src.build import _generate_placeholder_icons
    _generate_placeholder_icons(tmp_path)

    for name in ("icon16.png", "icon48.png", "icon128.png"):
        data = (tmp_path / name).read_bytes()
        # PNG magic bytes
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
