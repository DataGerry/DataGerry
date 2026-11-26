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
A field's class and audit flag on a type or template write (phase 12, D4) - pure, no reads

Both are set through the Field Protection routes only. A type or template write may send them back only as they are
stored: a new field (and every field of a new type or template) carries none, an existing field keeps the stored ones.
What is stored is then the stored value whatever the payload said - a field it leaves the keys out of keeps them too.
The fields a type copies from a global template are the template's (the reconciliation wrote them) and are not judged
"""
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PROTECTION_KEYS',
    'FIELD_PROTECTION_MANAGED_MESSAGE',
    'protection_value',
    'template_owned_field_names',
    'protection_problems',
]

# The keys only the Field Protection routes write
PROTECTION_KEYS: tuple[str, ...] = (FieldKey.PROTECTION.value, FieldKey.AUDIT_RELEVANT.value)
FIELD_PROTECTION_MANAGED_MESSAGE: str = (
    "The field class and the audit flag of the field '{field}' are managed under Access & Data Rules - Field "
    "Protection: send them as stored, or leave them out!"
)


def protection_value(key: str, value: Any) -> Any:
    """
    The meaning of a stored or sent class / flag value - an empty class is none, a flag is on only when true

    Args:
        key (str): ``protection`` or ``audit_relevant``
        value (Any): The value

    Returns:
        Any: The class name or None; True or False
    """
    if key == FieldKey.AUDIT_RELEVANT.value:
        return value is True

    return value if isinstance(value, str) and value else None


def template_owned_field_names(type_data: Mapping[str, Any]) -> set[str]:
    """
    The fields a type carries from its global templates - the fields of the sections named after a claimed template

    Args:
        type_data (Mapping[str, Any]): The type document (after the template reconciliation)

    Returns:
        set[str]: Those field names
    """
    claimed: set[Any] = set(type_data.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value) or [])
    owned: set[str] = set()

    for section in (type_data.get(TypeSchemaKey.RENDER_META.value) or {}).get(TypeSchemaKey.SECTIONS.value) or []:
        if isinstance(section, dict) and section.get(SectionKey.NAME.value) in claimed:
            owned.update(name for name in section.get(SectionKey.FIELDS.value) or [] if isinstance(name, str))

    return owned


def protection_problems(fields: Iterable[Any], stored_fields: Iterable[Any] = (),
                        owned: Collection[str] = ()) -> list[str]:
    """
    Judges the class and flag a write sends, then puts the stored ones in - the field entries are changed in place

    Args:
        fields (Iterable[Any]): The field definitions as sent (after the template reconciliation)
        stored_fields (Iterable[Any]): The stored field definitions; none for a create
        owned (Collection[str]): The fields a global template owns - not judged, not changed

    Returns:
        list[str]: One problem per field sending another value than stored; empty when none does
    """
    stored: dict[str, Mapping[str, Any]] = {field[FieldKey.NAME.value]: field for field in stored_fields
                                            if isinstance(field, dict) and FieldKey.NAME.value in field}
    problems: list[str] = []

    for field in fields:
        if not isinstance(field, dict) or field.get(FieldKey.NAME.value) in owned:
            continue

        name: Any = field.get(FieldKey.NAME.value)
        kept: Mapping[str, Any] = stored.get(name, {})

        if any(key in field and protection_value(key, field[key]) != protection_value(key, kept.get(key))
               for key in PROTECTION_KEYS):
            problems.append(FIELD_PROTECTION_MANAGED_MESSAGE.format(field=name))

        for key in PROTECTION_KEYS:
            field.pop(key, None)

            if key in kept:
                field[key] = kept[key]

    return problems
