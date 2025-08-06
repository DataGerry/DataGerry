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
Implementation of BaseImporterConfig
"""
from cmdb.framework.importer.mapper.mapping import Mapping
# -------------------------------------------------------------------------------------------------------------------- #

class BaseImporterConfig:
    """
    Base class for import configurations
    """
    DEFAULT_MAPPING: Mapping = Mapping()
    MANUALLY_MAPPING: bool = True

    def __init__(self, mapping: list = None):
        """
        Initializes the BaseImporterConfig

        Args:
            mapping (list | None): Optional list to generate a mapping
        """
        self.mapping: Mapping = Mapping.generate_mapping_from_list(mapping) if mapping else self.DEFAULT_MAPPING


    def get_mapping(self) -> Mapping:
        """
        Returns the current mapping configuration

        Returns:
            Mapping: The mapping instance associated with this configuration
        """
        return self.mapping
