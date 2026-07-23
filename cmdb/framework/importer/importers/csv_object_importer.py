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
from logging import Logger, getLogger
from datetime import datetime, timezone

from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.content_types import CSVContent
from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.importer_constants import (
    DEFAULT_OBJECT_VERSION,
    MapEntryOptionKey,
    MapEntryType,
)
from cmdb.framework.importer.mapper.map_entry import MapEntry
from cmdb.framework.importer.configs.csv_object_importer_config import CsvObjectImporterConfig
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse
from cmdb.framework.importer.helper.improve_object import ImproveObject
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse

from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.importer import ImportRuntimeError, ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

# Mongo operators used in the reference-lookup query
MONGO_ELEM_MATCH: str = '$elemMatch'
MONGO_AND: str = '$and'

LOGGER: Logger = getLogger(__name__)

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

        mapping = self.get_config().get_mapping()
        property_entries: list[MapEntry] = mapping.get_entries_with_option(
            query={MapEntryOptionKey.TYPE.value: MapEntryType.PROPERTY.value}
        )
        field_entries: list[MapEntry] = mapping.get_entries_with_option(
            query={MapEntryOptionKey.TYPE.value: MapEntryType.FIELD.value}
        )
        foreign_entries: list[MapEntry] = mapping.get_entries_with_option(
            query={MapEntryOptionKey.TYPE.value: MapEntryType.REFERENCE.value}
        )

        # Coerce the raw cell values to their target types before building the object
        entry = ImproveObject(entry, property_entries, field_entries, possible_fields).improve_entry()
        object_fields = self._build_object_fields(field_entries, foreign_entries, entry, possible_fields)

        working_object: dict = {
            CmdbObjectKey.ACTIVE.value: True,
            CmdbObjectKey.TYPE_ID.value: self.get_config().get_type_id(),
            CmdbObjectKey.FIELDS.value: object_fields,
            CmdbObjectKey.AUTHOR_ID.value: self.request_user.get_public_id(),
            CmdbObjectKey.VERSION.value: DEFAULT_OBJECT_VERSION,
            CmdbObjectKey.CREATION_TIME.value: datetime.now(timezone.utc),
        }

        # Mapped properties are written directly onto the object (e.g. active, public_id)
        for property_entry in property_entries:
            working_object[property_entry.get_name()] = entry.get(property_entry.get_value())

        return working_object


    def _build_object_fields(
            self,
            field_entries: list[MapEntry],
            foreign_entries: list[MapEntry],
            entry: dict,
            possible_fields: list[dict],
        ) -> list[dict]:
        """
        Builds the object's ``fields`` list from the mapped regular fields and resolved references

        Only mapped fields that exist on the target type are included; each reference entry is
        resolved to the referenced object's public_id (unresolvable references are skipped)

        Args:
            field_entries (list[MapEntry]): Mapping entries for regular fields
            foreign_entries (list[MapEntry]): Mapping entries for object references
            entry (dict): The (already coerced) source row
            possible_fields (list[dict]): The target type's field definitions

        Returns:
            list[dict]: The {name, value} field dicts for the object
        """
        fields: list[dict] = []

        for entry_field in field_entries:
            field_exists = any(
                field[FieldKey.NAME.value] == entry_field.get_name() for field in possible_fields
            )

            if field_exists:
                fields.append({
                    CmdbObjectFieldKey.NAME.value: entry_field.get_name(),
                    CmdbObjectFieldKey.VALUE.value: entry.get(entry_field.get_value()),
                })

        for foreign_entry in foreign_entries:
            reference_field = self._resolve_reference_field(foreign_entry, entry)

            if reference_field:
                fields.append(reference_field)

        return fields


    def _resolve_reference_field(self, foreign_entry: MapEntry, entry: dict) -> dict | None:
        """
        Resolves a reference mapping entry to a {name, value} field pointing at another object

        Looks up the single object of the referenced type whose ``ref_name`` field matches the source
        value. Returns None (skipping the reference) when its options are incomplete or the reference
        cannot be resolved to exactly one object

        Args:
            foreign_entry (MapEntry): The mapping entry describing the reference
            entry (dict): The current source row

        Returns:
            dict | None: The reference field dict, or None if it could not be resolved
        """
        options: dict = foreign_entry.get_options()

        try:
            working_type_id = options[MapEntryOptionKey.TYPE_ID.value]
            ref_name = options[MapEntryOptionKey.REF_NAME.value]
        except KeyError:
            return None

        query: dict = {
            CmdbObjectKey.TYPE_ID.value: working_type_id,
            CmdbObjectKey.FIELDS.value: {
                MONGO_ELEM_MATCH: {
                    MONGO_AND: [
                        {CmdbObjectFieldKey.NAME.value: ref_name},
                        {CmdbObjectFieldKey.VALUE.value: entry.get(foreign_entry.get_value())},
                    ]
                }
            }
        }

        try:
            found_objects: list[CmdbObject] = self.objects_manager.get_objects_by(**query)
        except ObjectsManagerGetError as err:
            LOGGER.error('[CSV] Error while loading ref object %s', err)
            return None

        if len(found_objects) != 1:
            return None

        return {
            CmdbObjectFieldKey.NAME.value: foreign_entry.get_name(),
            CmdbObjectFieldKey.VALUE.value: found_objects[0].get_public_id(),
        }


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
