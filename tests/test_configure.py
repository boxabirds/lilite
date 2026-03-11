"""Tests for Phase C: Interactive configuration (src/configure.py)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.configure import _BLOCK_BY_DEFAULT, _find_latest_discovery, configure


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
    """Return a pages list with classifications both inside and outside _BLOCK_BY_DEFAULT."""
    return [
        {
            "url": "https://www.linkedin.com/feed/",
            "ui_components": [
                {
                    "id": "nav-bar",
                    "selector": "#global-nav",
                    "classification": "navigation",
                    "description": "Main navigation bar",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
                {
                    "id": "feed-card-1",
                    "selector": ".feed-card",
                    "classification": "feed-card",
                    "description": "A normal feed card",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
                {
                    "id": "promoted-post-1",
                    "selector": ".promoted-post",
                    "classification": "promoted-content",
                    "description": "Sponsored post",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
                {
                    "id": "tracking-img",
                    "selector": "img.tracker",
                    "classification": "tracking-pixel",
                    "description": "1x1 tracking pixel",
                    "scope": "url:https://www.linkedin.com/feed/",
                },
            ],
            "api_calls": [
                {
                    "id": "feed-api",
                    "url_pattern": "https://www.linkedin.com/voyager/api/feed/*",
                    "classification": "rest-api",
                    "description": "Feed data endpoint",
                    "scope": "url-pattern:linkedin.com/voyager/*",
                    "vendor": "linkedin",
                },
                {
                    "id": "analytics-call",
                    "url_pattern": "https://analytics.linkedin.com/*",
                    "classification": "analytics",
                    "description": "Analytics beacon",
                    "scope": "url-pattern:analytics.linkedin.com/*",
                    "vendor": "linkedin",
                },
                {
                    "id": "ad-network-call",
                    "url_pattern": "https://ads.linkedin.com/*",
                    "classification": "ad-network",
                    "description": "Ad network call",
                    "scope": "url-pattern:ads.linkedin.com/*",
                    "vendor": "linkedin-ads",
                },
            ],
        },
    ]


def _mock_checkbox_returning(kept_names):
    """Create a mock for inquirer.checkbox that returns the given kept names."""
    def _factory(*args, **kwargs):
        mock = MagicMock()
        mock.execute.return_value = kept_names
        return mock
    return _factory


def _mock_checkbox_keep_defaults():
    """Mock that keeps items whose default_keep=True (simulates accepting defaults).

    The checkbox choices have enabled=True for items not in _BLOCK_BY_DEFAULT.
    We return the values of enabled choices.
    """
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
    """Mock that keeps ALL items (selects everything)."""
    def _factory(*args, **kwargs):
        choices = kwargs.get("choices", [])
        kept = [c["value"] for c in choices if c.get("value") is not None]
        mock = MagicMock()
        mock.execute.return_value = kept
        return mock
    return _factory


def _mock_checkbox_keep_none():
    """Mock that keeps NOTHING (deselects everything)."""
    def _factory(*args, **kwargs):
        mock = MagicMock()
        mock.execute.return_value = []
        return mock
    return _factory


# ===========================================================================
# 1. _BLOCK_BY_DEFAULT
# ===========================================================================


class TestBlockByDefault:
    """Tests for the _BLOCK_BY_DEFAULT set."""

    def test_exact_members(self):
        expected = {"tracking-pixel", "analytics", "ad-network", "promoted-content"}
        assert _BLOCK_BY_DEFAULT == expected

    @pytest.mark.parametrize(
        "classification",
        [
            "navigation",
            "feed-card",
            "sidebar-widget",
            "messaging",
            "notification",
            "modal",
            "other",
            "rest-api",
            "graphql",
            "websocket",
        ],
    )
    def test_non_blocked_classifications(self, classification):
        assert classification not in _BLOCK_BY_DEFAULT


# ===========================================================================
# 2. _find_latest_discovery
# ===========================================================================


class TestFindLatestDiscovery:
    """Tests for _find_latest_discovery."""

    def test_multiple_files_returns_newest(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        (tmp_path / "20260101-0800-discovery.json").write_text("{}")
        (tmp_path / "20260215-1400-discovery.json").write_text("{}")
        (tmp_path / "20260310-0900-discovery.json").write_text("{}")

        result = _find_latest_discovery()
        assert result is not None
        assert result.name == "20260310-0900-discovery.json"

    def test_single_file_returns_it(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        (tmp_path / "20260101-0800-discovery.json").write_text("{}")

        result = _find_latest_discovery()
        assert result is not None
        assert result.name == "20260101-0800-discovery.json"

    def test_empty_directory_returns_none(self, tmp_path, monkeypatch):
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        result = _find_latest_discovery()
        assert result is None


# ===========================================================================
# 3. configure()
# ===========================================================================


class TestConfigure:
    """Tests for the configure() function."""

    def test_accept_all_defaults(self, tmp_path, monkeypatch):
        """Accepting defaults blocks _BLOCK_BY_DEFAULT groups, allows others."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_defaults()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]

        # Blocked classifications should produce rules
        blocked_cls = {r["classification"] for r in rules}
        for cls in ("promoted-content", "tracking-pixel", "analytics", "ad-network"):
            assert cls in blocked_cls, f"{cls} should be blocked by default"

        # Allowed classifications should NOT produce rules
        for cls in ("navigation", "feed-card", "rest-api"):
            assert cls not in blocked_cls, f"{cls} should be allowed by default"

    def test_block_everything(self, tmp_path, monkeypatch):
        """When user deselects everything, all items generate rules."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_none()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]

        pages = _mixed_pages()
        total_ui = sum(len(p.get("ui_components", [])) for p in pages)
        total_api = sum(len(p.get("api_calls", [])) for p in pages)
        assert len(rules) == total_ui + total_api

    def test_allow_everything(self, tmp_path, monkeypatch):
        """When user selects everything, zero rules are generated."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=_mixed_pages())

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_all()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        assert output["rules"] == []

    def test_ui_rule_fields(self, tmp_path, monkeypatch):
        """UI hide rules contain the correct fields populated from the component."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        comp = {
            "id": "promo-widget",
            "selector": ".promo",
            "classification": "promoted-content",
            "description": "A promoted widget",
            "scope": "url:https://www.linkedin.com/feed/",
        }
        pages = [{"url": "https://www.linkedin.com/feed/", "ui_components": [comp], "api_calls": []}]
        disc_file = _make_discovery(tmp_path, pages=pages)

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_defaults()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]
        assert len(rules) == 1

        rule = rules[0]
        assert rule["id"] == "promo-widget"
        assert rule["type"] == "ui_component"
        assert rule["action"] == "hide"
        assert rule["selector"] == ".promo"
        assert rule["scope"] == "url:https://www.linkedin.com/feed/"
        assert rule["classification"] == "promoted-content"
        assert rule["description"] == "A promoted widget"

    def test_api_rule_fields(self, tmp_path, monkeypatch):
        """API block rules contain the correct fields populated from the api call."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        api = {
            "id": "tracker-beacon",
            "url_pattern": "https://tracking.example.com/*",
            "classification": "analytics",
            "description": "Analytics beacon",
            "scope": "url-pattern:tracking.example.com/*",
            "vendor": "example-analytics",
        }
        pages = [{"url": "https://www.linkedin.com/feed/", "ui_components": [], "api_calls": [api]}]
        disc_file = _make_discovery(tmp_path, pages=pages)

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_defaults()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]
        assert len(rules) == 1

        rule = rules[0]
        assert rule["id"] == "tracker-beacon"
        assert rule["type"] == "api_call"
        assert rule["action"] == "block"
        assert rule["url_pattern"] == "https://tracking.example.com/*"
        assert rule["scope"] == "url-pattern:tracking.example.com/*"
        assert rule["classification"] == "analytics"
        assert rule["vendor"] == "example-analytics"
        assert rule["description"] == "https://tracking.example.com/*"

    def test_output_json_structure(self, tmp_path, monkeypatch):
        """Output JSON has configured_at, based_on_discovery, and rules keys."""
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
        assert output["based_on_discovery"] == disc_file.name
        assert isinstance(output["rules"], list)

    def test_file_not_found_error(self, tmp_path, monkeypatch):
        """FileNotFoundError is raised when discovery file doesn't exist."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        with pytest.raises(FileNotFoundError, match="No discovery file found"):
            configure(discovery_path=str(tmp_path / "nonexistent.json"))

    def test_file_not_found_no_path_no_files(self, tmp_path, monkeypatch):
        """FileNotFoundError when no path given and no discovery files in config dir."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        with pytest.raises(FileNotFoundError, match="No discovery file found"):
            configure()

    def test_empty_pages_list(self, tmp_path, monkeypatch):
        """Discovery with empty pages list produces zero rules."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=[])

        result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        assert output["rules"] == []

    def test_missing_classification_defaults_to_other(self, tmp_path, monkeypatch):
        """Components without a classification key are grouped as 'other'."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        comp_no_class = {
            "id": "mystery-widget",
            "selector": ".mystery",
            "description": "Unknown widget",
        }
        pages = [
            {
                "url": "https://www.linkedin.com/feed/",
                "ui_components": [comp_no_class],
                "api_calls": [],
            },
        ]
        disc_file = _make_discovery(tmp_path, pages=pages)

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_none()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]
        assert len(rules) == 1
        assert rules[0]["classification"] == "other"

    def test_config_file_saved_to_config_dir(self, tmp_path, monkeypatch):
        """The output configuration file is saved inside config.CONFIG_DIR."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=[])

        result_path = configure(discovery_path=str(disc_file))

        assert Path(result_path).parent == tmp_path
        assert result_path.endswith("-configuration.json")

    def test_returns_path_as_string(self, tmp_path, monkeypatch):
        """configure() returns the path as a string."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        disc_file = _make_discovery(tmp_path, pages=[])

        result = configure(discovery_path=str(disc_file))
        assert isinstance(result, str)

    def test_ui_scope_defaults_to_page_url(self, tmp_path, monkeypatch):
        """When a UI component has no scope, it defaults to url:<page_url>."""
        import src.config as config
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

        comp = {
            "id": "no-scope-widget",
            "selector": ".ns",
            "classification": "promoted-content",
            "description": "No scope component",
            # no "scope" key
        }
        pages = [
            {
                "url": "https://www.linkedin.com/jobs/",
                "ui_components": [comp],
                "api_calls": [],
            },
        ]
        disc_file = _make_discovery(tmp_path, pages=pages)

        with patch("src.configure.inquirer") as mock_inq:
            mock_inq.checkbox = _mock_checkbox_keep_defaults()
            result_path = configure(discovery_path=str(disc_file))

        output = json.loads(Path(result_path).read_text())
        rules = output["rules"]
        assert len(rules) == 1
        assert rules[0]["scope"] == "url:https://www.linkedin.com/jobs/"
