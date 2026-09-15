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

from cmdb.framework.docapi.docapi_template.docgen_constants import ComponentKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CoverPage - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class CoverPage:
    """
    Builds the cover-page HTML for a generated PDF document

    The cover-page content comes from the DocAPI template. Styling is expected to be inline in that
    content, so this component only wraps the content and appends a page break.
    """
    def __init__(self, data: dict[str, Any] | None) -> None:
        """
        Args:
            data (dict[str, Any] | None): The template cover-page component (activated flag and
                                          content HTML), or None
        """
        data = data or {}

        self.activated: bool = data.get(ComponentKey.ACTIVATED, False)
        self.content: str = data.get(ComponentKey.CONTENT, "")


    def get_html(self) -> str:
        """
        Builds the cover-page content HTML followed by a page break

        Returns:
            str: The wrapped content and page break (empty string when inactive or without content)
        """
        if not self.activated or not self.content:
            return ""

        return f"""
        <div class="cover-page">
            {self.content}
        </div>
        <pdf:nextpage />
        """


    def get_css(self) -> str:
        """
        Returns the cover-page CSS

        The cover page carries no generated styling (styling is inline in the content), so this is
        always an empty string. Kept for interface parity with the other document components.

        Returns:
            str: An empty string
        """
        return ""
