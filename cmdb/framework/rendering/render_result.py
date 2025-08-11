# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import logging
from datetime import datetime, timezone
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RenderResult - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class RenderResult:
    """
    Represents the result of rendering a CmdbObject

    Attributes:
        current_render_time (datetime): Timestamp of when the render operation occurred
        object_information (dict): Information related to the rendered object
        type_information (dict): Metadata about the object's type
        fields (list): List of fields associated with the rendered object
        sections (list): List of sections present in the rendered result
        summaries (list): Summary details of the rendered object
        summary_line (str): A single-line summary representation
        externals (list): External references related to the object
        multi_data_sections (list): Sections containing multiple data entries
    """

    def __init__(self) -> None:
        self.current_render_time = datetime.now(timezone.utc)
        self.object_information: dict = {}
        self.type_information: dict = {}
        self.fields: list = []
        self.sections: list = []
        self.summaries: list = []
        self.summary_line: str = ''
        self.externals: list = []
        self.multi_data_sections: list = []
