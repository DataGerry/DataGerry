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
Implementation of CsvObjectImporterConfig
"""
import logging

from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            CsvObjectImporterConfig - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvObjectImporterConfig(ObjectImporterConfig, CSVContent):
    """
    Configuration class for importing CmdbObjects from a CSV file

    Attributes:
        MANUALLY_MAPPING (bool): Indicates if manual mapping is required
    """
    MANUALLY_MAPPING = True

    def __init__(self,
                 type_id: int,
                 start_element: int = 0,
                 max_elements: int = 0,
                 mapping: list | None = None,
                 overwrite_public: bool = True):
        """
        Initializes a CsvObjectImporterConfig

        Args:
            type_id (int): public_id of the CmdbType
            start_element (int, optional): The starting index for processing records. Defaults to 0
            max_elements (int, optional): The maximum number of records to process. Defaults to 0 (no limit)
            mapping (list, optional): A list defining the mapping of CSV columns to object fields
            overwrite_public (bool, optional): Whether to overwrite public data. Defaults to True
        """
        super().__init__(
            type_id = type_id,
            mapping = mapping,
            start_element = start_element,
            max_elements = max_elements,
            overwrite_public = overwrite_public
        )
