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

A person selector among the summary fields holds object ids; the line shows them as the labels of the persons and
groups the reader may see, through the caller's ``PersonLabeller`` (built by ``person_selector``, which reads the
reader's ACL - this module reads nothing). Without a labeller a person value is left out of the line, never written as
ids. The labeller is called once per batch of lines, and only when a line has a person value to show
"""
from logging import Logger, getLogger
from typing import Any, Callable, NamedTuple

from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.person_selector_rules import is_person_selector
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# What a malformed stored object raises while its field values are read: a missing 'fields' or row key, a
# 'fields' that is no list, a row that is no dict
OBJECT_SHAPE_ERRORS: tuple[type[Exception], ...] = (KeyError, TypeError, AttributeError)

# Person selector values in, the text the reader sees of each out (same order; empty text when they see none of it)
PersonLabeller = Callable[[list[Any]], list[str]]

# -------------------------------------------------------------------------------------------------------------------- #

class SummaryLayout(NamedTuple):
    """
    What a CmdbType's summary line is composed of

    Attributes:
        names (list[str]): The summary field names, in declaration order
        person_names (set[str]): Those of them that are person selectors
    """
    names: list[str]
    person_names: set[str]


def summary_layout(target_object_type: CmdbType) -> SummaryLayout:
    """
    A CmdbType's summary fields, read once (``CmdbType.get_summary``) - empty for a type that configures none

    Args:
        target_object_type (CmdbType): The CmdbType

    Returns:
        SummaryLayout: The summary field names in declaration order, and the person selectors among them
    """
    if not target_object_type.has_summaries():
        return SummaryLayout([], set())

    fields: list[dict[str, Any]] = list(target_object_type.get_summary().fields)

    return SummaryLayout(
        [field.get(CmdbObjectFieldKey.NAME.value) for field in fields],
        {field.get(CmdbObjectFieldKey.NAME.value) for field in fields if is_person_selector(field)},
    )


def _has_value(value: Any) -> bool:
    """
    Tells whether a summary field value is shown - None and the empty text are no value

    Args:
        value (Any): A stored field value

    Returns:
        bool: True when the value contributes to the line
    """
    return value is not None and value != ''


def label_person_values(entries: list[tuple[dict[str, Any], set[str]]], labeller: PersonLabeller | None) -> None:
    """
    Replaces the person selector values of many objects' field values by the text the reader sees, in place

    The labeller is called once for all of them, and not at all when none holds a value (nothing, the empty text or an
    empty list). Without a labeller every person value becomes the empty text, so the line leaves it out

    Args:
        entries (list[tuple[dict[str, Any], set[str]]]): Per object, its values by field name
            (``field_values_by_name``) and the names of its person selector summary fields
        labeller (PersonLabeller | None): The reader's labeller, or None

    Raises:
        BaseManagerGetError: When the labeller's reads fail
    """
    places: list[tuple[dict[str, Any], str]] = []

    for values, names in entries:
        for name in sorted(names):
            if _has_value(values.get(name)) and values.get(name) != []:
                places.append((values, name))
            elif name in values:
                values[name] = ''

    if not places:
        return

    texts: list[str] = labeller([values[name] for values, name in places]) if labeller else [''] * len(places)

    for (values, name), text in zip(places, texts, strict=True):
        values[name] = text


def summary_text(default_line: str, names: list[str], values: dict[str, Any]) -> str:
    """
    The summary line from its prefix and the values of the summary fields

    A field without a value contributes nothing - neither text nor a separator

    Args:
        default_line (str): The 'type label + public_id' prefix
        names (list[str]): The summary field names, in declaration order
        values (dict[str, Any]): The object's values by field name, person values already labelled

    Returns:
        str: The line; the prefix alone when no summary field has a value
    """
    emitted: list[str] = [str(values[name]) for name in names if _has_value(values.get(name))]

    if not emitted:
        return default_line

    return f"{default_line} - {' | '.join(emitted)}"


def _default_line(target_object: dict[str, Any], target_object_type: CmdbType, with_type: bool) -> str:
    """
    The 'type label + public_id' prefix of a summary line

    Args:
        target_object (dict[str, Any]): The CmdbObject document
        target_object_type (CmdbType): Its CmdbType
        with_type (bool): If True the type label is included

    Returns:
        str: The prefix
    """
    public_id: Any = target_object.get(CmdbObjectKey.PUBLIC_ID.value)

    return f"{target_object_type.label} #{public_id}" if with_type else f"#{public_id}"


def _read_values(target_object: dict[str, Any], target_object_type: CmdbType) -> dict[str, Any] | None:
    """
    An object's values by field name, None for a malformed stored object (logged at debug level)

    Args:
        target_object (dict[str, Any]): The CmdbObject document
        target_object_type (CmdbType): Its CmdbType

    Returns:
        dict[str, Any] | None: The values, or None when they could not be read
    """
    try:
        return field_values_by_name(target_object)
    except OBJECT_SHAPE_ERRORS as err:
        LOGGER.debug("Failed to build summary line for Object-ID: %s and Type-ID: %s. Error: %s!",
                     target_object.get(CmdbObjectKey.PUBLIC_ID.value), target_object_type.public_id, err)
        return None


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
    labeller: PersonLabeller | None = None,
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

    A person selector summary field shows the labeller's text for its value; without a labeller, or when the
    reader sees none of its persons, it contributes nothing

    Args:
        target_object (dict[str, Any]): The CmdbObject document (as_dict=True shape)
        target_object_type (CmdbType): The CmdbType instance of the object
        with_type (bool): If True the type label is included in the prefix
        labeller (PersonLabeller | None): The reader's person labeller; None leaves person values out

    Raises:
        BaseManagerGetError: When the labeller's reads fail

    Returns:
        str: The composed summary line
    """
    return compose_summary_lines([target_object], {target_object_type.public_id: target_object_type}, with_type,
                                 labeller).get(target_object.get(CmdbObjectKey.PUBLIC_ID.value),
                                               _default_line(target_object, target_object_type, with_type))


def compose_summary_lines(
    object_docs: list[dict[str, Any]],
    types_lookup: dict[int, CmdbType],
    with_type: bool = True,
    labeller: PersonLabeller | None = None,
) -> dict[int, str]:
    """
    Composes the summary lines of many loaded CmdbObjects, resolving each type's summary once

    The person selector values of all lines are labelled in one labeller call (``label_person_values``)

    Args:
        object_docs (list[dict[str, Any]]): The CmdbObject documents
        types_lookup (dict[int, CmdbType]): Their CmdbTypes by public_id
        with_type (bool): If True the type label is included in each prefix
        labeller (PersonLabeller | None): The reader's person labeller; None leaves person values out

    Raises:
        BaseManagerGetError: When the labeller's reads fail

    Returns:
        dict[int, str]: {public_id: summary line}; a document without an integer public_id, or whose type is not
            in the lookup, has no line
    """
    layouts: dict[int, SummaryLayout] = {
        type_id: summary_layout(cmdb_type) for type_id, cmdb_type in types_lookup.items()
    }
    lines: dict[int, str] = {}
    pending: list[tuple[int, str, SummaryLayout, dict[str, Any]]] = []

    for doc in object_docs:
        doc_id: Any = doc.get(CmdbObjectKey.PUBLIC_ID.value)
        doc_type_id: Any = doc.get(CmdbObjectKey.TYPE_ID.value)

        if not isinstance(doc_id, int) or not isinstance(doc_type_id, int) or doc_type_id not in types_lookup:
            continue

        default_line: str = _default_line(doc, types_lookup[doc_type_id], with_type)
        values: dict[str, Any] | None = (
            _read_values(doc, types_lookup[doc_type_id]) if layouts[doc_type_id].names else None
        )

        if values is None:
            lines[doc_id] = default_line
        else:
            pending.append((doc_id, default_line, layouts[doc_type_id], values))

    label_person_values([(values, layout.person_names) for _, _, layout, values in pending], labeller)

    for doc_id, default_line, layout, values in pending:
        lines[doc_id] = summary_text(default_line, layout.names, values)

    return lines
