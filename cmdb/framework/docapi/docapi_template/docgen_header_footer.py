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
<<<<<<< HEAD
from enum import Enum
=======
>>>>>>> origin/version-3.2
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.docapi.docapi_template.docgen_constants import (
    PAGE_HEIGHT,
    PAGE_WIDTH,
    MIN_HEADER_HEIGHT,
    MAX_HEADER_HEIGHT,
    MIN_FOOTER_HEIGHT,
    MAX_FOOTER_HEIGHT,
    DEFAULT_SPACING,
)
from cmdb.framework.docapi.docapi_template.docgen_helpers import mm_to_pt
<<<<<<< HEAD
=======
from cmdb.utils import BaseStrEnum
>>>>>>> origin/version-3.2
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

<<<<<<< HEAD
class PageValue(str, Enum):
=======
class PageValue(BaseStrEnum):
>>>>>>> origin/version-3.2
    """TODO: document"""
    MARGIN_TOP = "margin-top"
    MARGIN_BOTTOM = "margin-bottom"
    MARGIN_LEFT = "margin-left"
    MARGIN_RIGHT ="margin-right"
    MAX_WIDTH = "width"

<<<<<<< HEAD
class HeaderValue(str, Enum):
    """TODO: document"""
    HEIGHT = "height"

class FooterValue(str, Enum):
=======
class HeaderValue(BaseStrEnum):
    """TODO: document"""
    HEIGHT = "height"

class FooterValue(BaseStrEnum):
>>>>>>> origin/version-3.2
    """TODO: document"""
    HEIGHT = "height"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               PageHeaderFooter - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class PageHeaderFooter:
    """TODO: document"""
    def __init__(
        self,
        header: dict[str, Any] = None,
        footer: dict[str, Any] = None,
        page_config: dict[str, Any] = None
    ) -> None:
        """TODO: document"""
        self.header: dict[str, Any] = header or {
            "activated": False,
            "config": {},
            "content": ""
        }

        self.footer: dict[str, Any] = footer or {
            "activated": False,
            "config": {},
            "content": ""
        }

        self.page_config: dict[str, Any] = page_config or {}


    def get_css(self) -> str:
        """
        Build dynamic @page CSS with header, content and footer
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

        # ---- Header ----
        if self.header.get("activated", False):
            header_top = page_margin_top - header_height - DEFAULT_SPACING
            page_css.append(
                f"  @frame header_frame {{ "
                f"    -pdf-frame-content: header_content; "
                # f"    -pdf-frame-border: 1;"
                f"    left: {page_margin_left}pt; width: {page_content_width}pt; "
                f"    top: {header_top}pt; height: {header_height}pt; "
                f"}}"
            )

        # ---- Footer ----
        if self.footer.get("activated", False):
            footer_top: int = PAGE_HEIGHT - page_margin_bottom + DEFAULT_SPACING
            page_css.append(
                f"  @frame footer_frame {{ "
                f"    -pdf-frame-content: footer_content; "
                # f"    -pdf-frame-border: 1;"
                f"    left: {page_margin_left}pt; width: {page_content_width}pt; "
                f"    top: {footer_top}pt; height: {footer_height}pt; "
                f"}}"
            )

        page_css.append("}")
        result: str = "\n".join(page_css)

        return result


    def get_html(self) -> str:
        """TODO: document"""
        html_parts = []

        if self.header.get("activated", False):
            html_parts.append(
                "<div id='header_content'>"
                f"{self.header.get('content', '')}"
                "</div>"
            )

        if self.footer.get("activated", False):
            html_parts.append(
                "<div id='footer_content'>"
                f"{self.footer.get('content', '')}"
                "</div>"
            )

        # return "\n".join(html_parts)
        result = "\n".join(html_parts)
        # LOGGER.debug(f"[get_html] html: {result}")
        return result

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_page_value(self, page_value: PageValue) -> int:
        """TODO: document"""
        if page_value == PageValue.MARGIN_TOP:
            return mm_to_pt(self.page_config.get('margin', {}).get(PageValue.MARGIN_TOP), 0)

        if page_value == PageValue.MARGIN_BOTTOM:
            return mm_to_pt(self.page_config.get('margin', {}).get(PageValue.MARGIN_BOTTOM), 0)

        if page_value == PageValue.MARGIN_LEFT:
            return mm_to_pt(self.page_config.get('margin', {}).get(PageValue.MARGIN_LEFT), 0)

        if page_value == PageValue.MARGIN_RIGHT:
            return mm_to_pt(self.page_config.get('margin', {}).get(PageValue.MARGIN_RIGHT), 0)

        if page_value == PageValue.MAX_WIDTH:
            page_left = self.get_page_value(PageValue.MARGIN_LEFT)
            page_right = self.get_page_value(PageValue.MARGIN_RIGHT)
            return PAGE_WIDTH - page_left - page_right

        raise ValueError("Unknown PageValue")


    def get_header_value(self, header_value: HeaderValue) -> int:
        """TODO: document"""
        # If header is not activeated all values are 0
        if not self.header.get('activated', False):
            return 0

        if header_value == HeaderValue.HEIGHT:
            header_height: int = self.header.get("config", {}).get(HeaderValue.HEIGHT, MIN_HEADER_HEIGHT)

            # Enforce height is in the allowed scope
            header_height = min(max(header_height, MIN_HEADER_HEIGHT), MAX_HEADER_HEIGHT)

            return header_height

        raise ValueError("Unknown HeaderValue")


    def get_footer_value(self, footer_value: FooterValue) -> int:
        """TODO: document"""
        # If footer is not activeated all values are 0
        if not self.footer.get('activated', False):
            return 0

        if footer_value == FooterValue.HEIGHT:
            footer_height = self.header.get("config", {}).get(FooterValue.HEIGHT, MIN_FOOTER_HEIGHT)

            # Enforce height is in the allowed scope
            footer_height = min(max(footer_height, MIN_FOOTER_HEIGHT), MAX_FOOTER_HEIGHT)

            return footer_height

        raise ValueError("Unknown FooterValue")
