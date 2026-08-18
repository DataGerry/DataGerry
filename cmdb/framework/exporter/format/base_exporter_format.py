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
Implementation of the BaseExporterFormat
"""
import json
from json import JSONDecodeError
from typing import Any

from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.exporter.exporter_constants import ExporterOptionKey, ExporterMetadataKey
from cmdb.framework.rendering.render_constants import RenderedFieldKey

from cmdb.errors.exporter import ExporterColumnError, ExporterMetadataError
# -------------------------------------------------------------------------------------------------------------------- #

# RenderResult keys read while exporting (these live on the render result / type information / object
# information, not on the field definition, so they are not covered by FieldKey / CmdbObjectKey).
# The four reference-expansion keys are owned by the renderer and shared through `RenderedFieldKey`
TYPE_INFO_LABEL_KEY: str = 'type_label'
TYPE_INFO_NAME_KEY: str = 'type_name'
TYPE_INFO_ID_KEY: str = 'type_id'
OBJECT_INFO_ID_KEY: str = 'object_id'
REFERENCE_OBJECT_ID_KEY: str = 'object_id'

# Value written into a tabular (CSV / XLSX) cell that carries no data: a continuation row's identity /
# regular columns, or a multi-data-section column whose section has no entry for that row
EMPTY_CELL: str = ''

# Friendly header labels for the identity columns in a HUMAN_READABLE export (they have no field
# definition to source a label from)
IDENTITY_COLUMN_LABELS: dict[str, str] = {
    CmdbObjectKey.PUBLIC_ID.value: 'Public ID',
    CmdbObjectKey.ACTIVE.value: 'Active',
}


def to_export_cell(value: Any) -> str:
    """
    Renders one resolved value as the text of an export cell

    A field an object never filled in resolves to None, and stringifying that directly writes the
    literal text `'None'` into the cell — which is not what the object holds, and which an import
    then reads back as a real value (`auto_cast` turns the text 'None' into None only by accident of
    its noneify step). An absent value is an `EMPTY_CELL` instead. Every other value is stringified
    as before, so `0`, `False` and `''` keep exporting as their own text rather than being blanked

    Args:
        value (Any): The resolved field / metadata value

    Returns:
        str: The cell text, empty when the value is absent
    """
    return EMPTY_CELL if value is None else str(value)


class BaseExporterFormat:
    """
    Base class for exporter formats

    Subclasses set the metadata class attributes below and implement `export`. Objects are always
    instantiated without arguments (`SomeFormat()`), so there is no `__init__` to override.

    Attributes:
        FILE_EXTENSION (str): The file extension for the export format
        MIME_TYPE (str): The HTTP Content-Type used when streaming the export (set by every subclass)
        LABEL (str): Label for the exporter format
        MULTITYPE_SUPPORT (bool): Indicates if multiple types are supported
        ICON (str): Icon representation of the format
        DESCRIPTION (str): Description of the exporter format
        ACTIVE (bool): Status indicating if the format is active
    """
    FILE_EXTENSION = None
    MIME_TYPE = None
    LABEL = None
    MULTITYPE_SUPPORT = False
    ICON = None
    DESCRIPTION = None
    ACTIVE = None


    @staticmethod
    def resolve_export_view(args: tuple) -> tuple[str, dict | None]:
        """
        Determines the requested export view and any render-view column metadata from the export args

        Returns the requested `view` (defaulting to the NATIVE view) and, only when the view is RENDER
        and the caller supplied `metadata`, the parsed metadata override dict (otherwise None). Column /
        header overrides therefore require the render view; how a format treats a render view given
        without metadata is left to the individual format.

        The override comes straight from the query string, so it is validated here rather than trusted:
        it has to be JSON, it has to be an object, and its `header` / `columns` have to be lists. A
        string where a list is expected would otherwise be spread character by character into the
        exported header

        Args:
            args (tuple): The positional export args; `args[0]` (if present) is the options dict

        Raises:
            ExporterMetadataError: If the metadata override is not JSON, not an object, or carries a
                                   `header` / `columns` that is not a list

        Returns:
            tuple[str, dict | None]: (requested view, parsed metadata override or None)
        """
        options = args[0] if args else {}
        view = options.get(ExporterOptionKey.VIEW.value, ExporterConfigType.NATIVE.value)
        raw_metadata = options.get(ExporterOptionKey.METADATA.value)

        if raw_metadata and view.upper() == ExporterConfigType.RENDER.value:
            return view, BaseExporterFormat._parse_metadata_override(raw_metadata)

        return view, None


    @staticmethod
    def _parse_metadata_override(raw_metadata: Any) -> dict:
        """
        Decodes and checks the render-view metadata override

        Args:
            raw_metadata (Any): The raw `metadata` value from the export request

        Raises:
            ExporterMetadataError: If the value is not JSON, not an object, or carries a
                                   `header` / `columns` that is not a list

        Returns:
            dict: The parsed override
        """
        try:
            metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
        except JSONDecodeError as err:
            raise ExporterMetadataError(f"The export metadata is not valid JSON: {err}") from err

        if not isinstance(metadata, dict):
            raise ExporterMetadataError('The export metadata must be a JSON object!')

        for key in (ExporterMetadataKey.HEADER.value, ExporterMetadataKey.COLUMNS.value):
            value = metadata.get(key)

            if value is not None and not isinstance(value, list):
                raise ExporterMetadataError(f"The export metadata '{key}' must be a list!")

        return metadata


    @staticmethod
    def serialize_multi_data_sections(multi_data_sections: list[dict]) -> list[dict]:
        """
        Serializes an object's multi-data sections into a plain, JSON-serializable structure

        Shared by the JSON and CSV export formats so both emit the same MDS shape: one entry per
        section (`section_id`, `highest_id`, `values`), each value a row (`multi_data_id`, `data`),
        each data entry a `{name, value}` pair. The field `type` is intentionally omitted - it is
        re-derived from the type's section template on import/read.

        Args:
            multi_data_sections (list[dict]): The object's raw multi-data sections (or None)

        Returns:
            list[dict]: The serialized sections (an empty list when there are none)
        """
        sections: list[dict] = []

        for mds in multi_data_sections or []:
            rows: list[dict] = []

            for row in mds.get(CmdbObjectMdsKey.VALUES.value, []):
                data = [
                    {FieldKey.NAME.value: entry.get(FieldKey.NAME.value),
                     FieldKey.VALUE.value: entry.get(FieldKey.VALUE.value)}
                    for entry in row.get(CmdbObjectMdsRowKey.DATA.value, [])
                ]
                rows.append({
                    CmdbObjectMdsRowKey.MULTI_DATA_ID.value: row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value),
                    CmdbObjectMdsRowKey.DATA.value: data,
                })

            sections.append({
                CmdbObjectMdsKey.SECTION_ID.value: mds.get(CmdbObjectMdsKey.SECTION_ID.value),
                CmdbObjectMdsKey.HIGHEST_ID.value: mds.get(CmdbObjectMdsKey.HIGHEST_ID.value),
                CmdbObjectMdsKey.VALUES.value: rows,
            })

        return sections


    def export(self, data, *args):
        """
        Exports the given data

        This method must be implemented by subclasses

        Args:
            data: The data to export
            *args: Additional arguments for export customization

        Raises:
            NotImplementedError: If the method is not implemented by a subclass
        """
        raise NotImplementedError("The 'export' method must be implemented in a subclass.")


    @staticmethod
    def summary_renderer(obj, field: dict, view: str = 'native') -> Any:  # pylint: disable=unused-argument
        """
        Resolves the exported value of a single field for the given view

        In the NATIVE view (the default) the field's raw stored value is returned. In the RENDER view a
        reference field is rendered to the referenced object's summary line
        (`<referenced type_label> #<referenced object_id> | <summary values…>`); all other fields still
        return their raw value. (`obj` is kept for the shared format-callback signature; it is not used.)

        Args:
            obj: The rendered object (unused; kept for the shared callback signature)
            field (dict): The field to resolve
            view (str): The view type, `'native'` or `'render'`. Defaults to `'native'`

        Returns:
            Any: The rendered reference summary string, or the field's raw value (which may be None)
        """
        if not isinstance(field, dict):
            return ""

        # In the RENDER view a reference field is shown as the REFERENCED object's summary line
        is_render_view = view.upper() == ExporterConfigType.RENDER.value

        if is_render_view and field.get(FieldKey.TYPE.value) == FieldType.REFERENCE.value:
            return BaseExporterFormat._reference_summary_line(field)

        return field.get(FieldKey.VALUE.value, None)

    # ------------------------------ Tabular (CSV / XLSX) multi-data-section flattening ------------------------------ #
    # The tabular formats give every multi-data-section (MDS) field its own column and spread an object's
    # MDS entries over consecutive rows: the first row carries the identity + regular fields plus each
    # section's first entry; each following row leaves the identity / regular columns empty and carries
    # only the next entry of each section (a section with no further entry leaves its columns empty). The
    # helpers below build that layout so CSV and XLSX share one implementation.

    @staticmethod
    def extract_mds_layout(sections: list[dict]) -> list[tuple[str, list[str]]]:
        """
        Extracts the ordered multi-data-section layout from a type's rendered sections

        Each multi-data-section (`type == 'multi-data-section'`) contributes its `name` (which equals the
        object-side `section_id`) and its ordered list of field names. Non-MDS sections are ignored.

        Args:
            sections (list[dict]): The rendered `RenderResult.sections` of the (shared) type

        Returns:
            list[tuple[str, list[str]]]: One `(section_id, [field_name, …])` tuple per MDS section, in
                                         type order
        """
        layout: list[tuple[str, list[str]]] = []

        for section in sections or []:
            if section.get(SectionKey.TYPE.value) == SectionType.MDS_SECTION.value:
                layout.append((
                    section.get(SectionKey.NAME.value),
                    list(section.get(SectionKey.FIELDS.value, [])),
                ))

        return layout

    @staticmethod
    def assert_unique_columns(columns: list[str]) -> None:
        """
        Refuses the export when the resolved column names are not unique

        Args:
            columns (list[str]): The full ordered header (identity + regular + MDS columns)

        Raises:
            ExporterColumnError: If any column name occurs more than once
        """
        seen: set[str] = set()
        duplicates: list[str] = []

        for column in columns:
            if column in seen and column not in duplicates:
                duplicates.append(column)
            seen.add(column)

        if duplicates:
            raise ExporterColumnError(
                f"Cannot export: duplicate field name(s) {duplicates}. "
                "Field names must be unique within a type."
            )

    @staticmethod
    def collect_mds_entries(obj, mds_layout: list[tuple[str, list[str]]]) -> dict[str, list[dict]]:
        """
        Collects one object's multi-data-section entries as per-section name→value maps

        For every section in the layout, the object's matching section (by `section_id`) is looked up and
        each of its rows is flattened into a `{field_name: value}` dict. A section the object does not
        carry yields an empty list.

        Args:
            obj: The rendered object whose multi-data sections are read
            mds_layout (list[tuple[str, list[str]]]): The `(section_id, field_names)` layout of the type

        Returns:
            dict[str, list[dict]]: `section_id` -> ordered list of that section's row value-maps
        """
        section_by_id: dict[str, dict] = {
            section.get(CmdbObjectMdsKey.SECTION_ID.value): section
            for section in obj.multi_data_sections or []
        }

        entries: dict[str, list[dict]] = {}

        for section_id, _ in mds_layout:
            section = section_by_id.get(section_id)
            rows: list[dict] = []

            if section:
                for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
                    rows.append({
                        item.get(CmdbObjectFieldKey.NAME.value): item.get(CmdbObjectFieldKey.VALUE.value)
                        for item in row.get(CmdbObjectMdsRowKey.DATA.value, [])
                    })

            entries[section_id] = rows

        return entries

    @staticmethod
    def object_prefix_cells(
            obj,
            header: list[str],
            regular_columns: list[str],
            view: str,
            human_readable: bool = False,
            location_names: dict | None = None) -> list[str]:
        """
        Builds the identity + regular-field cells that lead an object's first row

        Args:
            obj: The rendered object to serialize
            header (list[str]): The identity columns (`public_id` maps to `object_id`)
            regular_columns (list[str]): The regular (non-MDS) field names, in output order
            view (str): The export view passed to the field value resolver
            human_readable (bool): Resolve reference / ref-section / location fields to display text
            location_names (dict | None): Resolved `{location public_id: name}` map (human-readable only)

        Returns:
            list[str]: The stringified identity cells followed by the regular-field cells
        """
        obj_fields: dict = {
            field[FieldKey.NAME.value]:
                BaseExporterFormat.resolve_export_value(obj, field, view, human_readable, location_names)
            for field in obj.fields
        }

        cells: list[str] = []

        for head in header:
            info_key = OBJECT_INFO_ID_KEY if head == CmdbObjectKey.PUBLIC_ID.value else head
            cells.append(to_export_cell(obj.object_information.get(info_key)))

        cells.extend(to_export_cell(obj_fields.get(name)) for name in regular_columns)

        return cells

    @staticmethod
    def mds_cells_for_index(
            mds_layout: list[tuple[str, list[str]]],
            section_entries: dict[str, list[dict]],
            index: int) -> list[str]:
        """
        Builds the multi-data-section cells for one row (the `index`-th entry of each section)

        A section without an `index`-th entry, an entry missing one of its fields, or an entry whose
        field carries no value, yields an empty cell.

        Args:
            mds_layout (list[tuple[str, list[str]]]): The `(section_id, field_names)` layout of the type
            section_entries (dict[str, list[dict]]): `section_id` -> ordered row value-maps for the object
            index (int): The zero-based row index within the object's block

        Returns:
            list[str]: The stringified MDS cells, in layout (section then field) order
        """
        cells: list[str] = []

        for section_id, field_names in mds_layout:
            section_rows = section_entries[section_id]
            entry = section_rows[index] if index < len(section_rows) else {}
            for field_name in field_names:
                cells.append(to_export_cell(entry.get(field_name)))

        return cells

    @staticmethod
    def build_object_rows(
            obj,
            header: list[str],
            regular_columns: list[str],
            mds_layout: list[tuple[str, list[str]]],
            view: str,
            human_readable: bool = False,
            location_names: dict | None = None) -> list[list[str]]:
        """
        Builds all tabular rows for a single object (identity + regular fields + spread MDS entries)

        The object spans `max(1, largest MDS-section entry count)` rows. The first row carries the
        identity + regular field values plus every MDS section's first entry; each following row leaves
        the identity and regular columns empty and carries only the next entry of each MDS section (empty
        where a section has no further entry). MDS cell values are always the raw stored values (a
        HUMAN_READABLE export only resolves the top-level regular fields).

        Args:
            obj: The rendered object to serialize
            header (list[str]): The identity columns (`public_id` maps to `object_id`)
            regular_columns (list[str]): The regular (non-MDS) field names, in output order
            mds_layout (list[tuple[str, list[str]]]): The `(section_id, field_names)` layout of the type
            view (str): The export view passed to the field value resolver
            human_readable (bool): Resolve reference / ref-section / location regular fields to display text
            location_names (dict | None): Resolved `{location public_id: name}` map (human-readable only)

        Returns:
            list[list[str]]: The stringified rows for this object
        """
        section_entries = BaseExporterFormat.collect_mds_entries(obj, mds_layout)
        row_count: int = max((len(rows) for rows in section_entries.values()), default=0) or 1

        first_prefix = BaseExporterFormat.object_prefix_cells(
            obj, header, regular_columns, view, human_readable, location_names
        )
        blank_prefix = [EMPTY_CELL] * len(first_prefix)

        rows: list[list[str]] = []

        for index in range(row_count):
            prefix = first_prefix if index == 0 else blank_prefix
            rows.append([*prefix, *BaseExporterFormat.mds_cells_for_index(mds_layout, section_entries, index)])

        return rows

    # ------------------------------- HUMAN_READABLE (presentation) export helpers ------------------------------- #
    # A HUMAN_READABLE export resolves reference / ref-section / location field VALUES to display text and
    # replaces the column HEADERS (field names) with field labels. Value resolution runs while the rows
    # are built (per field); the header relabel is applied afterwards on the finished header (labels are
    # not required to be unique, so they must never be used as build-time keys).

    @staticmethod
    def is_human_readable(options: dict | None) -> bool:
        """
        Reports whether the HUMAN_READABLE presentation export was requested

        Args:
            options (dict | None): The export options (`params.optional`)

        Returns:
            bool: True when the `human_readable` option is truthy
        """
        value = (options or {}).get(ExporterOptionKey.HUMAN_READABLE.value)

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() in ('true', '1', 'yes')

    @staticmethod
    def resolve_export_value(obj, field: dict, view: str, human_readable: bool = False,
                             location_names: dict | None = None) -> Any:
        """
        Resolves the exported value of a single field

        In a HUMAN_READABLE export a reference field becomes its summary line, a ref-section field a
        constructed summary line and a location field the location's name; every other field (and every
        field in a non-human-readable export) falls back to `summary_renderer`.

        Args:
            obj: The rendered object providing type/reference context
            field (dict): The field to resolve
            view (str): The export view (used by the non-human-readable `summary_renderer` fallback)
            human_readable (bool): Whether to resolve references / locations to display text
            location_names (dict | None): Resolved `{location public_id: name}` map

        Returns:
            Any: The resolved display value
        """
        if human_readable and isinstance(field, dict):
            field_type = field.get(FieldKey.TYPE.value)

            if field_type == FieldType.REFERENCE.value:
                return BaseExporterFormat._reference_summary_line(field)
            if field_type == FieldType.REF_SECTION.value:
                return BaseExporterFormat._ref_section_summary_line(field)
            if field_type == FieldType.LOCATION.value:
                value = field.get(FieldKey.VALUE.value)
                if value in (None, ''):
                    return EMPTY_CELL
                return (location_names or {}).get(value, str(value))

        return BaseExporterFormat.summary_renderer(obj, field, view)

    @staticmethod
    def _reference_summary_line(field: dict) -> str:
        """
        Builds the summary line for a reference field: `<type_label> #<object_id> | <summary values>`

        Uses the referenced object's own type/id (from the rendered `reference` expansion), so the line
        describes the referenced object. An unresolved / empty reference yields its raw value (or empty).

        Args:
            field (dict): The reference field (carrying its rendered `reference` expansion)

        Returns:
            str: The reference summary line
        """
        value = field.get(FieldKey.VALUE.value)
        reference = field.get(RenderedFieldKey.REFERENCE.value) or {}
        object_id = reference.get(REFERENCE_OBJECT_ID_KEY)

        if not object_id:
            return EMPTY_CELL if value in (None, '') else str(value)

        summary_values = [
            to_export_cell(item.get(FieldKey.VALUE.value))
            for item in reference.get(RenderedFieldKey.SUMMARIES.value, [])
        ]
        summary_values = [summary for summary in summary_values if summary]

        line = f"{reference.get(TYPE_INFO_LABEL_KEY, '')} #{object_id}".strip()

        if summary_values:
            line += ' | ' + ' | '.join(summary_values)

        return line

    @staticmethod
    def _ref_section_summary_line(field: dict) -> str:
        """
        Builds the summary line for a ref-section field: `<type_label> #<ref_id> | <pulled field values>`

        A ref-section carries no pre-built summary line, so it is constructed from the referenced type
        label, the referenced object id (the field value) and the pulled-in referenced field values.

        Args:
            field (dict): The ref-section field (carrying its rendered `references` expansion)

        Returns:
            str: The constructed ref-section summary line
        """
        value = field.get(FieldKey.VALUE.value)

        if value in (None, ''):
            return EMPTY_CELL

        references = field.get(RenderedFieldKey.REFERENCES.value) or {}
        pulled_values = [
            to_export_cell(pulled.get(FieldKey.VALUE.value))
            for pulled in references.get(RenderedFieldKey.FIELDS.value, [])
        ]
        # An unfilled pulled-in field is already an empty cell, so the plain truthiness filter is
        # enough: the previous `!= 'None'` guard also dropped a value that genuinely reads "None"
        pulled_values = [pulled for pulled in pulled_values if pulled]

        line = f"{references.get(TYPE_INFO_LABEL_KEY, '')} #{value}".strip()

        if pulled_values:
            line += ' | ' + ' | '.join(pulled_values)

        return line

    @staticmethod
    def build_field_label_map(data: list) -> dict[str, str]:
        """
        Builds a `{field name: field label}` map from the (shared) type's rendered fields

        Every field falls back to its own name when it has no label. Covers regular and MDS fields
        (both appear in the flat `fields` list).

        Args:
            data (list): The rendered objects (the first object's fields define the map)

        Returns:
            dict[str, str]: The field-name-to-label map (empty when there is no data)
        """
        if not data:
            return {}

        return {
            field[FieldKey.NAME.value]: (field.get(FieldKey.LABEL.value) or field[FieldKey.NAME.value])
            for field in data[0].fields
        }

    @staticmethod
    def label_for_column(name: str, field_labels: dict[str, str]) -> str:
        """
        Resolves the display label for a single header column name

        Identity columns use their friendly label; field columns use the field label; anything else
        falls back to the column name itself.

        Args:
            name (str): The header column name
            field_labels (dict[str, str]): The field-name-to-label map

        Returns:
            str: The label to show for the column
        """
        if name in IDENTITY_COLUMN_LABELS:
            return IDENTITY_COLUMN_LABELS[name]

        return field_labels.get(name, name)

    @staticmethod
    def relabel_header(header: list[str], data: list) -> list[str]:
        """
        Relabels a finished header row (field names -> labels) for a HUMAN_READABLE export

        Applied as the last step so labels (which need not be unique) never act as build-time keys.

        Args:
            header (list[str]): The finished header of column NAMES
            data (list): The rendered objects supplying the field labels

        Returns:
            list[str]: The header with each column name replaced by its label
        """
        field_labels = BaseExporterFormat.build_field_label_map(data)

        return [BaseExporterFormat.label_for_column(name, field_labels) for name in header]
