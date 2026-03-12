"""Tests for Phase C: Interactive configuration (src/configure.py)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.configure import _find_latest_discovery, _truncate, configure


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_discovery(tmp_path, pages=None):
    """Write a discovery JSON file and return its path."""
    disc = {
        "discovered_at": "2026-03-10T12:00:00Z",
        "pages": pages if pages is not None else [],
    }
    disc_file = tmp_path / "20260310-1200-discovery.json"
    disc_file.write_text(json.dumps(disc))
    return disc_file


def _mixed_pages():
    """Return a pages list with LLM-identified sections and API calls."""
    return [
        {
            "url": "https://www.linkedin.com/feed/",
            "ui_components": [
                {
                    "id": "home-button",
                    "name": "Home button",
                    "xpath": "//header//a[contains(@href, '/feed')]",
                    "selector": 'header a[href*="/feed"]',
                    "zone": "top-nav",
                    "description": "Home navigation button",
                    "default_action": "keep",
                    "element_type": "structural",
                    "classification": "navigation",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
                {
                    "id": "linkedin-news",
                    "name": "LinkedIn News",
                    "xpath": "//div[contains(., 'LinkedIn News')]",
                    "selector": None,
                    "zone": "right-sidebar",
                    "description": "LinkedIn News top stories",
                    "default_action": "keep",
                    "element_type": "structural",
                    "classification": "sidebar-widget",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
                {
                    "id": "ad-slot",
                    "name": "Promoted ad slot",
                    "xpath": "//div[contains(., 'Promoted')]",
                    "selector": None,
                    "zone": "right-sidebar",
                    "description": "Sponsored content ad",
                    "default_action": "hide",
                    "element_type": "structural",
                    "classification": "promoted-content",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
            ],
            "api_calls": [
                {
                    "id": "feed-api",
                    "url_pattern": "www.linkedin.com/voyager/api/feed/*",
                    "name": "Feed data API",
                    "category": "core-data",
                    "description": "Main feed data endpoint",
                    "default_action": "keep",
                    "scope": "url-pattern:www.linkedin.com/voyager/api/feed/*",
                },
                {
                    "id": "analytics-call",
                    "url_pattern": "analytics.linkedin.com/*",
                    "name": "Analytics beacon",
                    "category": "analytics",
                    "description": "Usage analytics tracking",
                    "default_action": "block",
                    "scope": "url-pattern:analytics.linkedin.com/*",
                },
            ],
        },
    ]


def _mock_checkbox_keep_defaults():
    """Mock that keeps items whose default_keep=True."""
    def _factory(*args, **kwargs):
        choices = kwargs.get("choices", [])
        kept = []
        for c in choices:
            if c.get("enabled") and c.get("value") is not None:
                kept.append(c["value"])
        mock = MagicMock()
        mock.execute.return_value = kept
        return mock
    return _factory


def _mock_checkbox_keep_all():
    """Mock that keeps ALL items."""
    def _factory(*args, **kwargs):
        choices = kwargs.get("choices", [])
        kept = [c["value"] for c in choices if c.get("value") is not None]
        mock = MagicMock()
        mock.execute.return_value = kept
        return mock
    return _factory


def _mock_checkbox_keep_none():
    """Mock that keeps NOTHING."""
    def _factory(*args, **kwargs):
        mock = MagicMock()
        mock.execute.return_value = []
        return mock
    return _factory


# ===========================================================================
# 1. _find_latest_discovery
# ===========================================================================

class TestFindLatestDiscovery:

    def test_multiple_files_returns_newest(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        (tmp_path / "20260101-0800-discovery.json").write_text("{}")
        (tmp_path / "20260215-1400-discovery.json").write_text("{}")
        (tmp_path / "20260310-0900-discovery.json").write_text("{}")

        result = _find_latest_discovery()
        assert result is not None
        assert result.name == "20260310-0900-discovery.json"

    def test_empty_directory_returns_none(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
        assert _find_latest_discovery() is None


# ===========================================================================
# 2. _truncate
# ===========================================================================

class TestTruncate:

    def test_short_text_unchanged(self):
        assert _truncate("Hello", 80) == "Hello"

    def test_long_text_truncated(self):
        result = _truncate("A" * 100, 80)
        assert len(result) == 80
        assert result.endswith("…")

    def test_exact_length_unchanged(self):
        assert _truncate("A" * 80, 80) == "A" * 80


# ===========================================================================
# 3. configure()
# ===========================================================================

class TestConfigure:

    def test_accept_defaults_hides_ad_slot(self, tmp_path, monkeypatch):
        """Ad slot with default_action=hide should be blocked by default."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_defaults()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]

        # The ad-slot (default_action=hide) should be blocked
        blocked_ids = {r["id"] for r in rules}
        assert "ad-slot" in blocked_ids

        # Home button and LinkedIn News (default_action=keep) should NOT be blocked
        assert "home-button" not in blocked_ids
        assert "linkedin-news" not in blocked_ids

        # Network blocking is disabled — no API call rules should appear
        assert "analytics-call" not in blocked_ids
        assert "feed-api" not in blocked_ids

    def test_block_everything(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_none()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]

        # Network blocking is disabled — only UI components should appear
        pages = _mixed_pages()
        total_ui = sum(len(p.get("ui_components", [])) for p in pages)
        assert len(rules) == total_ui

    def test_allow_everything(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_all()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        assert output["rules"] == []

    def test_ui_rule_has_xpath(self, tmp_path, monkeypatch):
        """UI hide rules should include xpath from discovery."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_none()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        ui_rules = [r for r in output["rules"] if r["type"] == "ui_component"]
        assert any(r.get("xpath") for r in ui_rules)

    def test_output_json_structure(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_all()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        assert "configured_at" in output
        assert "based_on_discovery" in output
        assert "rules" in output

    def test_file_not_found_error(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        with pytest.raises(FileNotFoundError, match="No discovery file found"):
            configure(discovery_path=str(tmp_path / "nonexistent.json"))

    def test_empty_pages(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=[])
        result_path = configure(discovery_path=str(disc_file))
        output = json.loads(Path(result_path).read_text())
        assert output["rules"] == []
