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
Module of basic importers
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.importer.configs.base_importer_config import BaseImporterConfig
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 BaseImporter - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseImporter:
    """
    Base class for all importers
    """

    def __init__(self, file: Any, file_type: str, config: BaseImporterConfig | None = None) -> None:
        """
        Init constructor for importer classes
        Args:
            file: File instance, name, content or loaded path to file
            file_type: file type - used with content-type
            config: importer configuration
        """
        self.file: Any = file
        self.file_type: str = file_type
        self.config: BaseImporterConfig | None = config


    def get_file_type(self) -> str:
        """Get the name of the file-type"""
        return self.file_type


    def get_file(self) -> Any:
        """Get the loaded file"""
        return self.file


    def get_config(self) -> BaseImporterConfig | None:
        """Get the configuration object"""
        return self.config


    def has_config(self) -> bool:
        """Check if importer has a config"""
        return bool(self.config)


    def start_import(self) -> ImporterObjectResponse:
        """Starting the import process"""
        raise NotImplementedError("Subclasses must implement the `start_import` method!")
