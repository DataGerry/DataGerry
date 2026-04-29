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

from cmdb.framework.docapi.docapi_template.docgen_helpers import format_value
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ALLOWED_TOC_STYLES: dict[str, list[str]] = {
    "pdftoc": ["line-height"],
    **{
        f"level{i}": [
            "font-size",
            "margin-left",
            "margin-top",
            "margin-bottom",
            "padding-bottom",
            "color",
            "font-style",
            "font-weight",
        ]
        for i in range(6)
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
    TODO: document
    """
    def __init__(self, data: dict[str, Any] | None) -> None:
        """
        TODO: document
        """
        data = data or {}

        self.activated: bool = data.get("activated", False)
        self.config: dict[str, Any] = data.get("config", {})


    def get_css(self) -> str:
        """TODO: document"""
        if not self.activated:
            return ""

        if not self.config:
            source_config = DEFAULT_TOC_CONFIG
        else:
            source_config = self.config

        css_blocks = []

        for key, allowed_props in ALLOWED_TOC_STYLES.items():
            props = source_config.get(key, {})

            if not props:
                continue

            # Filter allowed props
            filtered_props = {
                k: v for k, v in props.items() if k in allowed_props
            }

            if not filtered_props:
                continue

            # selector mapping
            if key == "pdftoc":
                selector = "pdftoc"
            elif key.startswith("level"):
                selector = f"pdftoc.pdftoc{key}"
            else:
                continue

            css: str = f"{selector} {{\n"
            for prop, val in filtered_props.items():
                css += f"    {prop}: {format_value(prop, val)};\n"
            css += "}"

            css_blocks.append(css)

        return "\n\n".join(css_blocks)


    def get_html(self) -> str:
        """TODO: document"""
        if not self.activated:
            return ""

        return "<div><pdf:toc /></div><pdf:nextpage />"
