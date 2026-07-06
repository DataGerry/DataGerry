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
Implementation of RenderResult
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RenderResult - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class RenderResult:
    """
    Represents the result of rendering a CmdbObject

    Attributes:
        current_render_time (datetime): Timestamp when the render operation occurred
        object_information (dict[str, Any]): Information related to the rendered CmdbObject
        type_information (dict[str, Any]): Metadata about the object's type
        fields (list): List of fields associated with the rendered object
        sections (list): List of sections present in the rendered result
        summaries (list): Summary details of the rendered object
        summary_line (str): A single-line summary representation
        externals (list): External references related to the object
        multi_data_sections (list): Sections containing multiple data entries
    """

    def __init__(self) -> None:
        self.current_render_time: datetime = datetime.now(timezone.utc)
        self.object_information: dict[str, Any] = {}
        self.type_information: dict[str, Any] = {}
        self.fields: list = []
        self.sections: list = []
        self.summaries: list = []
        self.summary_line: str = ''
        self.externals: list = []
        self.multi_data_sections: list = []


    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}(\n"
            f"  current_render_time={self.current_render_time.isoformat()},\n"
            f"  object_information={self.object_information},\n"
            f"  type_information={self.type_information},\n"
            f"  fields={len(self.fields)} items,\n"
            f"  sections={len(self.sections)} items,\n"
            f"  summaries={len(self.summaries)} items,\n"
            f"  summary_line='{self.summary_line}',\n"
            f"  externals={len(self.externals)} items,\n"
            f"  multi_data_sections={len(self.multi_data_sections)} items\n"
            f")"
        )