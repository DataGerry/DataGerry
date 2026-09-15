# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.framework.docapi.docapi_template.docgen_header_footer.PageHeaderFooter

Pure tests (no app context, no database). Covers the @page CSS and content-div HTML building, the
mm->pt page-value resolution, the header/footer height clamping, and the ValueError guards.
"""
import pytest

from cmdb.framework.docapi.docapi_template.docgen_header_footer import (
    PageHeaderFooter,
    PageValue,
    HeaderValue,
    FooterValue,
    HEADER_CONTENT_ID,
    FOOTER_CONTENT_ID,
)
from cmdb.framework.docapi.docapi_template.docgen_constants import (
    ComponentKey,
    PageConfigKey,
    PAGE_WIDTH,
    MIN_HEADER_HEIGHT,
    MAX_HEADER_HEIGHT,
    MIN_FOOTER_HEIGHT,
    MAX_FOOTER_HEIGHT,
    DEFAULT_SPACING,
)
# -------------------------------------------------------------------------------------------------------------------- #

HEIGHT: str = "height"
CONTENT_TEXT: str = "Company Ltd."
MM_FACTOR: float = 2.83465
MARGIN_MM: int = 10


def _component(activated: bool = False, config: dict = None, content: str = "") -> dict:
    """Builds a header/footer component dict."""
    return {
        ComponentKey.ACTIVATED: activated,
        ComponentKey.CONFIG: config or {},
        ComponentKey.CONTENT: content,
    }


def _page_config(margin: dict = None) -> dict:
    """Builds a page-config dict with an optional margin mapping."""
    return {PageConfigKey.MARGIN: margin or {}}


class TestInit:
    """Construction falls back to inactive defaults for missing components."""

    def test_defaults_are_inactive(self) -> None:
        """With no arguments both components default to inactive with empty config/content."""
        page_hf = PageHeaderFooter()

        assert page_hf.header[ComponentKey.ACTIVATED] is False
        assert page_hf.footer[ComponentKey.ACTIVATED] is False
        assert page_hf.page_config == {}

    def test_provided_values_kept(self) -> None:
        """Provided components and page config are stored unchanged."""
        header = _component(activated=True, content=CONTENT_TEXT)
        page_hf = PageHeaderFooter(header=header, page_config=_page_config())

        assert page_hf.header is header


class TestGetPageValue:
    """get_page_value resolves margins (mm->pt) and the derived content width."""

    def test_margin_converted_from_mm(self) -> None:
        """A margin in mm is converted to pt (rounded down)."""
        page_hf = PageHeaderFooter(page_config=_page_config({PageValue.MARGIN_TOP: MARGIN_MM}))

        assert page_hf.get_page_value(PageValue.MARGIN_TOP) == int(MARGIN_MM * MM_FACTOR)

    def test_missing_margin_is_zero(self) -> None:
        """A margin absent from the config resolves to 0."""
        assert PageHeaderFooter(page_config=_page_config()).get_page_value(PageValue.MARGIN_LEFT) == 0

    def test_all_margin_sides(self) -> None:
        """Every margin side is resolved from its own config key."""
        margins = {
            PageValue.MARGIN_TOP: 1,
            PageValue.MARGIN_BOTTOM: 2,
            PageValue.MARGIN_LEFT: 3,
            PageValue.MARGIN_RIGHT: 4,
        }
        page_hf = PageHeaderFooter(page_config=_page_config(margins))

        assert page_hf.get_page_value(PageValue.MARGIN_BOTTOM) == int(2 * MM_FACTOR)
        assert page_hf.get_page_value(PageValue.MARGIN_RIGHT) == int(4 * MM_FACTOR)

    def test_max_width_subtracts_horizontal_margins(self) -> None:
        """Content width is the page width minus the left and right margins."""
        margins = {PageValue.MARGIN_LEFT: MARGIN_MM, PageValue.MARGIN_RIGHT: MARGIN_MM}
        page_hf = PageHeaderFooter(page_config=_page_config(margins))

        expected = PAGE_WIDTH - int(MARGIN_MM * MM_FACTOR) - int(MARGIN_MM * MM_FACTOR)
        assert page_hf.get_page_value(PageValue.MAX_WIDTH) == expected

    def test_unknown_page_value_raises(self) -> None:
        """An unrecognised page value raises ValueError."""
        with pytest.raises(ValueError):
            PageHeaderFooter().get_page_value("bogus")


class TestGetHeaderValue:
    """get_header_value clamps the configured height and returns 0 when inactive."""

    def test_inactive_header_is_zero(self) -> None:
        """An inactive header resolves every value to 0."""
        assert PageHeaderFooter(header=_component(activated=False)).get_header_value(HeaderValue.HEIGHT) == 0

    def test_default_height_when_unconfigured(self) -> None:
        """An active header with no configured height falls back to the minimum."""
        page_hf = PageHeaderFooter(header=_component(activated=True))

        assert page_hf.get_header_value(HeaderValue.HEIGHT) == MIN_HEADER_HEIGHT

    def test_height_clamped_below_min(self) -> None:
        """A configured height below the minimum is raised to the minimum."""
        page_hf = PageHeaderFooter(header=_component(activated=True, config={HEIGHT: 1}))

        assert page_hf.get_header_value(HeaderValue.HEIGHT) == MIN_HEADER_HEIGHT

    def test_height_clamped_above_max(self) -> None:
        """A configured height above the maximum is capped at the maximum."""
        page_hf = PageHeaderFooter(header=_component(activated=True, config={HEIGHT: 9999}))

        assert page_hf.get_header_value(HeaderValue.HEIGHT) == MAX_HEADER_HEIGHT

    def test_height_in_range_kept(self) -> None:
        """A configured height inside the allowed range is returned unchanged."""
        in_range = MIN_HEADER_HEIGHT + 5
        page_hf = PageHeaderFooter(header=_component(activated=True, config={HEIGHT: in_range}))

        assert page_hf.get_header_value(HeaderValue.HEIGHT) == in_range

    def test_unknown_header_value_raises(self) -> None:
        """An unrecognised header value raises ValueError (once the header is active)."""
        page_hf = PageHeaderFooter(header=_component(activated=True))

        with pytest.raises(ValueError):
            page_hf.get_header_value("bogus")


class TestGetFooterValue:
    """get_footer_value clamps the configured height and reads the footer's own config."""

    def test_inactive_footer_is_zero(self) -> None:
        """An inactive footer resolves every value to 0."""
        assert PageHeaderFooter(footer=_component(activated=False)).get_footer_value(FooterValue.HEIGHT) == 0

    def test_reads_footer_config_not_header(self) -> None:
        """The footer height comes from the footer's own config, independent of the header (regression)."""
        header = _component(activated=True, config={HEIGHT: MAX_FOOTER_HEIGHT})
        footer = _component(activated=True, config={HEIGHT: MIN_FOOTER_HEIGHT + 7})
        page_hf = PageHeaderFooter(header=header, footer=footer)

        assert page_hf.get_footer_value(FooterValue.HEIGHT) == MIN_FOOTER_HEIGHT + 7

    def test_default_height_when_unconfigured(self) -> None:
        """An active footer with no configured height falls back to the minimum."""
        page_hf = PageHeaderFooter(footer=_component(activated=True))

        assert page_hf.get_footer_value(FooterValue.HEIGHT) == MIN_FOOTER_HEIGHT

    def test_height_clamped_above_max(self) -> None:
        """A configured height above the maximum is capped at the maximum."""
        page_hf = PageHeaderFooter(footer=_component(activated=True, config={HEIGHT: 9999}))

        assert page_hf.get_footer_value(FooterValue.HEIGHT) == MAX_FOOTER_HEIGHT

    def test_unknown_footer_value_raises(self) -> None:
        """An unrecognised footer value raises ValueError (once the footer is active)."""
        page_hf = PageHeaderFooter(footer=_component(activated=True))

        with pytest.raises(ValueError):
            page_hf.get_footer_value("bogus")


class TestGetCss:
    """get_css builds the @page block and an @frame per activated component."""

    def test_base_page_without_components(self) -> None:
        """With no active components the block has margins but no frames."""
        css = PageHeaderFooter().get_css()

        assert css.startswith("@page {")
        assert css.rstrip().endswith("}")
        assert "size: A4;" in css
        assert "@frame" not in css

    def test_inactive_margins_still_reserve_spacing(self) -> None:
        """Even with zero margins the reserved spacing is added to top and bottom."""
        css = PageHeaderFooter().get_css()

        assert f"margin-top: {DEFAULT_SPACING}pt;" in css
        assert f"margin-bottom: {DEFAULT_SPACING}pt;" in css

    def test_active_header_adds_header_frame(self) -> None:
        """An active header adds a header frame bound to the header content div."""
        css = PageHeaderFooter(header=_component(activated=True)).get_css()

        assert "@frame header_frame" in css
        assert f"-pdf-frame-content: {HEADER_CONTENT_ID};" in css

    def test_active_footer_adds_footer_frame(self) -> None:
        """An active footer adds a footer frame bound to the footer content div."""
        css = PageHeaderFooter(footer=_component(activated=True)).get_css()

        assert "@frame footer_frame" in css
        assert f"-pdf-frame-content: {FOOTER_CONTENT_ID};" in css

    def test_active_header_reserves_its_height(self) -> None:
        """An active header enlarges the top margin by its height plus the spacing."""
        css = PageHeaderFooter(header=_component(activated=True)).get_css()

        expected_top = MIN_HEADER_HEIGHT + DEFAULT_SPACING
        assert f"margin-top: {expected_top}pt;" in css


class TestGetHtml:
    """get_html emits content divs only for activated components."""

    def test_empty_when_inactive(self) -> None:
        """Neither component activated yields an empty string."""
        assert PageHeaderFooter().get_html() == ""

    def test_header_div(self) -> None:
        """An active header emits its content div."""
        html = PageHeaderFooter(header=_component(activated=True, content=CONTENT_TEXT)).get_html()

        assert html == f"<div id='{HEADER_CONTENT_ID}'>{CONTENT_TEXT}</div>"

    def test_both_divs_joined(self) -> None:
        """Both components emit their divs, joined by a newline in header-then-footer order."""
        header = _component(activated=True, content="H")
        footer = _component(activated=True, content="F")
        html = PageHeaderFooter(header=header, footer=footer).get_html()

        assert html == (
            f"<div id='{HEADER_CONTENT_ID}'>H</div>\n"
            f"<div id='{FOOTER_CONTENT_ID}'>F</div>"
        )
