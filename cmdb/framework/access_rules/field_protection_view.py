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
The Field Protection list (phase 12, D5) - pure, built from the Types and global section templates read

Every field appears once, where it is defined: a global template's field under the template, with the Types that carry
the template as its reach; a Type's own field under the Type (a field a global template owns is the template's). Each
row names its class, audit flag, required and pattern. For a user group, each row adds per Type of its reach what the
group may do with the field - ``write`` / ``read`` / ``system`` - and whether it is required for the group: what the
group's assignments may write in some create or edit (a conditional assignment counts)
"""
from collections.abc import Iterable, Mapping
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.models.access_model import SYSTEM_FIELD_CLASS, ScopeOperation
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.framework.access_engine import AccessGrants, FieldAccess
from cmdb.framework.access_rules.field_protection_rules import protection_value, template_owned_field_names
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FieldSource',
    'FieldProtectionKey',
    'field_rows',
    'group_field_access',
]

_WRITING: tuple[ScopeOperation, ...] = (ScopeOperation.CREATE, ScopeOperation.EDIT)


class FieldSource(BaseStrEnum):
    """Where a field is defined"""
    TYPE = 'type'
    TEMPLATE = 'template'


class FieldProtectionKey(BaseStrEnum):
    """The keys of one Field Protection row"""
    SOURCE = 'source'
    SOURCE_ID = 'source_id'
    SOURCE_NAME = 'source_name'
    NAME = 'name'
    LABEL = 'label'
    KIND = 'kind'
    PROTECTION = 'protection'
    AUDIT_RELEVANT = 'audit_relevant'
    REQUIRED = 'required'
    REGEX = 'regex'
    REACH = 'reach'
    GROUP = 'group'
    TYPE_ID = 'type_id'
    ACCESS = 'access'


def _row(source: FieldSource, source_id: Any, source_name: Any, field: Mapping[str, Any],
         reach: list[int]) -> dict[str, Any]:
    """
    One row

    Args:
        source (FieldSource): Type or template
        source_id (Any): Its public_id
        source_name (Any): Its name
        field (Mapping[str, Any]): The field definition
        reach (list[int]): The Types the field is on

    Returns:
        dict[str, Any]: The row
    """
    return {
        FieldProtectionKey.SOURCE.value: source.value,
        FieldProtectionKey.SOURCE_ID.value: source_id,
        FieldProtectionKey.SOURCE_NAME.value: source_name,
        FieldProtectionKey.NAME.value: field.get(FieldKey.NAME.value),
        FieldProtectionKey.LABEL.value: field.get(FieldKey.LABEL.value),
        FieldProtectionKey.KIND.value: field.get(FieldKey.TYPE.value),
        FieldProtectionKey.PROTECTION.value: protection_value(FieldKey.PROTECTION.value,
                                                              field.get(FieldKey.PROTECTION.value)),
        FieldProtectionKey.AUDIT_RELEVANT.value: protection_value(FieldKey.AUDIT_RELEVANT.value,
                                                                  field.get(FieldKey.AUDIT_RELEVANT.value)),
        FieldProtectionKey.REQUIRED.value: field.get(FieldKey.REQUIRED.value) is True,
        FieldProtectionKey.REGEX.value: field.get(FieldKey.REGEX.value) or None,
        FieldProtectionKey.REACH.value: reach,
    }


def field_rows(types: Iterable[Mapping[str, Any]], templates: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Every field once, where it is defined - the templates' first, then the Types' own, each in definition order

    Args:
        types (Iterable[Mapping[str, Any]]): The Types (public_id, name, fields, global_template_ids, render_meta)
        templates (Iterable[Mapping[str, Any]]): The global section templates (public_id, name, fields)

    Returns:
        list[dict[str, Any]]: The rows
    """
    type_list: list[Mapping[str, Any]] = list(types)
    rows: list[dict[str, Any]] = []

    for template in templates:
        name: Any = template.get(SectionTemplateKey.NAME.value)
        reach: list[int] = sorted(document[TypeSchemaKey.PUBLIC_ID.value] for document in type_list
                                  if name in (document.get(TypeSchemaKey.GLOBAL_TEMPLATE_IDS.value) or []))
        rows.extend(_row(FieldSource.TEMPLATE, template.get(SectionTemplateKey.PUBLIC_ID.value), name, field, reach)
                    for field in template.get(SectionTemplateKey.FIELDS.value) or [] if isinstance(field, dict))

    for document in type_list:
        owned: set[str] = template_owned_field_names(document)
        type_id: Any = document[TypeSchemaKey.PUBLIC_ID.value]
        rows.extend(_row(FieldSource.TYPE, type_id, document.get(TypeSchemaKey.NAME.value), field, [type_id])
                    for field in document.get(TypeSchemaKey.FIELDS.value) or []
                    if isinstance(field, dict) and field.get(FieldKey.NAME.value) not in owned)

    return rows


def group_field_access(grants: AccessGrants, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    What a user group may do with one field on each Type of its reach

    Args:
        grants (AccessGrants): The group's grants (built for the group alone)
        row (Mapping[str, Any]): The field's row

    Returns:
        list[dict[str, Any]]: ``{type_id, access, required}`` per Type of the reach
    """
    field_class: Any = row.get(FieldProtectionKey.PROTECTION.value)
    required: bool = row.get(FieldProtectionKey.REQUIRED.value) is True
    answer: list[dict[str, Any]] = []

    for type_id in row.get(FieldProtectionKey.REACH.value) or []:
        if field_class == SYSTEM_FIELD_CLASS:
            access: str = FieldAccess.SYSTEM.value
        elif not grants.is_restricted(type_id) or _writes(grants, type_id, field_class):
            access = FieldAccess.WRITE.value
        else:
            access = FieldAccess.READ.value

        answer.append({FieldProtectionKey.TYPE_ID.value: type_id, FieldProtectionKey.ACCESS.value: access,
                       FieldProtectionKey.REQUIRED.value: required and access == FieldAccess.WRITE.value})

    return answer


def _writes(grants: AccessGrants, type_id: int, field_class: Any) -> bool:
    """
    Whether one of the group's assignments writes a field of the class on the Type in some create or edit

    Args:
        grants (AccessGrants): The group's grants
        type_id (int): The Type
        field_class (Any): The field's class; None for a regular field

    Returns:
        bool: True when a role granting a writing operation on the Type writes it
    """
    return any(entry.grants(operation, type_id)
               and (entry.write_regular_fields if field_class is None else field_class in entry.field_classes)
               for entry in grants.entries for operation in _WRITING)
