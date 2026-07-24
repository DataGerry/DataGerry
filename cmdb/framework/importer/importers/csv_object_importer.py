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
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_type_enum import SectionType
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

# The first multi-data-section row id handed out on import (the section's highest_id counter is 0-based,
# so ids run 1..n and highest_id ends at the row count) - mirrors the object-edit MDS row assignment
FIRST_MDS_ROW_ID: int = 1

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

    Multi-data-sections (MDS) are carried by the flattened CSV export layout: every MDS field is its
    own column and an object's MDS entries are spread over consecutive rows (the first row holds the
    identity + regular fields plus each section's first entry; each following row leaves the identity /
    regular columns empty and carries only the next entry of each section). Rows are grouped back into a
    single object by the ``public_id`` column - a row with an empty ``public_id`` continues the previous
    object.

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


    def _generate_objects(self, parsed: CsvObjectParserResponse, *args, **kwargs) -> list[tuple[dict, dict]]:
        """
        Groups the parsed rows into objects and builds one ``(provided, generated)`` candidate per object

        Consecutive rows are grouped by the ``public_id`` column (a row with an empty ``public_id``
        continues the previous object), so an object spread over several rows by its multi-data sections
        is rebuilt as a single object. The regular fields + properties come from the group's first
        (primary) row; the multi-data sections are reassembled from every row in the group. The MDS is
        collected from the raw rows before ``generate_object`` runs, because value coercion mutates the
        primary row in place.

        Args:
            parsed (CsvObjectParserResponse): The parser response holding the index-keyed rows

        Keyword Args:
            header (list): The CSV header (column names)
            mds_layout (list[tuple[str, list[str]]]): The type's ``(section_id, field_names)`` MDS layout

        Returns:
            list[tuple[dict, dict]]: One (provided_data, generated_object) pair per reconstructed object
        """
        header: list = kwargs.get('header') or []
        mds_layout: list[tuple[str, list[str]]] = kwargs.get('mds_layout') or []

        candidates: list[tuple[dict, dict]] = []

        for group in self._group_rows(parsed.entries, header):
            primary = group[0]

            provided = self._to_provided_json(primary, **kwargs)
            multi_data_sections = self._build_multi_data_sections(group, header, mds_layout)
            generated = self.generate_object(primary, *args, **kwargs)

            if multi_data_sections:
                generated[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = multi_data_sections

            candidates.append((provided, generated))

        return candidates


    @staticmethod
    def _group_rows(entries: list[dict], header: list) -> list[list[dict]]:
        """
        Groups consecutive CSV rows into per-object blocks using the ``public_id`` column

        A row whose ``public_id`` cell is empty continues the previous object (it carries only the next
        multi-data-section entries); any other row starts a new object. When the CSV has no ``public_id``
        column each row is its own object (no multi-row grouping).

        Args:
            entries (list[dict]): The parsed rows, each keyed by column index
            header (list): The CSV header (column names)

        Returns:
            list[list[dict]]: One list of rows per object, in file order
        """
        public_id_key = CmdbObjectKey.PUBLIC_ID.value
        public_id_index = header.index(public_id_key) if header and public_id_key in header else None

        groups: list[list[dict]] = []

        for entry in entries:
            continues_previous = (
                public_id_index is not None
                and groups
                and CsvObjectImporter._is_blank(entry.get(public_id_index))
            )

            if continues_previous:
                groups[-1].append(entry)
            else:
                groups.append([entry])

        return groups


    @staticmethod
    def _build_multi_data_sections(
            group: list[dict],
            header: list,
            mds_layout: list[tuple[str, list[str]]]) -> list[dict]:
        """
        Reassembles an object's multi-data sections from its group of CSV rows

        For every MDS section, each row of the group contributes one entry unless all of that section's
        columns are empty in that row (that is how a section with fewer entries than another leaves its
        trailing rows blank). Row ids are assigned sequentially from ``FIRST_MDS_ROW_ID`` and the
        section's ``highest_id`` is set to the resulting entry count, matching the object-edit convention.

        Args:
            group (list[dict]): The rows belonging to one object (primary + continuation rows)
            header (list): The CSV header (column names)
            mds_layout (list[tuple[str, list[str]]]): The type's ``(section_id, field_names)`` MDS layout

        Returns:
            list[dict]: The reconstructed multi-data-section instances (empty when the object has none)
        """
        sections: list[dict] = []

        for section_id, field_names in mds_layout:
            # Only the section's fields that are actually columns in this CSV can be restored
            present_fields = [(name, header.index(name)) for name in field_names if name in header]
            if not present_fields:
                continue

            values: list[dict] = []

            for row in group:
                cells = [(name, row.get(index)) for name, index in present_fields]

                # A row with no data for this section does not contribute an entry (unequal counts)
                if all(CsvObjectImporter._is_blank(value) for _, value in cells):
                    continue

                values.append({
                    CmdbObjectMdsRowKey.MULTI_DATA_ID.value: len(values) + FIRST_MDS_ROW_ID,
                    CmdbObjectMdsRowKey.DATA.value: [
                        {CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: value}
                        for name, value in cells
                    ],
                })

            if values:
                sections.append({
                    CmdbObjectMdsKey.SECTION_ID.value: section_id,
                    CmdbObjectMdsKey.HIGHEST_ID.value: len(values),
                    CmdbObjectMdsKey.VALUES.value: values,
                })

        return sections


    @staticmethod
    def _build_mds_layout(type_instance: CmdbObject) -> list[tuple[str, list[str]]]:
        """
        Extracts the ordered multi-data-section layout from a type definition

        Args:
            type_instance: The target ``CmdbType`` being imported into

        Returns:
            list[tuple[str, list[str]]]: One ``(section_id, [field_name, …])`` tuple per MDS section
        """
        layout: list[tuple[str, list[str]]] = []

        for section in type_instance.get_sections():
            if getattr(section, 'type', None) == SectionType.MDS_SECTION.value:
                layout.append((section.name, list(section.get_fields())))

        return layout


    @staticmethod
    def _is_blank(value) -> bool:
        """
        Reports whether a parsed CSV cell carries no value

        Args:
            value: The parsed cell value (``auto_cast`` turns an empty cell into an empty string)

        Returns:
            bool: True when the cell is None or an empty string
        """
        return value is None or value == ''


    def generate_object(self, entry: dict, *args, **kwargs) -> dict:
        """
        Generate an object dictionary from a CSV row based on the import configuration

        Builds the regular fields, properties and references from the given (primary) row. Multi-data
        sections are attached separately by ``_generate_objects`` from the whole row group, so any MDS
        field mapped as a regular field is skipped here to avoid emitting it twice.

        Args:
            entry (dict): A single row from the CSV file represented as a dictionary

        Keyword Args:
            fields (list[dict]): The target type's field definitions (required)
            mds_layout (list[tuple[str, list[str]]]): The type's MDS layout (its fields are excluded here)

        Raises:
            ImportRuntimeError: If required field information is missing or cannot be processed

        Returns:
            dict: A dictionary representing the generated object, ready to be imported into the system
        """
        try:
            possible_fields: list[dict] = kwargs['fields']
        except (KeyError, IndexError, ValueError) as err:
            raise ImportRuntimeError(f"[generate_object] can't import objects: {err}") from err

        mds_layout: list[tuple[str, list[str]]] = kwargs.get('mds_layout') or []
        mds_field_names: set[str] = {name for _, field_names in mds_layout for name in field_names}

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
        object_fields = self._build_object_fields(
            field_entries, foreign_entries, entry, possible_fields, mds_field_names
        )

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


    def _to_provided_json(self, entry: dict, **kwargs) -> dict:
        """
        Reconstructs the CSV row as a header-keyed JSON object (the data the user provided)

        The parser keys each row by column index; this maps the header column names onto those values
        so a rejected/failed row is reported as a readable ``{column: value}`` object.

        Args:
            entry (dict): The parsed CSV row (keyed by column index)

        Keyword Args:
            header (list): The CSV header (column names)

        Returns:
            dict: The row as a {column_name: value} object (empty when there is no header)
        """
        header = kwargs.get('header') or []

        return {column: entry.get(index) for index, column in enumerate(header)}


    def _build_object_fields(
            self,
            field_entries: list[MapEntry],
            foreign_entries: list[MapEntry],
            entry: dict,
            possible_fields: list[dict],
            mds_field_names: set[str],
        ) -> list[dict]:
        """
        Builds the object's ``fields`` list from the mapped regular fields and resolved references

        Only mapped fields that exist on the target type and are not multi-data-section fields are
        included; each reference entry is resolved to the referenced object's public_id (unresolvable
        references are skipped)

        Args:
            field_entries (list[MapEntry]): Mapping entries for regular fields
            foreign_entries (list[MapEntry]): Mapping entries for object references
            entry (dict): The (already coerced) source row
            possible_fields (list[dict]): The target type's field definitions
            mds_field_names (set[str]): Field names that belong to a multi-data-section (excluded here)

        Returns:
            list[dict]: The {name, value} field dicts for the object
        """
        fields: list[dict] = []

        for entry_field in field_entries:
            # MDS fields are restored from the row group, not as a flat field
            if entry_field.get_name() in mds_field_names:
                continue

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
            type_instance = self.objects_manager.get_object_type(self.config.get_type_id())

            header = parsed_response.get_header_list() or []
            mds_layout = self._build_mds_layout(type_instance)

            candidates = self._generate_objects(
                parsed_response, fields=type_instance.get_fields(), header=header, mds_layout=mds_layout
            )

            return self._import(candidates, type_instance.special_type)
        except ParserRuntimeError as err:
            LOGGER.error("[start_import] Parsing error: %s", err, exc_info=True)
            raise ImportRuntimeError(f"Parsing failed: {err}") from err

        except Exception as err:
            LOGGER.error("[start_import] Unexpected error: %s. Type: %s", err, type(err), exc_info=True)
            raise ImportRuntimeError(f"Unexpected error: {err}") from err
