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
Implementation of ObjectImporterConfig
"""
from cmdb.framework.importer.configs.base_importer_config import BaseImporterConfig
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectImporterConfig(BaseImporterConfig):
    """
    Configuration class for importing objects

    Extends: BaseImporterConfig
    """

    def __init__(self,
                 type_id: int,
                 mapping: list | None = None,
                 start_element: int = 0,
                 max_elements: int = 0,
                 overwrite_public: bool = True,
                 *args, **kwargs):
        """
        Initializes the ObjectImporterConfig with the given parameters

        Args:
            type_id (int): The identifier for the import type
            mapping (list, optional): The mapping of data for the import. Defaults to None
            start_element (int, optional): The index of the first element to process. Defaults to 0
            max_elements (int, optional): The maximum number of elements to process. Defaults to 0 (no limit)
            overwrite_public (bool, optional): Flag to determine if public data should be overwritten. Defaults to True
            *args: Additional positional arguments passed to the parent constructor
            **kwargs: Additional keyword arguments passed to the parent constructor
        """
        self.type_id: int = type_id
        self.start_element: int = start_element
        self.max_elements: int = max_elements
        self.overwrite_public: bool = overwrite_public
        super().__init__(mapping=mapping, *args, **kwargs)


    def get_type_id(self) -> int:
        """
        Retrieves the type ID for the import configuration

        Returns:
            int: The type ID associated with the import configuration
        """
        return self.type_id
