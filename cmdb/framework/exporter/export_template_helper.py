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
Header of an object-import template (framework layer)

An import template is a CSV carrying nothing but its header row: the columns a user fills in to create
CmdbObjects of one CmdbType. Each column is self-describing -
``<Field label> [MDS-<Section label>] [<field name>]`` - so the person filling it in reads the label
while the importer still finds the identifier, and a field belonging to a multi-data-section says so.

The column ORDER mirrors an object CSV export of the same type (identity columns, then the regular
fields, then the multi-data-section fields grouped per section), so a template is structurally the same
document as an export of that type with no rows.

The functions here are pure: they read a CmdbType and return strings, with no database and no request
involved.
"""
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_type_enum import SectionType

from cmdb.framework.exporter.exporter_constants import (
    TEMPLATE_ACTIVE_LABEL,
    TEMPLATE_COLUMN_PART_SEPARATOR,
    TEMPLATE_FIELD_NAME_TEMPLATE,
    TEMPLATE_MDS_MARKER_TEMPLATE,
    TEMPLATE_PUBLIC_ID_LABEL,
)
# -------------------------------------------------------------------------------------------------------------------- #


def build_template_column(label: str, field_name: str, mds_section_label: str | None = None) -> str:
    """
    Assembles one column header of an import template

    Args:
        label (str): Human-readable label leading the column
        field_name (str): The field's unique name, which closes the column in brackets
        mds_section_label (str | None): Label of the multi-data-section owning the field, or None for a
                                        regular field. Defaults to None

    Returns:
        str: e.g. `Hostname [hostname]` or `Port [MDS-Interfaces] [port]`
    """
    parts: list[str] = [label]

    if mds_section_label:
        parts.append(TEMPLATE_MDS_MARKER_TEMPLATE.format(section=mds_section_label))

    parts.append(TEMPLATE_FIELD_NAME_TEMPLATE.format(name=field_name))

    return TEMPLATE_COLUMN_PART_SEPARATOR.join(parts)


def build_field_label_map(type_instance: CmdbType) -> dict[str, str]:
    """
    Maps every field name of a CmdbType onto the label to show for it

    A field without a label (or with an empty one) falls back to its own name, so a column is never
    headed by the bracketed identifier alone

    Args:
        type_instance (CmdbType): The CmdbType whose fields should be mapped

    Returns:
        dict[str, str]: {field name: label}
    """
    labels: dict[str, str] = {}

    for a_field in type_instance.get_fields():
        field_name = a_field.get(FieldKey.NAME.value)

        if not field_name:
            continue

        labels[field_name] = a_field.get(FieldKey.LABEL.value) or field_name

    return labels


def collect_template_field_layout(type_instance: CmdbType) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """
    Splits a CmdbType's fields into the regular columns and the multi-data-section layout

    The type's sections are walked in their declared order, so the template follows the layout a user
    sees in the UI. A field name is emitted once: the first section placing it wins, which keeps a
    malformed type (the same field in two sections) from producing a duplicate column. A field that no
    section places at all is appended to the regular columns rather than dropped, so a template never
    silently omits part of the type

    Args:
        type_instance (CmdbType): The CmdbType to lay out

    Returns:
        tuple[list[str], list[tuple[str, list[str]]]]: The regular field names, and one
            `(section label, [field name, …])` tuple per multi-data-section
    """
    regular_fields: list[str] = []
    mds_layout: list[tuple[str, list[str]]] = []
    seen_fields: set[str] = set()

    for a_section in type_instance.render_meta.sections or []:
        section_fields: list[str] = []

        for field_name in getattr(a_section, 'fields', None) or []:
            if not field_name or field_name in seen_fields:
                continue

            seen_fields.add(field_name)
            section_fields.append(field_name)

        if a_section.type == SectionType.MDS_SECTION:
            # A section label always exists (TypeSection defaults it from the name), but stay defensive
            mds_layout.append((a_section.label or a_section.name, section_fields))
        else:
            regular_fields.extend(section_fields)

    # Fields the type declares but no section places would otherwise be missing from the template
    for a_field in type_instance.get_fields():
        field_name = a_field.get(FieldKey.NAME.value)

        if field_name and field_name not in seen_fields:
            seen_fields.add(field_name)
            regular_fields.append(field_name)

    return regular_fields, mds_layout


def build_object_template_header(type_instance: CmdbType) -> list[str]:
    """
    Builds the full header row of a CmdbType's object-import template

    The order mirrors an object CSV export of that type: the two identity columns, then the regular
    fields in section order, then the multi-data-section fields grouped per section

    Args:
        type_instance (CmdbType): The CmdbType to build the template header for

    Returns:
        list[str]: The header row, one self-describing column per entry
    """
    header: list[str] = [
        build_template_column(TEMPLATE_PUBLIC_ID_LABEL, CmdbObjectKey.PUBLIC_ID.value),
        build_template_column(TEMPLATE_ACTIVE_LABEL, CmdbObjectKey.ACTIVE.value),
    ]

    field_labels: dict[str, str] = build_field_label_map(type_instance)
    regular_fields, mds_layout = collect_template_field_layout(type_instance)

    header.extend(
        build_template_column(field_labels.get(name, name), name) for name in regular_fields
    )

    for section_label, field_names in mds_layout:
        header.extend(
            build_template_column(field_labels.get(name, name), name, section_label) for name in field_names
        )

    return header


def type_has_template_fields(type_instance: CmdbType) -> bool:
    """
    Reports whether a CmdbType declares any field to build a template from

    A CmdbType without fields cannot be filled in, so the route refuses it instead of handing out a
    template that holds nothing but the two identity columns

    Args:
        type_instance (CmdbType): The CmdbType to check

    Returns:
        bool: True when the type declares at least one field
    """
    fields: list[dict[str, Any]] = type_instance.get_fields() or []

    return any(a_field.get(FieldKey.NAME.value) for a_field in fields)
