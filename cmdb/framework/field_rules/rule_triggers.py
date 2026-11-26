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
When a Field Rule runs - pure

A trigger names fields: by name (``changed``), by the audit flag or by a field class (``changed_any``) - read off the
Type's field definitions. It fires when the user's change touches one of them; the rule runs when ``when`` fires and
``unless`` (if any) does not. Only the user's change counts - never what another rule set (no chaining)
"""
from collections.abc import Collection, Iterable, Mapping
from typing import Any

from cmdb.models.access_model import FieldRuleKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.field_rules.field_rule_constants import AUDIT_FLAG, TriggerKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'trigger_fields',
    'triggered',
    'rule_runs',
]


def trigger_fields(trigger: Mapping[str, Any], type_fields: Iterable[Mapping[str, Any]]) -> set[str]:
    """
    The fields a trigger names on a Type

    Args:
        trigger (Mapping[str, Any]): A shape-checked ``when`` / ``unless``
        type_fields (Iterable[Mapping[str, Any]]): The Type's field definitions

    Returns:
        set[str]: The field names
    """
    if TriggerKey.CHANGED.value in trigger:
        return set(trigger[TriggerKey.CHANGED.value])

    any_of: Mapping[str, Any] = trigger.get(TriggerKey.CHANGED_ANY.value) or {}

    if TriggerKey.FLAG.value in any_of:
        return {field[FieldKey.NAME.value] for field in type_fields if field.get(AUDIT_FLAG) is True}

    return {field[FieldKey.NAME.value] for field in type_fields
            if field.get(FieldKey.PROTECTION.value) == any_of.get(TriggerKey.CLASS.value)}


def triggered(trigger: Mapping[str, Any], changed: Collection[str], type_fields: list[Mapping[str, Any]]) -> bool:
    """
    Whether the user's change touches a field the trigger names

    Args:
        trigger (Mapping[str, Any]): A shape-checked ``when`` / ``unless``
        changed (Collection[str]): The field names the user's write changes
        type_fields (list[Mapping[str, Any]]): The Type's field definitions

    Returns:
        bool: True when it fires
    """
    return bool(trigger_fields(trigger, type_fields).intersection(changed))


def rule_runs(rule: Mapping[str, Any], changed: Collection[str], type_fields: list[Mapping[str, Any]]) -> bool:
    """
    Whether a rule runs on a write: ``when`` fires and ``unless`` does not

    Args:
        rule (Mapping[str, Any]): The stored rule
        changed (Collection[str]): The field names the user's write changes
        type_fields (list[Mapping[str, Any]]): The Type's field definitions

    Returns:
        bool: True when it runs
    """
    unless: Any = rule.get(FieldRuleKey.UNLESS.value)

    return triggered(rule[FieldRuleKey.WHEN.value], changed, type_fields) and not (
        unless and triggered(unless, changed, type_fields))
