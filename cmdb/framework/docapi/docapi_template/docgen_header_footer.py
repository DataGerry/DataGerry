# DataGerry - OpenSource Enterprise CMDB
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
Implementation of template header and footer component
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.docapi.docapi_template.docgen_constants import (
    ComponentKey,
    PageConfigKey,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    MIN_HEADER_HEIGHT,
    MAX_HEADER_HEIGHT,
    MIN_FOOTER_HEIGHT,
    MAX_FOOTER_HEIGHT,
    DEFAULT_SPACING,
)
from cmdb.framework.docapi.docapi_template.docgen_helpers import mm_to_pt
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# xhtml2pdf frame names and the content-div ids they bind to (get_css and get_html must agree)
HEADER_FRAME_NAME: str = "header_frame"
HEADER_CONTENT_ID: str = "header_content"
FOOTER_FRAME_NAME: str = "footer_frame"
FOOTER_CONTENT_ID: str = "footer_content"


class PageValue(BaseStrEnum):
    """Selectors for a resolved page-margin / content-width value (values match page-config keys)."""
    MARGIN_TOP = "margin-top"
    MARGIN_BOTTOM = "margin-bottom"
    MARGIN_LEFT = "margin-left"
    MARGIN_RIGHT = "margin-right"
    MAX_WIDTH = "width"


class HeaderValue(BaseStrEnum):
    """Selectors for a resolved header dimension (values match header-config keys)."""
    HEIGHT = "height"


class FooterValue(BaseStrEnum):
    """Selectors for a resolved footer dimension (values match footer-config keys)."""
    HEIGHT = "height"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               PageHeaderFooter - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class PageHeaderFooter:
    """
    Builds the @page CSS and the header/footer HTML for a generated PDF document

    The header, footer and page-config dicts come from the DocAPI template. This class resolves the
    effective page margins (base margin plus the space reserved for an activated header/footer) into
    xhtml2pdf @page rules, and emits the matching content divs.
    """
    def __init__(
        self,
        header: dict[str, Any] = None,
        footer: dict[str, Any] = None,
        page_config: dict[str, Any] = None
    ) -> None:
        """
        Args:
            header (dict[str, Any]): The template header component (activated / config / content)
            footer (dict[str, Any]): The template footer component (activated / config / content)
            page_config (dict[str, Any]): The template page config (margins etc.)
        """
        self.header: dict[str, Any] = header or {
            ComponentKey.ACTIVATED: False,
            ComponentKey.CONFIG: {},
            ComponentKey.CONTENT: ""
        }

        self.footer: dict[str, Any] = footer or {
            ComponentKey.ACTIVATED: False,
            ComponentKey.CONFIG: {},
            ComponentKey.CONTENT: ""
        }

        self.page_config: dict[str, Any] = page_config or {}


    def get_css(self) -> str:
        """
        Builds the dynamic @page CSS, reserving margin space and frames for header and footer

        Returns:
            str: The @page CSS block, including an @frame for each activated component
        """
        header_height: int = self.get_header_value(HeaderValue.HEIGHT)
        footer_height: int = self.get_footer_value(FooterValue.HEIGHT)

        page_margin_top: int = self.get_page_value(PageValue.MARGIN_TOP) + header_height + DEFAULT_SPACING
        page_margin_bottom: int = self.get_page_value(PageValue.MARGIN_BOTTOM) + footer_height + DEFAULT_SPACING
        page_margin_left: int = self.get_page_value(PageValue.MARGIN_LEFT)
        page_content_width: int = self.get_page_value(PageValue.MAX_WIDTH)

        page_css: list[str] = [
            "@page {",
            "  size: A4;",
            f"  margin-top: {page_margin_top}pt;",
            f"  margin-bottom: {page_margin_bottom}pt;",
            f"  margin-left: {page_margin_left}pt;",
            f"  margin-right: {self.get_page_value(PageValue.MARGIN_RIGHT)}pt;",
        ]

        if self.header.get(ComponentKey.ACTIVATED, False):
            header_top: int = page_margin_top - header_height - DEFAULT_SPACING
            page_css.append(self._build_frame(
                HEADER_FRAME_NAME, HEADER_CONTENT_ID,
                page_margin_left, page_content_width, header_top, header_height,
            ))

        if self.footer.get(ComponentKey.ACTIVATED, False):
            footer_top: int = PAGE_HEIGHT - page_margin_bottom + DEFAULT_SPACING
            page_css.append(self._build_frame(
                FOOTER_FRAME_NAME, FOOTER_CONTENT_ID,
                page_margin_left, page_content_width, footer_top, footer_height,
            ))

        page_css.append("}")

        return "\n".join(page_css)


    def get_html(self) -> str:
        """
        Builds the header/footer content divs for the activated components

        Returns:
            str: The concatenated content divs (empty string when neither component is activated)
        """
        html_parts: list[str] = []

        if self.header.get(ComponentKey.ACTIVATED, False):
            html_parts.append(
                f"<div id='{HEADER_CONTENT_ID}'>"
                f"{self.header.get(ComponentKey.CONTENT, '')}"
                "</div>"
            )

        if self.footer.get(ComponentKey.ACTIVATED, False):
            html_parts.append(
                f"<div id='{FOOTER_CONTENT_ID}'>"
                f"{self.footer.get(ComponentKey.CONTENT, '')}"
                "</div>"
            )

        return "\n".join(html_parts)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def _build_frame(name: str, content_id: str, left: int, width: int, top: int, height: int) -> str:
        """
        Builds a single xhtml2pdf @frame rule binding a named frame to its content div

        Args:
            name (str): The frame name
            content_id (str): The id of the content div the frame renders
            left (int): The frame left offset in pt
            width (int): The frame width in pt
            top (int): The frame top offset in pt
            height (int): The frame height in pt

        Returns:
            str: The @frame CSS rule
        """
        return (
            f"  @frame {name} {{ "
            f"    -pdf-frame-content: {content_id}; "
            f"    left: {left}pt; width: {width}pt; "
            f"    top: {top}pt; height: {height}pt; "
            f"}}"
        )


    def get_page_value(self, page_value: PageValue) -> int:
        """
        Resolves a page margin (converted from mm) or the usable content width

        Args:
            page_value (PageValue): The value to resolve

        Returns:
            int: The resolved value in pt

        Raises:
            ValueError: If `page_value` is not a known PageValue
        """
        margin: dict[str, Any] = self.page_config.get(PageConfigKey.MARGIN, {})

        if page_value == PageValue.MARGIN_TOP:
            return mm_to_pt(margin.get(PageValue.MARGIN_TOP), 0)

        if page_value == PageValue.MARGIN_BOTTOM:
            return mm_to_pt(margin.get(PageValue.MARGIN_BOTTOM), 0)

        if page_value == PageValue.MARGIN_LEFT:
            return mm_to_pt(margin.get(PageValue.MARGIN_LEFT), 0)

        if page_value == PageValue.MARGIN_RIGHT:
            return mm_to_pt(margin.get(PageValue.MARGIN_RIGHT), 0)

        if page_value == PageValue.MAX_WIDTH:
            page_left: int = self.get_page_value(PageValue.MARGIN_LEFT)
            page_right: int = self.get_page_value(PageValue.MARGIN_RIGHT)
            return PAGE_WIDTH - page_left - page_right

        raise ValueError("Unknown PageValue")


    def get_header_value(self, header_value: HeaderValue) -> int:
        """
        Resolves a header dimension, clamped to the allowed range (0 when the header is inactive)

        Args:
            header_value (HeaderValue): The value to resolve

        Returns:
            int: The resolved value in pt

        Raises:
            ValueError: If `header_value` is not a known HeaderValue
        """
        # If the header is not activated all values are 0
        if not self.header.get(ComponentKey.ACTIVATED, False):
            return 0

        if header_value == HeaderValue.HEIGHT:
            header_height: int = self.header.get(ComponentKey.CONFIG, {}).get(HeaderValue.HEIGHT, MIN_HEADER_HEIGHT)

            # Enforce the height is within the allowed range
            return min(max(header_height, MIN_HEADER_HEIGHT), MAX_HEADER_HEIGHT)

        raise ValueError("Unknown HeaderValue")


    def get_footer_value(self, footer_value: FooterValue) -> int:
        """
        Resolves a footer dimension, clamped to the allowed range (0 when the footer is inactive)

        Args:
            footer_value (FooterValue): The value to resolve

        Returns:
            int: The resolved value in pt

        Raises:
            ValueError: If `footer_value` is not a known FooterValue
        """
        # If the footer is not activated all values are 0
        if not self.footer.get(ComponentKey.ACTIVATED, False):
            return 0

        if footer_value == FooterValue.HEIGHT:
            footer_height: int = self.footer.get(ComponentKey.CONFIG, {}).get(FooterValue.HEIGHT, MIN_FOOTER_HEIGHT)

            # Enforce the height is within the allowed range
            return min(max(footer_height, MIN_FOOTER_HEIGHT), MAX_FOOTER_HEIGHT)

        raise ValueError("Unknown FooterValue")
