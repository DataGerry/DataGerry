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
Implementation of ExcelObjectImporter
"""
import logging
from datetime import datetime, timezone

from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.content_types import XLSXContent
from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.configs.excel_object_importer_config import ExcelObjectImporterConfig
from cmdb.framework.importer.mapper.map_entry import MapEntry
from cmdb.framework.importer.responses.excel_object_parser_response import ExcelObjectParserResponse
from cmdb.framework.importer.helper.improve_object import ImproveObject
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse

from cmdb.errors.importer import ImportRuntimeError, ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ExcelObjectImporter - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class ExcelObjectImporter(ObjectImporter, XLSXContent):
    """
    ExcelObjectImporter handles the import of objects from Excel (.xlsx) files.

    It reads the Excel content based on a given configuration and mapping,
    generates objects compatible with the system's structure,
    and prepares them for insertion.

    Extends: ObjectImporter, XLSXContent
    """
    #pylint: disable=R0917
    def __init__(self,
        file = None,
        config: ExcelObjectImporterConfig = None,
        parser: JsonObjectParser | None = None,
        objects_manager: ObjectsManager | None = None,
        request_user: CmdbUser | None = None
    ) -> None:
        """
        Initialize the ExcelObjectImporter

        Args:
            file: The Excel file to import
            config (ExcelObjectImporterConfig): Configuration defining mappings and rules for import
            parser (JsonObjectParser): Parser instance to handle object parsing logic
            objects_manager (ObjectsManager): Manager instance to retrieve and interact with existing objects
            request_user (CmdbUser): The user initiating the import
        """
        super().__init__(
            file = file,
            file_type = self.FILE_TYPE,
            config = config,
            parser = parser,
            objects_manager = objects_manager,
            request_user = request_user
        )


    def generate_object(self, entry: dict, *args, **kwargs) -> dict:
        """
        Generate an object dictionary from an Excel row entry based on the import configuration

        Args:
            entry (dict): A single row from the Excel file represented as a dictionary
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments. Must include 'fields', a list of available fields for validation

        Raises:
            ImportRuntimeError: If required fields are missing or processing fails

        Returns:
            dict: A dictionary representing the generated object ready for system import
        """
        try:
            possible_fields: list[dict] = kwargs['fields']
        except (KeyError, IndexError, ValueError) as err:
            raise ImportRuntimeError(err) from err

        working_object: dict = {
            'active': True,
            'type_id': self.get_config().get_type_id(),
            'fields': [],
            'author_id': self.request_user.get_public_id(),
            'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc)
        }

        current_mapping = self.get_config().get_mapping()
        property_entries: list[MapEntry] = current_mapping.get_entries_with_option(query={'type': 'property'})
        field_entries: list[MapEntry] = current_mapping.get_entries_with_option(query={'type': 'field'})

        # Insert properties
        for property_entry in property_entries:
            working_object.update({property_entry.get_name(): entry.get(property_entry.get_value())})

        # Improve insert object
        improve_object = ImproveObject(entry, property_entries, field_entries, possible_fields)
        entry = improve_object.improve_entry()

        # Validate insert fields
        for field_entry in field_entries:
            if field_entry.get_name() not in possible_fields:
                continue
            working_object['fields'].append(
                {'name': field_entry.get_name(),
                 'value': entry.get(field_entry.get_value())
                 })

        return working_object


    def start_import(self) -> ImporterObjectResponse:
        """
        Start the import process by parsing the provided Excel file

        Parses the file content into structured entries and prepares an import response

        Raises:
            ImportRuntimeError: If the parsing fails

        Returns:
            ImporterObjectResponse: Response indicating the result of the import preparation
        """
        try:
            parsed_response: ExcelObjectParserResponse = self.parser.parse(self.file)
        except ParserRuntimeError as err:
            raise ImportRuntimeError(err) from err

        LOGGER.debug(parsed_response)

        return ImporterObjectResponse('Excel Object Import')
