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

from cmdb.framework.docapi.docapi_template.docgen_constants import PAGE_HEIGHT, PAGE_WIDTH
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               PageHeaderFooter - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class PageHeaderFooter:
    """TODO: document"""
    def __init__(self, header: dict = None, footer: dict = None) -> None:
        """TODO: document"""
        self.header = header or {
            "activated": True,
            "config": {},
            "content": ""
        }
        self.footer = footer or {
            "activated": True,
            "config": {},
            "content": ""
        }
        self.page_config = {}


    def get_css(self) -> str:
        """Build dynamic @page CSS with header, content and footer"""

        margin = self._pt_to_int(self.page_config.get("margin", "40pt"), 40)

        # ---- Header ----
        header_top = self._pt_to_int(
            self.header.get("config", {}).get("top", f"{margin}pt"),
            margin
        )
        header_height = self._pt_to_int(
            self.header.get("config", {}).get("height", "30pt"),
            30
        )

        # ---- Footer ----
        footer_height = self._pt_to_int(
            self.footer.get("config", {}).get("height", "25pt"),
            25
        )
        footer_bottom = self._pt_to_int(
            self.footer.get("config", {}).get("bottom", f"{margin}pt"),
            margin
        )

        # ---- Content calculation ----
        spacing = 10

        content_top = header_top + header_height + spacing
        content_bottom = footer_bottom + footer_height + spacing

        content_height = PAGE_HEIGHT - content_top - content_bottom

        content_left = margin
        content_width = PAGE_WIDTH - (2 * margin)

        # ---- Build CSS ----
        page_css = [
            "@page {",
            f"  size: A4;",
            f"  margin: {margin}pt;",
        ]

        # ---- Header ----
        if self.header.get("activated", True):
            page_css.append(
                f"  @frame header_frame {{ "
                f"-pdf-frame-content: header_content; "
                f"left: 0pt; width: {PAGE_WIDTH}pt; "
                f"top: {header_top}pt; height: {header_height}pt; "
                f"}}"
            )

        # ---- Content ----
        page_css.append(
            f"  @frame content_frame {{ "
            f"left: {content_left}pt; width: {content_width}pt; "
            f"top: {content_top}pt; height: {content_height}pt; "
            f"}}"
        )

        # ---- Footer ----
        if self.footer.get("activated", True):
            footer_top = PAGE_HEIGHT - footer_bottom - footer_height

            page_css.append(
                f"  @frame footer_frame {{ "
                f"-pdf-frame-content: footer_content; "
                f"left: {content_left}pt; width: {content_width}pt; "
                f"top: {footer_top}pt; height: {footer_height}pt; "
                f"}}"
            )

        page_css.append("}")

        return "\n".join(page_css)


    def get_html(self) -> str:
        """TODO: document"""
        html_parts = []

        if self.header.get("activated", True):
            html_parts.append(
                "<div id='header_content'>"
                f"{self.header.get('content', '')}"
                "</div>"
            )

        if self.footer.get("activated", True):
            html_parts.append(
                "<div id='footer_content'>"
                f"{self.footer.get('content', '')}"
                "</div>"
            )

        return "\n".join(html_parts)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _pt_to_int(self, value: str, default: int) -> int:
        """TODO: document"""
        try:
            return int(str(value).replace("pt", "").strip())
        except Exception:
            return default
