# DATAGERRY - OpenSource Enterprise CMDB
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
The write-side rule for ``CmdbType.ci_explorer_label``

``ci_explorer_label`` does not hold a label. It holds the **name of one of the Type's own fields**,
and the CI Explorer shows that field's value on every node of the Type - so a "Server" Type
nominating ``hostname`` draws nodes reading ``db-01``, ``web-02``, … The read side of that is
``nodes.resolve_title``; this module is the write side, so the nomination cannot point at something
that will never resolve.

Two ways a nomination is unusable, and both are refused on write:

* **it names no field of the Type at all** - a typo, a display label sent instead of a field name, or
  a field that has since been removed. Every node of the Type then renders "Label not selected",
  which is indistinguishable from never having chosen one.
* **it names a field of a multi-data-section.** An MDS field does have an entry in a CmdbObject's flat
  ``fields`` list, so ``resolve_title`` WOULD find it - but the per-row data lives in
  ``multi_data_sections``, and that flat entry carries none of it. The nodes would show a blank or a
  stale single value rather than the rows. The frontend's picker excludes MDS fields for exactly this
  reason, and the backend enforces the same rule.

A field the Type declares but assigns to no section IS accepted. The frontend only offers fields it
can show in a section, but an unassigned field still resolves on the object, and refusing it here
would mean refusing a Type shape the write routes otherwise allow
"""
from typing import Any

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

# Refusal when the nomination names no field of the Type. Worded for the API client, because the
# frontend picks from a list and can only send this by sending something it did not pick
LABEL_FIELD_UNKNOWN_MESSAGE: str = (
    "Invalid 'ci_explorer_label': {value} is not a field of this Type. It is the NAME of the field "
    'whose value the CI Explorer shows on every node of the Type, not a label to display. '
    'Allowed: {allowed}'
)

# Refusal when the nomination names a multi-data-section field
LABEL_FIELD_MDS_MESSAGE: str = (
    "Invalid 'ci_explorer_label': {value} belongs to a multi-data-section, whose values are stored "
    'per row - a node can only show one. Nominate a field of an ordinary section instead. '
    'Allowed: {allowed}'
)

# How the allowed field names are listed in both messages when the Type has none to offer
NO_SELECTABLE_FIELDS: str = '(this Type has no selectable field)'


def declared_field_names(type_data: dict[str, Any]) -> list[str]:
    """
    Lists the names of every field a CmdbType declares, in declaration order

    Reads the flat ``fields`` list, which is where a Type declares every field it has - its sections
    only reference them by name

    Args:
        type_data (dict[str, Any]): A CmdbType document or write payload

    Returns:
        list[str]: The declared field names
    """
    fields: Any = type_data.get(TypeSchemaKey.FIELDS.value) or []

    if not isinstance(fields, list):
        return []

    return [
        field[FieldKey.NAME.value] for field in fields
        if isinstance(field, dict) and isinstance(field.get(FieldKey.NAME.value), str)
    ]


def mds_field_names(type_data: dict[str, Any]) -> set[str]:
    """
    Collects the names of every field assigned to a multi-data-section of a CmdbType

    A field is MDS by where its NAME is listed, not by anything on the field itself: the section
    entry carries the kind, and the field is referenced from it by name

    Args:
        type_data (dict[str, Any]): A CmdbType document or write payload

    Returns:
        set[str]: The names referenced from a multi-data-section
    """
    render_meta: Any = type_data.get(TypeSchemaKey.RENDER_META.value) or {}
    sections: Any = render_meta.get(TypeSchemaKey.SECTIONS.value) if isinstance(render_meta, dict) else None

    if not isinstance(sections, list):
        return set()

    names: set[str] = set()

    for section in sections:
        if not isinstance(section, dict) or section.get(SectionKey.TYPE.value) != SectionType.MDS_SECTION:
            continue

        for field_name in section.get(SectionKey.FIELDS.value) or []:
            # A section references its fields by name, but an older document may carry the whole
            # field dict - both spellings are read the same way everywhere else
            if isinstance(field_name, dict):
                field_name = field_name.get(FieldKey.NAME.value)

            if isinstance(field_name, str):
                names.add(field_name)

    return names


def selectable_label_fields(type_data: dict[str, Any]) -> list[str]:
    """
    Lists the field names a CmdbType may nominate as its CI Explorer label

    Every declared field except the ones belonging to a multi-data-section. This is what the refusal
    messages offer the caller, and what a frontend picker would show

    Args:
        type_data (dict[str, Any]): A CmdbType document or write payload

    Returns:
        list[str]: The selectable field names, in declaration order
    """
    excluded: set[str] = mds_field_names(type_data)

    return [name for name in declared_field_names(type_data) if name not in excluded]


def is_label_field_unset(label_field: Any) -> bool:
    """
    Reports whether a nomination means "no field chosen"

    ``None`` is the stored form, but the frontend sends an empty string when it clears the pick, and
    ``resolve_title`` treats both as "nothing nominated" - so both have to be accepted here

    Args:
        label_field (Any): The 'ci_explorer_label' value as it came off the request

    Returns:
        bool: True when nothing is nominated
    """
    return label_field is None or label_field == ''


def label_field_error(type_data: dict[str, Any], label_field: Any) -> str | None:
    """
    Reports why a CI Explorer label nomination is unusable, if it is

    The rule itself, shared by every write path: the two type routes, the CI Explorer route that sets
    it on its own, and the type import (which repairs instead of reporting). Pure - it judges the
    nomination against the Type data it is handed, so an update judges it against the payload being
    written rather than against the stored document

    Args:
        type_data (dict[str, Any]): The CmdbType document or write payload the nomination belongs to
        label_field (Any): The nominated field name

    Returns:
        str | None: The refusal message, or None when the nomination is usable (which includes
            nominating nothing at all)
    """
    if is_label_field_unset(label_field):
        return None

    allowed: list[str] = selectable_label_fields(type_data)
    listed: str = ', '.join(allowed) if allowed else NO_SELECTABLE_FIELDS

    if isinstance(label_field, str) and label_field in mds_field_names(type_data):
        return LABEL_FIELD_MDS_MESSAGE.format(value=repr(label_field), allowed=listed)

    if not isinstance(label_field, str) or label_field not in allowed:
        return LABEL_FIELD_UNKNOWN_MESSAGE.format(value=repr(label_field), allowed=listed)

    return None
