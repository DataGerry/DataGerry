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
What a Field Rule reaches against a holder of grants - pure

* **The editor's reach:** a rule writes as the server, so its editor may only make it set fields the editor may
  write on each of its Types - a ``system`` field excepted (only rules write those). The administrators are exempt;
  the caller leaves them out.
* **A group's rules:** the rules a user group's own changes can trigger - one of the rule's Types on which the
  group may write a field the ``when`` names
"""
from collections.abc import Mapping
from typing import Any

from cmdb.models.access_model import SYSTEM_FIELD_CLASS, FieldRuleKey
from cmdb.models.access_model.scope_operation_enum import ScopeOperation
from cmdb.models.type_model import FieldKey, TypeSchemaKey
from cmdb.framework.access_engine.access_grants import AccessGrants
from cmdb.framework.access_engine.access_decision import refused_fields
from cmdb.framework.access_engine.field_class_lookup import classes_of_fields
from cmdb.framework.field_rules.field_rule_constants import FieldRuleMessage
from cmdb.framework.field_rules.rule_triggers import trigger_fields
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'reach_problems',
    'group_may_trigger',
]


def reach_problems(grants: AccessGrants, rule: Mapping[str, Any], type_documents: list[dict[str, Any]]) -> list[str]:
    """
    The fields a rule would set that its editor may not write - per Type

    Args:
        grants (AccessGrants): The editor's grants
        rule (Mapping[str, Any]): The rule as it would be stored
        type_documents (list[dict[str, Any]]): Its Types' documents (``public_id``, ``fields``)

    Returns:
        list[str]: A problem per Type with a field beyond the editor's reach
    """
    problems: list[str] = []
    names: list[str] = sorted(rule.get(FieldRuleKey.SET.value) or {})

    for document in type_documents:
        fields: Any = document.get(TypeSchemaKey.FIELDS.value) or []
        carried: set[str] = {field.get(FieldKey.NAME.value) for field in fields if isinstance(field, dict)}
        classes: dict[str, str] = classes_of_fields(fields)
        judged: list[str] = [name for name in names if name in carried and classes.get(name) != SYSTEM_FIELD_CLASS]
        type_id: Any = document.get(TypeSchemaKey.PUBLIC_ID.value)
        refused: tuple[str, ...] = refused_fields(grants, ScopeOperation.EDIT, type_id, judged,
                                                  field_classes=classes)

        if refused:
            problems.append(FieldRuleMessage.BEYOND_REACH.value.format(fields=list(refused), type_id=type_id))

    return problems


def group_may_trigger(grants: AccessGrants, rule: Mapping[str, Any], type_documents: list[dict[str, Any]]) -> bool:
    """
    Whether a holder of grants can trigger a rule with its own changes

    Args:
        grants (AccessGrants): The group's grants
        rule (Mapping[str, Any]): A stored rule
        type_documents (list[dict[str, Any]]): The rule's Types' documents (``public_id``, ``fields``)

    Returns:
        bool: True when on one of the Types the holder may write a field the ``when`` names
    """
    when: Mapping[str, Any] = rule.get(FieldRuleKey.WHEN.value) or {}

    for document in type_documents:
        fields: Any = document.get(TypeSchemaKey.FIELDS.value) or []
        named: list[str] = sorted(trigger_fields(when, [field for field in fields if isinstance(field, dict)]))
        classes: dict[str, str] = classes_of_fields(fields)
        type_id: Any = document.get(TypeSchemaKey.PUBLIC_ID.value)

        if named and len(refused_fields(grants, ScopeOperation.EDIT, type_id, named,
                                        field_classes=classes)) < len(named):
            return True

    return False
