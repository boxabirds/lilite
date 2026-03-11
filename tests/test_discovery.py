"""Tests for pure helper functions in src/discovery.py."""

import pytest

from src.discovery import (
    _classify_network_call,
    _classify_ui_component,
    _url_to_pattern,
    _make_id,
)


# ---------------------------------------------------------------------------
# _classify_network_call
# ---------------------------------------------------------------------------

class TestClassifyNetworkCall:
    """Tests for _classify_network_call(url, entry)."""

    # -- Named tracking vendors --

    def test_linkedin_ads_pixel(self):
        url = "https://px.ads.linkedin.com/collect?v=2&fmt=js"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "tracking-pixel"
        assert vendor == "linkedin-ads"

    def test_linkedin_snap(self):
        url = "https://snap.licdn.com/li.lms-analytics/insight.min.js"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "tracking-pixel"
        assert vendor == "linkedin-snap"

    def test_google_analytics(self):
        url = "https://www.google-analytics.com/analytics.js"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor == "google-analytics"

    def test_google_tag_manager(self):
        url = "https://www.googletagmanager.com/gtag/js?id=UA-12345"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor == "google-analytics"

    def test_doubleclick(self):
        url = "https://ad.doubleclick.net/ddm/activity/src=1234"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "ad-network"
        assert vendor == "doubleclick"

    def test_meta_pixel(self):
        url = "https://www.facebook.com/tr?id=123456&ev=PageView"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "tracking-pixel"
        assert vendor == "meta-pixel"

    def test_microsoft_ads(self):
        url = "https://bat.bing.com/action/0?ti=12345"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "tracking-pixel"
        assert vendor == "microsoft-ads"

    # -- Generic tracking / analytics patterns --

    def test_generic_analytics_pattern(self):
        url = "https://example.com/analytics/event"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor is None

    def test_generic_tracking_pattern(self):
        url = "https://example.com/tracking/pixel.gif"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor is None

    def test_generic_telemetry_pattern(self):
        url = "https://example.com/telemetry/v1/collect"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor is None

    def test_generic_beacon_pattern(self):
        url = "https://example.com/beacon?event=load"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor is None

    def test_generic_ad_network_ads_dot(self):
        url = "https://ads.example.com/show"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "ad-network"
        assert vendor is None

    def test_generic_ad_network_ad_dash(self):
        url = "https://example.com/ad-banner/image"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "ad-network"
        assert vendor is None

    def test_generic_ad_network_adserver(self):
        url = "https://example.com/adserver/serve?id=5"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "ad-network"
        assert vendor is None

    # -- Static assets --

    def test_static_js(self):
        cls, vendor = _classify_network_call("https://cdn.example.com/app.js", {})
        assert cls == "static-asset"
        assert vendor is None

    def test_static_css(self):
        cls, vendor = _classify_network_call("https://cdn.example.com/style.css", {})
        assert cls == "static-asset"
        assert vendor is None

    def test_static_png(self):
        cls, vendor = _classify_network_call("https://cdn.example.com/image.png", {})
        assert cls == "static-asset"
        assert vendor is None

    def test_static_woff2(self):
        cls, vendor = _classify_network_call("https://cdn.example.com/font.woff2", {})
        assert cls == "static-asset"
        assert vendor is None

    def test_static_svg(self):
        cls, vendor = _classify_network_call("https://cdn.example.com/icon.svg", {})
        assert cls == "static-asset"
        assert vendor is None

    def test_static_avif(self):
        cls, vendor = _classify_network_call("https://cdn.example.com/photo.avif", {})
        assert cls == "static-asset"
        assert vendor is None

    # -- WebSocket --

    def test_websocket_wss(self):
        cls, vendor = _classify_network_call("wss://realtime.linkedin.com/socket", {})
        assert cls == "websocket"
        assert vendor is None

    def test_websocket_ws(self):
        cls, vendor = _classify_network_call("ws://localhost:8080/ws", {})
        assert cls == "websocket"
        assert vendor is None

    # -- GraphQL --

    def test_graphql(self):
        cls, vendor = _classify_network_call(
            "https://www.linkedin.com/graphql?variables=(foo:bar)", {}
        )
        assert cls == "graphql"
        assert vendor is None

    # -- LinkedIn REST API --

    def test_voyager_api(self):
        cls, vendor = _classify_network_call(
            "https://www.linkedin.com/voyager/api/feed/updates", {}
        )
        assert cls == "rest-api"
        assert vendor is None

    def test_api_path(self):
        cls, vendor = _classify_network_call(
            "https://www.linkedin.com/api/identity/profiles", {}
        )
        assert cls == "rest-api"
        assert vendor is None

    def test_generic_linkedin_url(self):
        """A linkedin.com URL that doesn't match any specific pattern -> rest-api."""
        cls, vendor = _classify_network_call(
            "https://www.linkedin.com/feed/", {}
        )
        assert cls == "rest-api"
        assert vendor is None

    # -- Third party --

    def test_third_party_url(self):
        cls, vendor = _classify_network_call("https://example.com/some/page", {})
        assert cls == "other"
        assert vendor is None

    # -- Priority tests --

    def test_tracking_beats_static_extension(self):
        """A tracking-pattern URL ending in .png should be tracking, not static-asset."""
        url = "https://px.ads.linkedin.com/collect.png"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "tracking-pixel"
        assert vendor == "linkedin-ads"

    def test_tracking_beats_websocket(self):
        """A wss:// URL that also matches a tracking pattern should be tracking."""
        # Synthetic: websocket to google analytics domain
        url = "wss://www.google-analytics.com/stream"
        cls, vendor = _classify_network_call(url, {})
        assert cls == "analytics"
        assert vendor == "google-analytics"

    # -- Edge cases --

    def test_empty_url(self):
        cls, vendor = _classify_network_call("", {})
        assert cls == "other"
        assert vendor is None

    def test_bare_domain(self):
        cls, vendor = _classify_network_call("https://example.com", {})
        assert cls == "other"
        assert vendor is None


# ---------------------------------------------------------------------------
# _classify_ui_component
# ---------------------------------------------------------------------------

class TestClassifyUiComponent:
    """Tests for _classify_ui_component(comp)."""

    @staticmethod
    def _comp(**kwargs) -> dict:
        """Build a minimal component dict with given overrides."""
        base = {
            "id": None,
            "role": None,
            "tag": None,
            "aria_label": None,
            "text_summary": None,
        }
        base.update(kwargs)
        return base

    # -- Navigation --

    def test_role_navigation(self):
        assert _classify_ui_component(self._comp(role="navigation")) == "navigation"

    def test_role_nav(self):
        assert _classify_ui_component(self._comp(role="nav")) == "navigation"

    def test_tag_nav(self):
        assert _classify_ui_component(self._comp(tag="nav")) == "navigation"

    def test_role_banner(self):
        assert _classify_ui_component(self._comp(role="banner")) == "navigation"

    def test_tag_header(self):
        assert _classify_ui_component(self._comp(tag="header")) == "navigation"

    # -- Footer --

    def test_role_contentinfo(self):
        assert _classify_ui_component(self._comp(role="contentinfo")) == "footer"

    def test_tag_footer(self):
        assert _classify_ui_component(self._comp(tag="footer")) == "footer"

    # -- Sidebar widget --

    def test_role_complementary(self):
        assert _classify_ui_component(self._comp(role="complementary")) == "sidebar-widget"

    def test_tag_aside(self):
        assert _classify_ui_component(self._comp(tag="aside")) == "sidebar-widget"

    # -- Promoted content (by id) --

    def test_id_containing_ad(self):
        assert _classify_ui_component(self._comp(id="ad-banner")) == "promoted-content"

    def test_id_containing_sponsor(self):
        assert _classify_ui_component(self._comp(id="sponsor-card")) == "promoted-content"

    def test_id_containing_promote(self):
        assert _classify_ui_component(self._comp(id="promoted-post")) == "promoted-content"

    # -- Promoted content (by aria_label) --

    def test_label_containing_sponsor(self):
        assert _classify_ui_component(self._comp(aria_label="Sponsored content")) == "promoted-content"

    def test_label_containing_ad(self):
        assert _classify_ui_component(self._comp(aria_label="Ad by Acme Corp")) == "promoted-content"

    def test_label_containing_promot(self):
        """aria_label check uses 'promot' (not 'promote') to catch 'promoted', 'promotion', etc."""
        assert _classify_ui_component(self._comp(aria_label="Promoted post")) == "promoted-content"

    # -- Known false positive: "ad" substring in "download" --

    def test_false_positive_download_contains_ad(self):
        """BUG: 'ad' in 'download' matches because the check is a plain substring match.
        The code does `'ad' in cid` which triggers on 'downl*ad*'. This test documents
        the buggy behaviour so it's visible."""
        result = _classify_ui_component(self._comp(id="download-button"))
        # This SHOULD be "other" but the code will return "promoted-content"
        assert result == "promoted-content", (
            "Expected buggy behaviour: 'download' falsely matches 'ad' substring"
        )

    def test_false_positive_loading(self):
        """BUG: 'ad' in 'loading' matches because 'lo*ad*ing' contains 'ad'."""
        result = _classify_ui_component(self._comp(id="loading-spinner"))
        assert result == "promoted-content", (
            "Expected buggy behaviour: 'loading' falsely matches 'ad' substring"
        )

    # -- Messaging --

    def test_id_containing_messaging(self):
        assert _classify_ui_component(self._comp(id="messaging-overlay")) == "messaging"

    def test_id_containing_message(self):
        """'message-thread' should be messaging, but 'thread' contains 'ad' (thre*ad*).
        BUG: this is another false-positive from the naive 'ad' in cid substring check.
        Use an id that doesn't accidentally contain 'ad'."""
        assert _classify_ui_component(self._comp(id="message-list")) == "messaging"

    def test_id_containing_message_thread_false_positive(self):
        """BUG: 'message-thread' triggers promoted-content because 'thread' contains 'ad'."""
        assert _classify_ui_component(self._comp(id="message-thread")) == "promoted-content"

    def test_id_containing_msg(self):
        assert _classify_ui_component(self._comp(id="msg-list")) == "messaging"

    # -- Notification --

    def test_id_containing_notification(self):
        """Use an id without 'badge' (which contains 'ad') to test the real path."""
        assert _classify_ui_component(self._comp(id="notification-icon")) == "notification"

    def test_id_notification_badge_false_positive(self):
        """BUG: 'notification-badge' triggers promoted-content because 'badge' contains 'ad'."""
        assert _classify_ui_component(self._comp(id="notification-badge")) == "promoted-content"

    def test_id_containing_notif(self):
        assert _classify_ui_component(self._comp(id="notif-dropdown")) == "notification"

    # -- Feed card --

    def test_id_containing_feed(self):
        assert _classify_ui_component(self._comp(id="feed-list")) == "feed-card"

    def test_id_containing_update(self):
        assert _classify_ui_component(self._comp(id="update-item")) == "feed-card"

    # -- Modal --

    def test_id_containing_modal(self):
        assert _classify_ui_component(self._comp(id="modal-dialog")) == "modal"

    def test_id_containing_overlay(self):
        assert _classify_ui_component(self._comp(id="overlay-container")) == "modal"

    # -- Other (fallback) --

    def test_empty_component(self):
        assert _classify_ui_component(self._comp()) == "other"

    def test_unrecognised_id(self):
        assert _classify_ui_component(self._comp(id="some-random-thing")) == "other"

    # -- Precedence --

    def test_role_navigation_beats_id_ad(self):
        """Role-based checks should win over keyword-based id checks."""
        assert _classify_ui_component(
            self._comp(role="navigation", id="ad-panel")
        ) == "navigation"

    def test_role_contentinfo_beats_id_feed(self):
        assert _classify_ui_component(
            self._comp(role="contentinfo", id="feed-footer")
        ) == "footer"

    def test_tag_aside_beats_id_notification(self):
        assert _classify_ui_component(
            self._comp(tag="aside", id="notification-sidebar")
        ) == "sidebar-widget"


# ---------------------------------------------------------------------------
# _url_to_pattern
# ---------------------------------------------------------------------------

class TestUrlToPattern:
    """Tests for _url_to_pattern(url)."""

    def test_numeric_segment_replaced(self):
        result = _url_to_pattern("https://www.linkedin.com/feed/updates/12345")
        assert result == "www.linkedin.com/feed/updates/*"

    def test_hex_segment_8_chars_replaced(self):
        result = _url_to_pattern("https://www.linkedin.com/abc12345")
        assert result == "www.linkedin.com/*"

    def test_hex_segment_long_replaced(self):
        result = _url_to_pattern("https://www.linkedin.com/abc123def456")
        assert result == "www.linkedin.com/*"

    def test_hex_7_chars_not_replaced(self):
        """7-char hex strings should NOT be replaced (threshold is 8+)."""
        result = _url_to_pattern("https://www.linkedin.com/abc1234")
        assert result == "www.linkedin.com/abc1234"

    def test_query_params_stripped(self):
        result = _url_to_pattern("https://www.linkedin.com/feed?page=2&sort=recent")
        assert result == "www.linkedin.com/feed"

    def test_multiple_numeric_segments(self):
        result = _url_to_pattern("https://www.linkedin.com/in/123/posts/456")
        assert result == "www.linkedin.com/in/*/posts/*"

    def test_no_replaceable_segments(self):
        result = _url_to_pattern("https://www.linkedin.com/feed/updates")
        assert result == "www.linkedin.com/feed/updates"

    def test_both_numeric_and_hex_segments(self):
        result = _url_to_pattern(
            "https://www.linkedin.com/voyager/api/feed/12345/comments/abcdef12"
        )
        assert result == "www.linkedin.com/voyager/api/feed/*/comments/*"

    def test_empty_path(self):
        result = _url_to_pattern("https://www.linkedin.com")
        assert result == "www.linkedin.com"

    def test_trailing_slash_preserved(self):
        result = _url_to_pattern("https://www.linkedin.com/feed/")
        assert result == "www.linkedin.com/feed/"


# ---------------------------------------------------------------------------
# _make_id
# ---------------------------------------------------------------------------

class TestMakeId:
    """Tests for _make_id(url_pattern)."""

    def test_normal_path(self):
        assert _make_id("www.linkedin.com/voyager/api/feed/updates") == "updates"

    def test_trailing_wildcard_skipped(self):
        assert _make_id("www.linkedin.com/voyager/api/feed/*") == "feed"

    def test_special_chars_sanitised(self):
        result = _make_id("www.linkedin.com/path/segment_with.dots")
        assert result == "segment-with-dots"

    def test_truncation_at_40_chars(self):
        long_segment = "a" * 60
        result = _make_id(f"www.linkedin.com/path/{long_segment}")
        assert len(result) == 40
        assert result == "a" * 40

    def test_all_wildcards_returns_unknown(self):
        assert _make_id("*/*") == "unknown"

    def test_single_wildcard_returns_unknown(self):
        assert _make_id("*") == "unknown"

    def test_empty_string_returns_unknown(self):
        assert _make_id("") == "unknown"

    def test_query_string_stripped_from_last_segment(self):
        result = _make_id("www.linkedin.com/feed/updates?page=2")
        assert result == "updates"

    def test_domain_only(self):
        """When the pattern is just a domain (no path), domain is the last part."""
        result = _make_id("www.linkedin.com")
        assert result == "www-linkedin-com"

    def test_hyphens_preserved(self):
        result = _make_id("www.linkedin.com/my-network/connections")
        assert result == "connections"

    def test_segment_with_hyphens(self):
        result = _make_id("www.linkedin.com/some-path/well-named-segment")
        assert result == "well-named-segment"
