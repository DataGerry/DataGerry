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
Implementation of template Table of Contents component
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.docapi.docapi_template.docgen_constants import ComponentKey
from cmdb.framework.docapi.docapi_template.docgen_helpers import format_value
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Config key / base CSS selector for the table of contents
PDFTOC_KEY: str = "pdftoc"
# Prefix of the per-depth config keys (level0 .. level{TOC_LEVEL_COUNT - 1})
LEVEL_PREFIX: str = "level"
# Number of supported TOC depth levels
TOC_LEVEL_COUNT: int = 6

ALLOWED_TOC_STYLES: dict[str, list[str]] = {
    PDFTOC_KEY: ["line-height"],
    **{
        f"{LEVEL_PREFIX}{i}": [
            "font-size",
            "margin-left",
            "margin-top",
            "margin-bottom",
            "padding-bottom",
            "color",
            "font-style",
            "font-weight",
        ]
        for i in range(TOC_LEVEL_COUNT)
    },
}

DEFAULT_TOC_CONFIG: dict[str, dict[str, str]] = {
    "pdftoc": {
        "line-height": "1.4",
    },

    "level0": {
        "font-weight": "bold",
        "font-size": "12pt",
        "margin-top": "10pt",
        "margin-bottom": "4pt",
        "padding-bottom": "2pt",
    },

    "level1": {
        "margin-left": "12pt",
        "font-size": "10pt",
        "margin-top": "3pt",
    },

    "level2": {
        "margin-left": "24pt",
        "font-size": "9pt",
        "font-style": "italic",
        "color": "#444",
    },

    "level3": {
        "margin-left": "36pt",
        "font-size": "9pt",
        "color": "#555",
    },

    "level4": {
        "margin-left": "48pt",
        "font-size": "8pt",
        "color": "#666",
    },

    "level5": {
        "margin-left": "60pt",
        "font-size": "8pt",
        "color": "#777",
        "font-style": "italic",
    }
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                TableOfContents - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TableOfContents:
    """
    Builds the pdftoc CSS and the table-of-contents marker HTML for a generated PDF document

    The TOC config comes from the DocAPI template. When the template carries no config the module
    default styling is used; otherwise the template config fully replaces the defaults. Only the
    CSS properties whitelisted in ALLOWED_TOC_STYLES are emitted per selector.
    """
    def __init__(self, data: dict[str, Any] | None) -> None:
        """
        Args:
            data (dict[str, Any] | None): The template table-of-contents component
                                          (activated flag and per-selector config), or None
        """
        data = data or {}

        self.activated: bool = data.get(ComponentKey.ACTIVATED, False)
        self.config: dict[str, Any] = data.get(ComponentKey.CONFIG, {})


    def get_css(self) -> str:
        """
        Builds the pdftoc CSS from the (whitelisted) TOC config, or the defaults

        Returns:
            str: The CSS blocks joined by blank lines (empty string when the TOC is inactive or no
                 whitelisted property is configured)
        """
        if not self.activated:
            return ""

        source_config: dict[str, Any] = self.config or DEFAULT_TOC_CONFIG

        css_blocks: list[str] = []

        for key, allowed_props in ALLOWED_TOC_STYLES.items():
            props = source_config.get(key, {})

            if not props:
                continue

            # Keep only the whitelisted properties for this selector
            filtered_props = {k: v for k, v in props.items() if k in allowed_props}

            if not filtered_props:
                continue

            selector = PDFTOC_KEY if key == PDFTOC_KEY else f"{PDFTOC_KEY}.{PDFTOC_KEY}{key}"

            css: str = f"{selector} {{\n"
            for prop, val in filtered_props.items():
                css += f"    {prop}: {format_value(prop, val)};\n"
            css += "}"

            css_blocks.append(css)

        return "\n\n".join(css_blocks)


    def get_html(self) -> str:
        """
        Builds the table-of-contents marker HTML

        Returns:
            str: The pdf:toc marker div followed by a page break (empty string when inactive)
        """
        if not self.activated:
            return ""

        return "<div><pdf:toc /></div><pdf:nextpage />"
