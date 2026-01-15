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
Implementation of CsvObjectImporter
"""
import logging
from datetime import datetime, timezone

from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.mapper.map_entry import MapEntry
from cmdb.framework.importer.configs.csv_object_importer_config import CsvObjectImporterConfig
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse
from cmdb.framework.importer.helper.improve_object import ImproveObject
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.importer import ImportRuntimeError, ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               CsvObjectImporter - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvObjectImporter(ObjectImporter, CSVContent):
    """
    CsvObjectImporter handles the import of CmdbObjects from CSV files

    It parses CSV content according to a provided configuration and mapping,
    generates objects compatible with the system's data structure,
    and resolves references to other existing objects where necessary.

    Extends: ObjectImporter, CSVContent
    """
    #pylint: disable=R0917
    def __init__(
            self,
            file=None,
            config: CsvObjectImporterConfig | None = None,
            parser: JsonObjectParser | None = None,
            objects_manager: ObjectsManager | None = None,
            request_user: CmdbUser | None = None) -> None:
        """
        Initialize the CsvObjectImporter

        Args:
            file: The CSV file to import
            config (CsvObjectImporterConfig): Configuration defining the mapping and rules for import
            parser (JsonObjectParser): Parser instance to handle object parsing logic
            objects_manager (ObjectsManager): Manager instance to retrieve and handle existing objects
            request_user (CmdbUser): The user who initiates the import request
        """
        super().__init__(
            file = file,
            file_type = self.FILE_TYPE,
            config = config,
            parser = parser,
            objects_manager = objects_manager,
            request_user = request_user
        )


    #pylint: disable=R0914
    def generate_object(self, entry: dict, *args, **kwargs) -> dict:
        """
        Generate an object dictionary from a CSV entry based on the import configuration

        Args:
            entry (dict): A single row from the CSV file represented as a dictionary
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments. Must include 'fields', a list of available fields for validation

        Raises:
            ImportRuntimeError: If required field information is missing or cannot be processed

        Returns:
            dict: A dictionary representing the generated object, ready to be imported into the system
        """
        try:
            possible_fields: list[dict] = kwargs['fields']
        except (KeyError, IndexError, ValueError) as err:
            raise ImportRuntimeError(f"[generate_object] can't import objects: {err}") from err

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
        foreign_entries: list[MapEntry] = current_mapping.get_entries_with_option(query={'type': 'ref'})

        # field/properties improvement
        improve_object = ImproveObject(entry, property_entries, field_entries, possible_fields)
        entry = improve_object.improve_entry()

        # Insert properties
        for property_entry in property_entries:
            working_object.update({property_entry.get_name(): entry.get(property_entry.get_value())})

        # Validate insert fields
        for entry_field in field_entries:
            field_exists = next((item for item in possible_fields if item["name"] == entry_field.get_name()), None)
            if field_exists:
                working_object['fields'].append(
                    {'name': entry_field.get_name(),
                     'value': entry.get(entry_field.get_value())
                     })

        for foreign_entry in foreign_entries:
            try:
                working_type_id = foreign_entry.get_options()['type_id']
            except (KeyError, IndexError):
                continue

            try:
                query: dict = {
                    'type_id': working_type_id,
                    'fields': {
                        '$elemMatch': {
                            '$and': [
                                {'name': foreign_entry.get_options()['ref_name']},
                                {'value': entry.get(foreign_entry.get_value())},
                            ]
                        }
                    }
                }

                founded_objects: list[CmdbObject] = self.objects_manager.get_objects_by(**query)

                if len(founded_objects) != 1:
                    continue

                working_object['fields'].append({
                    'name': foreign_entry.get_name(),
                    'value': founded_objects[0].get_public_id()
                })

            except (ObjectsManagerGetError, Exception) as err:
                LOGGER.error('[CSV] Error while loading ref object %s', err)
                continue

        return working_object


    def start_import(self) -> ImporterObjectResponse:
        """
        Initiates the import process by parsing a CSV file, generating objects, 
        and importing them into the system

        Returns:
            ImporterObjectResponse: The result of the import process

        Raises:
            ImportRuntimeError: If parsing or importing fails
        """
        try:
            parsed_response: CsvObjectParserResponse = self.parser.parse(self.file)


            type_instance_fields: list[dict] = self.objects_manager.get_object_type(
                self.config.get_type_id()
            ).get_fields()

            import_objects: list[dict] = self._generate_objects(parsed_response, fields=type_instance_fields)
            import_result: ImporterObjectResponse = self._import(import_objects)

            return import_result
        except ParserRuntimeError as err:
            LOGGER.error("[start_import] Parsing error: %s", err, exc_info=True)
            raise ImportRuntimeError(f"Parsing failed: {err}") from err

        except Exception as err:
            LOGGER.error("[start_import] Unexpected error: %s. Type: %s", err, type(err), exc_info=True)
            raise ImportRuntimeError(f"Unexpected error: {err}") from err
