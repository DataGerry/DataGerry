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

        return ""
