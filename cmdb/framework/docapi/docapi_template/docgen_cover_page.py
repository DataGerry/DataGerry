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
Implementation of template cover page component
"""
from logging import Logger, getLogger
from typing import Any

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ALLOWED_COVER_STYLES: dict[str, list[str]] = {
    "container": [
        "text-align",
        "margin-top",
        "margin-bottom",
        "margin-left",
        "margin-right",
    ],
    "h1": [
        "font-size",
        "font-weight",
        "color",
        "margin-bottom",
        "text-align",
    ],
    "h2": [
        "font-size",
        "font-weight",
        "color",
        "margin-bottom",
        "text-align",
    ],
    "h3": [
        "font-size",
        "font-weight",
        "color",
        "margin-bottom",
        "text-align",
    ],
    "p": [
        "font-size",
        "color",
        "margin-top",
        "margin-bottom",
        "text-align",
    ],
    "img": [
        "width",
        "height",
        "margin-top",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "text-align",
    ]
}

DEFAULT_COVER_CONFIG: dict[str, dict[str, str]] = {
    "container": {
        "text-align": "center",
        "margin-top": "250pt",
    },
    "h1": {
        "font-size": "24pt",
        "margin-bottom": "20pt",
        "font-weight": "bold",
    },
    "p": {
        "font-size": "12pt",
        "margin-top": "5pt",
        "margin-bottom": "5pt",
    },
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CoverPage - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CoverPage:
    """TODO: document"""
    def __init__(self, data: dict[str, Any] | None) -> None:
        data = data or {}

        self.activated: bool = data.get("activated", False)
        self.content: str = data.get("content", "")
        self.config: dict[str, Any] = data.get("config") or {}


    def get_html(self) -> str:
        """TODO: document"""
        if not self.activated or not self.content:
            return ""

        return f"""
        <div class="cover-page">
            {self.content}
        </div>
        <pdf:nextpage />
        """


    def get_css(self) -> str:
        """TODO: document"""
        if not self.activated:
            return ""

        config: dict[str, Any] = self.config or DEFAULT_COVER_CONFIG
        css_blocks = []

        mapping: dict[str, str] = {
            "container": ".cover-page",
            "h1": ".cover-page h1",
            "h2": ".cover-page h2",
            "h3": ".cover-page h3",
            "p": ".cover-page p",
            "img": ".cover-page img",
        }

        for key, allowed_props in ALLOWED_COVER_STYLES.items():
            props = config.get(key, {})
            filtered = {k: v for k, v in props.items() if k in allowed_props}
            if not filtered:
                continue

            selector: str = mapping[key]
            css = f"{selector} {{\n"
            for prop, val in filtered.items():
                css += f"    {prop}: {val};\n"
            css += "}"
            css_blocks.append(css)

        return "\n\n".join(css_blocks)
