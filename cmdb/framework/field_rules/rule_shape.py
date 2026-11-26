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
The shape of a Field Rule's ``when``, ``unless`` and ``set`` - pure; the schema has already held
the document's keys to their types
"""
import re
from typing import Any

from cmdb.models.access_model import FIELD_CLASS_NAME_PATTERN, FieldRuleKey
from cmdb.framework.field_rules.field_rule_constants import AUDIT_FLAG, FieldRuleMessage, TriggerKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'trigger_problems',
    'rule_shape_problems',
]

_CLASS_NAME: re.Pattern[str] = re.compile(FIELD_CLASS_NAME_PATTERN)


def trigger_problems(key: str, trigger: Any) -> list[str]:
    """
    Judges one ``when`` / ``unless``

    Args:
        key (str): ``when`` or ``unless``, for the message
        trigger (Any): The value

    Returns:
        list[str]: The problem, or none
    """
    if isinstance(trigger, dict) and len(trigger) == 1:
        if TriggerKey.CHANGED.value in trigger:
            names: Any = trigger[TriggerKey.CHANGED.value]

            if isinstance(names, list) and names and all(isinstance(name, str) and name.strip() for name in names):
                return []
        elif _is_changed_any(trigger.get(TriggerKey.CHANGED_ANY.value)):
            return []

    return [FieldRuleMessage.BAD_TRIGGER.value.format(key=key)]


def _is_changed_any(any_of: Any) -> bool:
    """
    Whether a ``changed_any`` value is ``{flag: audit_relevant}`` or ``{class: <class name>}``

    Args:
        any_of (Any): The value

    Returns:
        bool: True for one of the two
    """
    if not isinstance(any_of, dict) or len(any_of) != 1:
        return False

    if any_of.get(TriggerKey.FLAG.value) == AUDIT_FLAG:
        return True

    name: Any = any_of.get(TriggerKey.CLASS.value)

    return isinstance(name, str) and _CLASS_NAME.match(name) is not None


def rule_shape_problems(rule: dict[str, Any]) -> list[str]:
    """
    Judges a rule's trigger, exception, set values and Types for their shape - every problem

    Args:
        rule (dict[str, Any]): The rule as it would be stored

    Returns:
        list[str]: The problems
    """
    problems: list[str] = trigger_problems(FieldRuleKey.WHEN.value, rule.get(FieldRuleKey.WHEN.value))

    if rule.get(FieldRuleKey.UNLESS.value) is not None:
        problems += trigger_problems(FieldRuleKey.UNLESS.value, rule[FieldRuleKey.UNLESS.value])

    values: Any = rule.get(FieldRuleKey.SET.value)

    if not isinstance(values, dict) or not values or not all(isinstance(name, str) and name.strip()
                                                             for name in values):
        problems.append(FieldRuleMessage.BAD_SET.value)

    if rule.get(FieldRuleKey.TYPES.value) == []:
        problems.append(FieldRuleMessage.NO_TYPES.value)

    return problems
