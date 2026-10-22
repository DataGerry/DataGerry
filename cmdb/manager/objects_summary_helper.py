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
The one-line summary a CmdbObject is shown as

Every list, picker and reference in the product identifies an object by this line, so its shape is a
user-facing contract: `Type label #public_id - field | field | field`, with the configured summary
fields in declaration order.

**Pure composition over already-loaded data**, which is why it lives beside the manager rather than in
it: `ObjectsManager.get_summary_lines_lookup` reads many objects and their types in two bulk queries,
the IPAM assignable-objects listing reads its own page, and both compose the line here - so no two
callers can drift into producing different text for the same object.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.type_model.cmdb_type import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What a malformed stored object raises while its field values are read: a missing 'fields' or row key, a
# 'fields' that is no list, a row that is no dict
OBJECT_SHAPE_ERRORS: tuple[type[Exception], ...] = (KeyError, TypeError, AttributeError)

# -------------------------------------------------------------------------------------------------------------------- #

def summary_field_names(target_object_type: CmdbType) -> list[str]:
    """
    The names of a CmdbType's summary fields, in declaration order

    Resolved once per type, so composing the lines of many objects of one type reads the type's summary once.
    A summary name whose field is gone is skipped (``CmdbType.get_summary``)

    Args:
        target_object_type (CmdbType): The CmdbType

    Returns:
        list[str]: The summary field names, empty when the type configures none
    """
    if not target_object_type.has_summaries():
        return []

    return [field.get(CmdbObjectFieldKey.NAME.value) for field in target_object_type.get_summary().fields]


def field_values_by_name(target_object: dict[str, Any]) -> dict[str, Any]:
    """
    An object's field values keyed by field name; the first row of a name wins, a row without a value holds None

    Args:
        target_object (dict[str, Any]): The CmdbObject document

    Raises:
        KeyError: If the document has no 'fields', or a row lacks its name
        TypeError: If 'fields' is not iterable or a row is not subscriptable
        AttributeError: If a row has no mapping interface

    Returns:
        dict[str, Any]: {field name: value}
    """
    values: dict[str, Any] = {}

    for field in target_object[CmdbObjectKey.FIELDS.value]:
        values.setdefault(field[CmdbObjectFieldKey.NAME.value], field.get(CmdbObjectFieldKey.VALUE.value))

    return values


def compose_summary_line(
    target_object: dict[str, Any],
    target_object_type: CmdbType,
    with_type: bool = True,
    summary_names: list[str] | None = None,
) -> str:
    """
    Composes the summary line for a CmdbObject that has already been loaded

    Pure composition over already-loaded data: the object as a dict and its CmdbType
    instance. The 'type label + public_id' prefix is built first, then the configured
    summary fields are appended in declaration order (separator '-' before the first
    field, '|' between fields). If the stored object is malformed (``OBJECT_SHAPE_ERRORS``)
    the helper falls back to the default prefix line and logs at debug level - one broken
    document must not block a whole listing. A programming error is not caught

    A summary field the object has no value for contributes NOTHING - neither text nor a
    separator. Interpolating it would put the literal word 'None' in front of a user (an object
    whose summary field is unset used to read '#264 - None'), and emitting the separator alone
    would leave a line trailing off as '#264 - '. Only a genuinely absent value is skipped:
    `0`, `False` and other falsy-but-present values are real data and are rendered. The
    separator therefore tracks the first field actually EMITTED, not the first one configured,
    so an unset first field does not push a stray '|' to the front of the line

    Args:
        target_object (dict[str, Any]): The CmdbObject document (as_dict=True shape)
        target_object_type (CmdbType): The CmdbType instance of the object
        with_type (bool): If True the type label is included in the prefix
        summary_names (list[str] | None): The type's summary field names when the caller resolved them once
            for many objects (``summary_field_names``); None resolves them here

    Returns:
        str: The composed summary line
    """
    public_id: Any = target_object.get(CmdbObjectKey.PUBLIC_ID.value)
    default_line: str = f"{target_object_type.label} #{public_id}" if with_type else f"#{public_id}"
    names: list[str] = summary_field_names(target_object_type) if summary_names is None else summary_names

    if not names:
        return default_line

    try:
        values: dict[str, Any] = field_values_by_name(target_object)
    except OBJECT_SHAPE_ERRORS as err:
        LOGGER.debug("Failed to build summary line for Object-ID: %s and Type-ID: %s. Error: %s!",
                     public_id, target_object_type.public_id, err)
        return default_line

    emitted: list[str] = [
        str(values[name]) for name in names
        if values.get(name) is not None and values.get(name) != ''
    ]

    if not emitted:
        return default_line

    return f"{default_line} - {' | '.join(emitted)}"


def compose_summary_lines(
    object_docs: list[dict[str, Any]],
    types_lookup: dict[int, CmdbType],
    with_type: bool = True,
) -> dict[int, str]:
    """
    Composes the summary lines of many loaded CmdbObjects, resolving each type's summary once

    Args:
        object_docs (list[dict[str, Any]]): The CmdbObject documents
        types_lookup (dict[int, CmdbType]): Their CmdbTypes by public_id
        with_type (bool): If True the type label is included in each prefix

    Returns:
        dict[int, str]: {public_id: summary line}; a document without an integer public_id, or whose type is not
            in the lookup, has no line
    """
    names_by_type: dict[int, list[str]] = {
        type_id: summary_field_names(cmdb_type) for type_id, cmdb_type in types_lookup.items()
    }
    lines: dict[int, str] = {}

    for doc in object_docs:
        doc_id: Any = doc.get(CmdbObjectKey.PUBLIC_ID.value)
        doc_type_id: Any = doc.get(CmdbObjectKey.TYPE_ID.value)

        if not isinstance(doc_id, int) or not isinstance(doc_type_id, int) or doc_type_id not in types_lookup:
            continue

        lines[doc_id] = compose_summary_line(
            doc, types_lookup[doc_type_id], with_type=with_type, summary_names=names_by_type[doc_type_id],
        )

    return lines
