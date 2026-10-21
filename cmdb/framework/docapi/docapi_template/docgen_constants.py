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
All constants for Document Generator
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ComponentKey(BaseStrEnum):
    """Structural keys shared by the docgen component dicts (header, footer, cover page, toc)."""
    ACTIVATED = "activated"
    CONFIG = "config"
    CONTENT = "content"


class PageConfigKey(BaseStrEnum):
    """Structural keys of the page-config dict."""
    MARGIN = "margin"


PAGE_HEIGHT = 842 # A4 maximum page height in pt

PAGE_WIDTH = 595 # A4 maximum page width in pt

MIN_MARGIN = 40 # Minimal margin for an A4 page in pt

MIN_HEADER_HEIGHT = 20 # Minimum header height in pt

MAX_HEADER_HEIGHT = 80 # Maximum header height in pt

MIN_FOOTER_HEIGHT = 20 # Minimum footer height in pt

MAX_FOOTER_HEIGHT = 80 # Maximum footer height in pt

DEFAULT_SPACING = 10 # Default spacing in pt
