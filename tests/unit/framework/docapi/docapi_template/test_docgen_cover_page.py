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
Unit tests for cmdb.framework.docapi.docapi_template.docgen_cover_page.CoverPage

Pure tests (no app context, no database). Covers the activated/content guards on the HTML output
and the always-empty CSS.
"""
from cmdb.framework.docapi.docapi_template.docgen_cover_page import CoverPage
from cmdb.framework.docapi.docapi_template.docgen_constants import ComponentKey
# -------------------------------------------------------------------------------------------------------------------- #

CONTENT_TEXT: str = "Annual Report 2026"


def _cover(activated: bool = True, content: str = CONTENT_TEXT) -> CoverPage:
    """Builds a CoverPage from a component payload."""
    return CoverPage({
        ComponentKey.ACTIVATED: activated,
        ComponentKey.CONTENT: content,
    })


class TestInit:
    """Construction reads the activated flag and content, tolerating None."""

    def test_none_data_is_inactive(self) -> None:
        """A None payload yields an inactive cover page with empty content."""
        cover = CoverPage(None)

        assert cover.activated is False
        assert cover.content == ""

    def test_reads_flag_and_content(self) -> None:
        """The activated flag and content are read from the payload."""
        cover = _cover(activated=True, content=CONTENT_TEXT)

        assert cover.activated is True
        assert cover.content == CONTENT_TEXT


class TestGetHtml:
    """get_html wraps the content only when activated and non-empty."""

    def test_inactive_returns_empty(self) -> None:
        """An inactive cover page emits no HTML."""
        assert _cover(activated=False).get_html() == ""

    def test_active_without_content_returns_empty(self) -> None:
        """An active cover page with empty content emits no HTML."""
        assert _cover(activated=True, content="").get_html() == ""

    def test_active_with_content_wraps_and_breaks(self) -> None:
        """An active cover page wraps its content and appends a page break."""
        html = _cover(activated=True, content=CONTENT_TEXT).get_html()

        assert '<div class="cover-page">' in html
        assert CONTENT_TEXT in html
        assert "<pdf:nextpage />" in html


class TestGetCss:
    """get_css always yields an empty string."""

    def test_active_is_empty(self) -> None:
        """An active cover page produces no CSS."""
        assert _cover(activated=True).get_css() == ""

    def test_inactive_is_empty(self) -> None:
        """An inactive cover page produces no CSS."""
        assert _cover(activated=False).get_css() == ""
