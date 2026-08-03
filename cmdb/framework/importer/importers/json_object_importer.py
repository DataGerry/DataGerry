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
Implementation of JsonObjectImporter
"""
from logging import Logger, getLogger
from datetime import datetime, timezone

from cmdb.manager import ObjectsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.content_types import JSONContent
from cmdb.framework.importer.importers.object_importer import ObjectImporter
from cmdb.framework.importer.importer_constants import DEFAULT_OBJECT_VERSION, JsonMappingKey
from cmdb.framework.importer.responses.json_object_parser_response import JsonObjectParserResponse
from cmdb.framework.importer.helper.improve_object import ImproveObject
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.framework.importer.configs.json_object_importer_config import JsonObjectImporterConfig

from cmdb.errors.importer import ImportRuntimeError, ParserNoContentError, ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              JsonObjectImporter - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonObjectImporter(ObjectImporter, JSONContent):
    """Object importer for JSON"""

    def __init__(self,
                 file=None,
                 config: JsonObjectImporterConfig | None = None,
                 parser: JsonObjectParser | None = None,
                 objects_manager: ObjectsManager | None = None,
                 request_user: CmdbUser | None = None) -> None:
        """
        Initialize the JsonObjectImporter

        Args:
            file: The JSON file to import
            config (JsonObjectImporterConfig | None): Configuration defining the mapping and import rules
            parser (JsonObjectParser | None): Parser instance handling the JSON parsing
            objects_manager (ObjectsManager | None): Manager used to read/insert/delete CmdbObjects
            request_user (CmdbUser | None): The user initiating the import request
        """
        super().__init__(
            file=file,
            file_type=self.FILE_TYPE,
            config=config,
            parser=parser,
            objects_manager=objects_manager,
            request_user=request_user
        )


    def generate_object(self, entry: dict, *args, **kwargs) -> dict:
        """
        Creates a native CmdbObject dict from a parsed JSON entry

        Args:
            entry (dict): A single parsed object from the JSON file

        Returns:
            dict: The generated object dict ready for import
        """
        map_properties: dict = self.config.get_mapping().get(JsonMappingKey.PROPERTIES.value)

        working_object: dict = {
            CmdbObjectKey.TYPE_ID.value: self.config.get_type_id(),
            CmdbObjectKey.FIELDS.value: [],
            CmdbObjectKey.VERSION.value: DEFAULT_OBJECT_VERSION,
            CmdbObjectKey.CREATION_TIME.value: datetime.now(timezone.utc),
        }

        if CmdbObjectKey.MULTI_DATA_SECTIONS.value in entry:
            working_object[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = entry[CmdbObjectKey.MULTI_DATA_SECTIONS.value]

        for prop in map_properties:
            working_object = self._map_element(prop, entry, working_object, map_properties)

        # Every provided field is kept (an unknown field is rejected later by normalization, not dropped);
        # only date coercion happens here - value-type validation/coercion is the import validator's job
        for entry_field in entry.get(CmdbObjectKey.FIELDS.value):
            entry_field[CmdbObjectFieldKey.VALUE.value] = ImproveObject.improve_date(
                entry_field[CmdbObjectFieldKey.VALUE.value]
            )
            working_object[CmdbObjectKey.FIELDS.value].append(entry_field)

        return working_object


    def _map_element(self, prop: str, entry: dict, working: dict, map_properties: dict) -> dict:
        """
        Copies one mapped property value from the entry onto the working object

        Args:
            prop (str): The target property name on the object
            entry (dict): The parsed source entry
            working (dict): The object being built (mutated in place)
            map_properties (dict): The property mapping (target property -> source key)

        Returns:
            dict: The working object
        """
        if map_properties:
            source_key = map_properties.get(prop)

            if source_key:
                value = entry.get(source_key)

                if value is not None:
                    working[prop] = value

        return working


    def start_import(self) -> ImporterObjectResponse:
        """
        Starts the import process by parsing the file, generating objects based on the parsed data,
        and importing those objects into the system

        The method performs the following steps:
        1. Uses the parser to parse the provided file
        2. Retrieves the fields for the specified object type based on the config
        3. Generates import objects based on the parsed response and object type fields
        4. Imports the generated objects and returns the result

        Returns:
            ImporterObjectResponse: The response after importing the objects, containing status and data

        Raises:
            ParserNoContentError: If the file carries no entry at all - re-raised as it is, because that
                is the caller's doing and not an import failure
            ImportRuntimeError: If parsing or importing fails
        """
        try:
            parsed_response: JsonObjectParserResponse = self.parser.parse(self.file)
            type_instance = self.resolve_target_type()
            type_fields = type_instance.get_fields()

            candidates = self._generate_objects(parsed_response, fields=type_fields)

            return self._import_for_type(candidates, type_instance)
        except ParserNoContentError:
            # The file holds no entry: a caller-actionable condition, not an import failure, so it
            # travels out untouched for the route to answer with a 400 naming the real reason
            raise
        except ParserRuntimeError as err:
            LOGGER.error("[start_import] Parsing error: %s", err, exc_info=True)
            raise ImportRuntimeError(f"Parsing failed: {err}") from err
        except Exception as err:
            LOGGER.error("[start_import] Unexpected error: %s. Type: %s", err, type(err), exc_info=True)
            raise ImportRuntimeError(f"Unexpected error: {err}") from err
