"""Tests for pure helper functions in src/discovery.py."""

import json

from src.discovery import (
    _is_static_asset,
    _is_selector_too_broad,
    _is_infrastructure_url,
    _strip_html_noise,
    _slugify,
    _zone_to_classification,
    _parse_page_blocks,
    _merge_network_classifications,
    _url_to_pattern,
    _make_id,
    _GENERIC_SELECTOR_DENYLIST,
    _APP_ROOT_SELECTOR_DENYLIST,
    _INFRASTRUCTURE_URL_PATTERNS,
    MAX_CSS_SELECTOR_MATCHES,
)


# ---------------------------------------------------------------------------
# _is_static_asset
# ---------------------------------------------------------------------------

class TestIsStaticAsset:
    """Tests for _is_static_asset(url)."""

    def test_media_licdn_is_static(self):
        assert _is_static_asset("https://media.licdn.com/dms/image/v2/abc/logo.jpg")

    def test_static_licdn_is_static(self):
        assert _is_static_asset("https://static.licdn.com/aero-v1/sc/h/some-hash")

    def test_js_extension_is_static(self):
        assert _is_static_asset("https://example.com/bundle.js")

    def test_css_extension_is_static(self):
        assert _is_static_asset("https://example.com/styles.css")

    def test_png_extension_is_static(self):
        assert _is_static_asset("https://example.com/image.png")

    def test_woff2_extension_is_static(self):
        assert _is_static_asset("https://example.com/font.woff2")

    def test_api_call_not_static(self):
        assert not _is_static_asset("https://www.linkedin.com/voyager/api/feed/updates")

    def test_html_page_not_static(self):
        assert not _is_static_asset("https://www.linkedin.com/feed/")

    def test_json_api_not_static(self):
        assert not _is_static_asset("https://www.linkedin.com/api/data.json")
        # Note: .json is not in _STATIC_EXTENSIONS — it's API data, not a static asset


# ---------------------------------------------------------------------------
# _strip_html_noise
# ---------------------------------------------------------------------------

class TestStripHtmlNoise:
    """Tests for _strip_html_noise()."""

    def test_removes_script_tags(self):
        html = '<div>Hello</div><script>alert("x")</script><div>World</div>'
        result = _strip_html_noise(html)
        assert "<script" not in result
        assert "alert" not in result
        assert "Hello" in result

    def test_removes_style_tags(self):
        html = '<style>.foo { color: red; }</style><div>Content</div>'
        result = _strip_html_noise(html)
        assert "<style" not in result
        assert "Content" in result

    def test_removes_svg_tags(self):
        html = '<div>Before</div><svg viewBox="0 0 24 24"><path d="M0 0"/></svg><div>After</div>'
        result = _strip_html_noise(html)
        assert "<svg" not in result
        assert "After" in result

    def test_removes_inline_styles(self):
        html = '<div style="display: none; color: red;">Hidden</div>'
        result = _strip_html_noise(html)
        assert 'style=' not in result
        assert "Hidden" in result

    def test_removes_class_attributes(self):
        html = '<div class="abc123 _hash456">Content</div>'
        result = _strip_html_noise(html)
        assert 'class=' not in result
        assert "Content" in result

    def test_removes_data_uris(self):
        html = '<img src="data:image/png;base64,iVBOR...">'
        result = _strip_html_noise(html)
        assert "base64" not in result

    def test_removes_html_comments(self):
        html = '<div>Visible</div><!-- secret --><div>Also visible</div>'
        result = _strip_html_noise(html)
        assert "secret" not in result

    def test_removes_noscript(self):
        html = '<noscript><div>Fallback</div></noscript><div>Main</div>'
        result = _strip_html_noise(html)
        assert "Fallback" not in result
        assert "Main" in result

    def test_preserves_semantic_structure(self):
        html = '<header><nav><a href="/feed">Home</a></nav></header>'
        result = _strip_html_noise(html)
        assert '<header>' in result
        assert '<nav>' in result
        assert 'href="/feed"' in result


# ---------------------------------------------------------------------------
# _parse_page_blocks
# ---------------------------------------------------------------------------

class TestParsePageBlocks:
    """Tests for _parse_page_blocks()."""

    def test_valid_json_array(self):
        raw = json.dumps([
            {"name": "Jobs button", "xpath": "//a[@href='/jobs']",
             "zone": "top-nav", "description": "Jobs link", "default_action": "keep"},
        ])
        result = _parse_page_blocks(raw, "https://www.linkedin.com/feed/")
        assert len(result) == 1
        assert result[0]["name"] == "Jobs button"
        assert result[0]["xpath"] == "//a[@href='/jobs']"
        assert result[0]["zone"] == "top-nav"
        assert result[0]["default_action"] == "keep"
        assert result[0]["scope"] == "url:https://www.linkedin.com/feed/"

    def test_skips_entries_without_name(self):
        raw = json.dumps([
            {"xpath": "//div", "zone": "other"},
        ])
        result = _parse_page_blocks(raw, "https://example.com")
        assert len(result) == 0

    def test_skips_entries_without_xpath(self):
        raw = json.dumps([
            {"name": "Something", "zone": "other"},
        ])
        result = _parse_page_blocks(raw, "https://example.com")
        assert len(result) == 0

    def test_invalid_json_returns_empty(self):
        result = _parse_page_blocks("not json at all", "https://example.com")
        assert result == []

    def test_extracts_json_from_markdown(self):
        raw = '```json\n[{"name": "Nav", "xpath": "//nav", "zone": "top-nav"}]\n```'
        result = _parse_page_blocks(raw, "https://example.com")
        assert len(result) == 1

    def test_id_is_slugified(self):
        raw = json.dumps([
            {"name": "LinkedIn News Widget", "xpath": "//div", "zone": "right-sidebar"},
        ])
        result = _parse_page_blocks(raw, "https://example.com")
        assert result[0]["id"] == "linkedin-news-widget"

    def test_default_action_hide_sets_promoted_classification(self):
        raw = json.dumps([
            {"name": "Ad slot", "xpath": "//div", "zone": "right-sidebar",
             "default_action": "hide"},
        ])
        result = _parse_page_blocks(raw, "https://example.com")
        assert result[0]["classification"] == "promoted-content"


# ---------------------------------------------------------------------------
# _merge_network_classifications
# ---------------------------------------------------------------------------

class TestMergeNetworkClassifications:
    """Tests for _merge_network_classifications()."""

    def test_merges_by_url_pattern(self):
        calls = [
            {"url_pattern": "www.linkedin.com/feed/", "method": "GET", "id": "feed"},
        ]
        raw = json.dumps([
            {"url_pattern": "www.linkedin.com/feed/", "name": "Feed page",
             "category": "core-data", "description": "Main feed", "default_action": "keep"},
        ])
        result = _merge_network_classifications(calls, raw)
        assert result[0]["name"] == "Feed page"
        assert result[0]["category"] == "core-data"
        assert result[0]["default_action"] == "keep"

    def test_unmatched_calls_get_defaults(self):
        calls = [
            {"url_pattern": "unknown.com/api", "method": "GET", "id": "x"},
        ]
        raw = json.dumps([])
        result = _merge_network_classifications(calls, raw)
        assert result[0]["name"] == "unknown.com/api"
        assert result[0]["category"] == "other"

    def test_invalid_json_falls_back(self):
        calls = [
            {"url_pattern": "example.com/api", "method": "GET", "id": "y"},
        ]
        result = _merge_network_classifications(calls, "garbage")
        assert result[0]["category"] == "other"


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:

    def test_basic_name(self):
        assert _slugify("Jobs button") == "jobs-button"

    def test_special_chars(self):
        assert _slugify("LinkedIn News — Top Stories") == "linkedin-news-top-stories"

    def test_truncation(self):
        assert len(_slugify("A" * 100)) <= 50

    def test_empty_string(self):
        assert _slugify("") == "unknown"


# ---------------------------------------------------------------------------
# _zone_to_classification
# ---------------------------------------------------------------------------

class TestZoneToClassification:

    def test_hide_action_returns_promoted(self):
        assert _zone_to_classification("right-sidebar", "hide") == "promoted-content"

    def test_top_nav(self):
        assert _zone_to_classification("top-nav", "keep") == "navigation"

    def test_left_sidebar(self):
        assert _zone_to_classification("left-sidebar", "keep") == "sidebar-widget"

    def test_main_feed(self):
        assert _zone_to_classification("main-feed", "keep") == "feed-card"

    def test_unknown_zone(self):
        assert _zone_to_classification("something-new", "keep") == "other"


# ---------------------------------------------------------------------------
# _url_to_pattern
# ---------------------------------------------------------------------------

class TestUrlToPattern:

    def test_numeric_segments_replaced(self):
        result = _url_to_pattern("https://www.linkedin.com/in/12345/detail")
        assert "12345" not in result

    def test_hex_segments_replaced(self):
        result = _url_to_pattern("https://www.linkedin.com/post/abcdef1234567890")
        assert "abcdef1234567890" not in result

    def test_query_params_stripped(self):
        result = _url_to_pattern("https://www.linkedin.com/feed/?sort=top")
        assert "sort" not in result

    def test_preserves_non_numeric_paths(self):
        result = _url_to_pattern("https://www.linkedin.com/feed/")
        assert "feed" in result


# ---------------------------------------------------------------------------
# _make_id
# ---------------------------------------------------------------------------

class TestMakeId:

    def test_last_path_segment(self):
        assert _make_id("www.linkedin.com/voyager/api/feed/updates") == "updates"

    def test_strips_wildcards(self):
        assert _make_id("www.linkedin.com/voyager/api/feed/*") == "feed"

    def test_truncation(self):
        assert len(_make_id(f"www.linkedin.com/{'a' * 100}")) <= 40

    def test_all_wildcards(self):
        assert _make_id("*/*/*") == "unknown"


# ---------------------------------------------------------------------------
# _is_selector_too_broad
# ---------------------------------------------------------------------------

class TestIsSelectorTooBroad:

    def test_generic_role_menu_is_broad(self):
        assert _is_selector_too_broad('div[role="menu"]', 1)

    def test_generic_role_button_is_broad(self):
        assert _is_selector_too_broad('div[role="button"]', 1)

    def test_all_denylist_entries_are_broad(self):
        for selector in _GENERIC_SELECTOR_DENYLIST:
            assert _is_selector_too_broad(selector, 0), f"{selector} should be broad"

    def test_specific_id_selector_not_broad(self):
        assert not _is_selector_too_broad('#my-widget', 1)

    def test_specific_aria_label_not_broad(self):
        assert not _is_selector_too_broad('[aria-label="Jobs"]', 1)

    def test_selector_exceeding_max_matches_is_broad(self):
        assert _is_selector_too_broad('.some-class', MAX_CSS_SELECTOR_MATCHES + 1)

    def test_selector_at_max_matches_not_broad(self):
        assert not _is_selector_too_broad('.some-class', MAX_CSS_SELECTOR_MATCHES)

    def test_none_selector_not_broad(self):
        assert not _is_selector_too_broad(None, 0)

    def test_app_root_selectors_are_broad(self):
        for selector in _APP_ROOT_SELECTOR_DENYLIST:
            assert _is_selector_too_broad(selector, 1), f"{selector} should be broad"

    def test_root_id_is_broad_even_with_one_match(self):
        assert _is_selector_too_broad('#root', 1)


# ---------------------------------------------------------------------------
# _is_infrastructure_url
# ---------------------------------------------------------------------------

class TestIsInfrastructureUrl:

    def test_trackO11y_is_infrastructure(self):
        assert _is_infrastructure_url("www.linkedin.com/rest/trackO11yApi/trackO11y")

    def test_trackObserve_is_infrastructure(self):
        assert _is_infrastructure_url("www.linkedin.com/rest/trackObserveApi/trackObserve")

    def test_sensorCollect_is_infrastructure(self):
        assert _is_infrastructure_url("www.linkedin.com/rest/sensorCollect")

    def test_regular_analytics_not_infrastructure(self):
        assert not _is_infrastructure_url("analytics.linkedin.com/tracking")

    def test_feed_api_not_infrastructure(self):
        assert not _is_infrastructure_url("www.linkedin.com/voyager/api/feed/updates")

    def test_all_patterns_are_caught(self):
        for pattern in _INFRASTRUCTURE_URL_PATTERNS:
            url = f"www.linkedin.com/rest/{pattern}"
            assert _is_infrastructure_url(url), f"Pattern '{pattern}' not caught"


# ---------------------------------------------------------------------------
# _merge_network_classifications — infrastructure override
# ---------------------------------------------------------------------------

class TestMergeNetworkClassificationsInfraOverride:

    def test_trackO11y_overridden_to_infrastructure(self):
        calls = [
            {"url_pattern": "www.linkedin.com/rest/trackO11yApi/trackO11y",
             "method": "POST", "id": "trackO11y"},
        ]
        raw = json.dumps([
            {"url_pattern": "www.linkedin.com/rest/trackO11yApi/trackO11y",
             "name": "Error Tracking", "category": "analytics",
             "description": "Client error tracking", "default_action": "block"},
        ])
        result = _merge_network_classifications(calls, raw)
        assert result[0]["category"] == "infrastructure"
        assert result[0]["default_action"] == "keep"

    def test_regular_analytics_not_overridden(self):
        calls = [
            {"url_pattern": "analytics.linkedin.com/pixel",
             "method": "GET", "id": "pixel"},
        ]
        raw = json.dumps([
            {"url_pattern": "analytics.linkedin.com/pixel",
             "name": "Pixel", "category": "analytics",
             "description": "Tracking pixel", "default_action": "block"},
        ])
        result = _merge_network_classifications(calls, raw)
        assert result[0]["category"] == "analytics"
        assert result[0]["default_action"] == "block"
