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
Filling a new CmdbObject's empty fields from their declared defaults

**When an object is created, a field it leaves empty takes the default its CmdbType declares** - whether
or not the client sent that default. "Empty" is absent, `None` or `''` (an empty list for a multi-value
kind); `0` and `False` are values the client chose. The rule applies on **create only** - the REST insert
and the object importer. An update keeps what the client sent, so a user can still clear a field that has
a default.

Two kinds of default are never filled:

  - **reference-like kinds** (`ref`, `ref-section-field`, `location`): their "default" would be an object
    id, which the importer clears on import and a client picks deliberately
  - **a default that breaks its own field's value rules** (the text / textarea cap, the field's `regex`).
    It is skipped with a warning, so a create that leaves the field empty can never fail over a value the
    client did not send. The CmdbType and section-template writes refuse such defaults; this covers the
    ones stored before they did

The fill runs before the required-field rule, so a required field with a usable default is satisfied by
it, and before the value rules, which then judge the filled value like any other. It covers the
top-level `fields` list and every row of the multi-data sections the object carries
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.object_field_value_rules import (
    FieldValueRule,
    PatternBudget,
    build_field_value_rules,
    find_default_errors,
    has_no_value,
)
from cmdb.framework.object_required_fields import mds_section_field_names
from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__ = [
    'DEFAULT_EXCLUDED_KINDS',
    'fill_entries_from_defaults',
    'fill_object_defaults',
    'usable_default',
]

# Field kinds whose declared default is never filled into a new object (see the module docstring)
DEFAULT_EXCLUDED_KINDS: frozenset[str] = frozenset({
    FieldType.REFERENCE.value,
    FieldType.REF_SECTION.value,
    FieldType.LOCATION.value,
})


def usable_default(field: dict[str, Any], rule: FieldValueRule | None, budget: PatternBudget | None = None) -> Any:
    """
    Answers the default a new object's empty field may be filled with, or None when there is none

    A default whose pattern check runs out of time is not used either - it could not be shown to pass

    Args:
        field (dict[str, Any]): The field definition
        rule (FieldValueRule | None): The field's value rule (see ``build_field_value_rules``), if it has one
        budget (PatternBudget | None): The object write's pattern time budget; None starts one for this field

    Returns:
        Any: The declared default, or None when the field declares none, is of an excluded kind, or its
            default breaks the field's own value rules (logged as a warning)
    """
    default: Any = field.get(FieldKey.VALUE.value)

    if has_no_value(default) or field.get(FieldKey.TYPE.value) in DEFAULT_EXCLUDED_KINDS:
        return None

    if rule is not None:
        errors: list[str] = find_default_errors(field.get(FieldKey.NAME.value), default, rule, budget)

        if errors:
            LOGGER.warning("[usable_default] Not filling an unusable default: %s", '; '.join(errors))
            return None

    return default


def fill_entries_from_defaults(
        entries: list[dict[str, Any]],
        defaults: dict[str, Any],
        field_types: dict[str, Any] | None = None,
        append_without_default: bool = False) -> None:
    """
    Fills one list of field entries - an object's ``fields`` or one MDS row's ``data`` - in place

    An entry that is present and empty takes its field's default; a field the list does not carry at all
    is appended with it. A field without a usable default is left as it is - and appended with ``None``
    only when ``append_without_default`` asks for complete entries (the importer does)

    Args:
        entries (list[dict[str, Any]]): The field entries to fill (mutated in place)
        defaults (dict[str, Any]): ``{field name: usable default or None}`` for every field of this list
        field_types (dict[str, Any] | None): ``{field name: kind}``, stamped as ``type`` on an appended
            entry; None appends no ``type`` key
        append_without_default (bool): Whether a field with no usable default is appended with ``None``
    """
    by_name: dict[Any, dict[str, Any]] = {entry.get(CmdbObjectFieldKey.NAME.value): entry for entry in entries}

    for name, default in defaults.items():
        entry: dict[str, Any] | None = by_name.get(name)

        if entry is not None:
            if default is not None and has_no_value(entry.get(CmdbObjectFieldKey.VALUE.value)):
                entry[CmdbObjectFieldKey.VALUE.value] = default
            continue

        if default is None and not append_without_default:
            continue

        appended: dict[str, Any] = {CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: default}

        if field_types and name in field_types:
            appended[CmdbObjectFieldKey.TYPE.value] = field_types[name]

        entries.append(appended)


def fill_object_defaults(object_data: dict[str, Any], type_instance: CmdbType) -> None:
    """
    Fills a new CmdbObject's empty fields from its CmdbType's usable defaults, in place

    The top-level ``fields`` list gets the defaults of the fields no multi-data section holds; each row of
    every multi-data section the object carries gets its section's defaults. Rows are never created

    Args:
        object_data (dict[str, Any]): The candidate CmdbObject document (mutated in place)
        type_instance (CmdbType): The object's CmdbType
    """
    type_fields: list[dict[str, Any]] = type_instance.get_fields() or []
    rules: dict[str, FieldValueRule] = build_field_value_rules(type_fields)
    budget: PatternBudget = PatternBudget()
    usable: dict[Any, Any] = {
        field.get(FieldKey.NAME.value): usable_default(field, rules.get(field.get(FieldKey.NAME.value)), budget)
        for field in type_fields
    }
    field_types: dict[Any, Any] = {
        field.get(FieldKey.NAME.value): field.get(FieldKey.TYPE.value) for field in type_fields
    }
    section_fields: dict[str, list[str]] = mds_section_field_names(type_instance)
    mds_names: set[str] = set().union(*(set(names) for names in section_fields.values())) if section_fields else set()

    fill_entries_from_defaults(
        object_data.setdefault(CmdbObjectKey.FIELDS.value, []),
        {name: default for name, default in usable.items() if name not in mds_names},
        field_types,
    )

    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        names: list[str] = section_fields.get(section.get(CmdbObjectMdsKey.SECTION_ID.value), [])

        if not names:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            fill_entries_from_defaults(
                row.setdefault(CmdbObjectMdsRowKey.DATA.value, []),
                {name: usable.get(name) for name in names},
                field_types,
            )
