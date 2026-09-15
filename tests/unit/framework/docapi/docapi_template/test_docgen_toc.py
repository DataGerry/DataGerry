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
Unit tests for cmdb.framework.docapi.docapi_template.docgen_toc.TableOfContents

Pure tests (no app context, no database). Covers the activated guard, the default-vs-config source,
the per-selector property whitelisting, the pdftoc / level selector mapping, and the HTML marker.
"""
from cmdb.framework.docapi.docapi_template.docgen_toc import (
    TableOfContents,
    PDFTOC_KEY,
    LEVEL_PREFIX,
)
from cmdb.framework.docapi.docapi_template.docgen_constants import ComponentKey
# -------------------------------------------------------------------------------------------------------------------- #

LEVEL0: str = f"{LEVEL_PREFIX}0"
LEVEL_SELECTOR0: str = f"{PDFTOC_KEY}.{PDFTOC_KEY}{LEVEL0}"

LINE_HEIGHT: str = "line-height"
FONT_SIZE: str = "font-size"
FORBIDDEN_PROP: str = "position"

TOC_MARKER: str = "<div><pdf:toc /></div><pdf:nextpage />"


def _toc(activated: bool = True, config: dict = None) -> TableOfContents:
    """Builds a TableOfContents component dict wrapper."""
    return TableOfContents({
        ComponentKey.ACTIVATED: activated,
        ComponentKey.CONFIG: config or {},
    })


class TestInit:
    """Construction reads the activated flag and config, tolerating None."""

    def test_none_data_is_inactive(self) -> None:
        """A None payload yields an inactive TOC with empty config."""
        toc = TableOfContents(None)

        assert toc.activated is False
        assert toc.config == {}

    def test_reads_flag_and_config(self) -> None:
        """The activated flag and config are read from the payload."""
        toc = _toc(activated=True, config={PDFTOC_KEY: {LINE_HEIGHT: "2"}})

        assert toc.activated is True
        assert toc.config == {PDFTOC_KEY: {LINE_HEIGHT: "2"}}


class TestGetCss:
    """get_css builds whitelisted pdftoc CSS, falling back to the module defaults."""

    def test_inactive_returns_empty(self) -> None:
        """An inactive TOC emits no CSS."""
        assert _toc(activated=False).get_css() == ""

    def test_defaults_used_when_no_config(self) -> None:
        """With no config the default styling is emitted for pdftoc and the levels."""
        css = _toc(config={}).get_css()

        assert css.startswith(f"{PDFTOC_KEY} {{")
        assert f"{LEVEL_SELECTOR0} {{" in css
        assert f"{LINE_HEIGHT}: 1.4;" in css

    def test_config_replaces_defaults(self) -> None:
        """A provided config is used verbatim instead of the defaults."""
        css = _toc(config={PDFTOC_KEY: {LINE_HEIGHT: "2"}}).get_css()

        assert f"{LINE_HEIGHT}: 2;" in css
        # Only pdftoc was configured, so no level block is emitted
        assert LEVEL_SELECTOR0 not in css

    def test_selector_without_config_entry_skipped(self) -> None:
        """A selector missing from the config produces no block."""
        css = _toc(config={PDFTOC_KEY: {LINE_HEIGHT: "2"}}).get_css()

        assert f"{PDFTOC_KEY}.{PDFTOC_KEY}" not in css

    def test_non_whitelisted_props_dropped(self) -> None:
        """Only whitelisted properties survive; a fully non-whitelisted selector is skipped."""
        css = _toc(config={LEVEL0: {FONT_SIZE: "9pt", FORBIDDEN_PROP: "absolute"}}).get_css()

        assert f"{FONT_SIZE}: 9pt;" in css
        assert FORBIDDEN_PROP not in css

    def test_all_props_non_whitelisted_yields_empty(self) -> None:
        """When nothing whitelisted is configured the result is empty."""
        assert _toc(config={LEVEL0: {FORBIDDEN_PROP: "absolute"}}).get_css() == ""

    def test_numeric_value_gets_pt_unit(self) -> None:
        """A numeric property value is formatted with a pt unit."""
        css = _toc(config={LEVEL0: {FONT_SIZE: 9}}).get_css()

        assert f"{FONT_SIZE}: 9pt;" in css

    def test_level_selector_shape(self) -> None:
        """A level config produces the nested pdftoc.pdftoc<level> selector."""
        css = _toc(config={LEVEL0: {FONT_SIZE: "9pt"}}).get_css()

        assert css.startswith(f"{LEVEL_SELECTOR0} {{")


class TestGetHtml:
    """get_html emits the TOC marker only when activated."""

    def test_inactive_returns_empty(self) -> None:
        """An inactive TOC emits no HTML."""
        assert _toc(activated=False).get_html() == ""

    def test_active_returns_marker(self) -> None:
        """An active TOC emits the pdf:toc marker followed by a page break."""
        assert _toc(activated=True).get_html() == TOC_MARKER
