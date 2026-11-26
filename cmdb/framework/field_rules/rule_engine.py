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
Applying the Field Rules to one object write - pure

The user's change is fixed first (the fields the write changes against the stored object; on a create every filled
field). Then each rule covering the object's Type runs once, in ``public_id`` order, when its trigger fires on that
change - never on what another rule set (no chaining). It writes its values as the server: no field class is judged,
but every value is held to its field's rules (pattern, caps, a required field never emptied) - a value they refuse
leaves the write refused, naming the rule. What a rule changed is recorded for the object log
"""
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cmdb.models.access_model import ALL_TYPES, FieldRuleKey
from cmdb.models.object_model import CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.access_engine.object_field_changes import changed_field_names
from cmdb.framework.object_field_value_rules import (
    FieldValueRule,
    PatternBudget,
    build_field_value_rules,
    find_value_errors,
    has_no_value,
)
from cmdb.framework.field_rules.field_rule_constants import FieldRuleMessage, RuleChangeKey
from cmdb.framework.field_rules.rule_triggers import rule_runs
from cmdb.framework.field_rules.rule_values import field_kind, resolve_rule_value
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RuleApplication',
    'rules_on_type',
    'apply_rules',
]


@dataclass
class RuleApplication:
    """
    What the rules did to one write

    Attributes:
        changes (list[dict[str, Any]]): ``{rule_id, rule_name, field, before, after}`` per value a rule changed
        problems (list[str]): Why the write cannot be completed - empty when it can
    """
    changes: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def rules_on_type(rules: Iterable[Mapping[str, Any]], type_id: Any) -> list[Mapping[str, Any]]:
    """
    The rules covering a Type, in the order they run

    Args:
        rules (Iterable[Mapping[str, Any]]): Active rules
        type_id (Any): The Type

    Returns:
        list[Mapping[str, Any]]: The rules naming every Type or this one, ascending by public_id
    """
    return sorted((rule for rule in rules if rule.get(FieldRuleKey.TYPES.value) == ALL_TYPES
                   or type_id in (rule.get(FieldRuleKey.TYPES.value) or [])),
                  key=lambda rule: rule[FieldRuleKey.PUBLIC_ID.value])


def apply_rules(rules: Iterable[Mapping[str, Any]], before: Mapping[str, Any] | None, after: dict[str, Any],
                type_fields: list[dict[str, Any]], mds_names: Collection[str], now: datetime,
                person_id: int | None) -> RuleApplication:
    """
    Runs the rules covering the object's Type on one write - the state written changed in place

    Args:
        rules (Iterable[Mapping[str, Any]]): Active rules (any Types)
        before (Mapping[str, Any] | None): The stored object; None for a create
        after (dict[str, Any]): The object as the user would store it - the rules' values are written into it
        type_fields (list[dict[str, Any]]): The object's Type's field definitions
        mds_names (Collection[str]): The fields that sit in a multi-data section - no rule writes them
        now (datetime): The moment of the write (UTC)
        person_id (int | None): The person linked to the writing user, or None

    Returns:
        RuleApplication: What the rules changed, and the problems when a value would be invalid
    """
    application: RuleApplication = RuleApplication()
    covering: list[Mapping[str, Any]] = rules_on_type(rules, after.get(CmdbObjectKey.TYPE_ID.value))

    if not covering:
        return application

    changed: list[str] = changed_field_names(before, after)
    definitions: dict[str, dict[str, Any]] = {definition[FieldKey.NAME.value]: definition
                                              for definition in type_fields if isinstance(definition, dict)}
    value_rules: dict[str, FieldValueRule] = build_field_value_rules(type_fields)
    budget: PatternBudget = PatternBudget()

    for rule in covering:
        if rule_runs(rule, changed, type_fields):
            _apply_rule(rule, _resolved_values(rule, definitions, mds_names, now, person_id), after, application,
                        value_rules, budget)

    return application


def _apply_rule(rule: Mapping[str, Any], resolved: list[tuple[dict[str, Any], Any]], after: dict[str, Any],
                application: RuleApplication, value_rules: Mapping[str, FieldValueRule], budget: PatternBudget) -> None:
    """
    Writes one triggered rule's values - up to the first invalid one, which refuses the write naming the rule

    Args:
        rule (Mapping[str, Any]): The rule
        resolved (list[tuple[dict[str, Any], Any]]): Its fields' definitions and the values to write
        after (dict[str, Any]): The state written
        application (RuleApplication): The record
        value_rules (Mapping[str, FieldValueRule]): The Type's field value rules
        budget (PatternBudget): The write's pattern time budget
    """
    problems: list[str] = []

    for definition, value in resolved:
        problems += _value_problems(definition, value, value_rules, budget)

        if not problems:
            _write(after, application, rule, definition, value)

    if problems:
        application.problems.append(FieldRuleMessage.APPLY_REFUSED.value.format(
            name=rule.get(FieldRuleKey.NAME.value), problems='; '.join(problems)))


def _resolved_values(rule: Mapping[str, Any], definitions: Mapping[str, dict[str, Any]], mds_names: Collection[str],
                     now: datetime, person_id: int | None) -> list[tuple[dict[str, Any], Any]]:
    """
    The values a rule writes on this Type, as written - a field the Type lacks or holds in a section is skipped

    Args:
        rule (Mapping[str, Any]): The rule
        definitions (Mapping[str, dict[str, Any]]): The Type's field definitions by name
        mds_names (Collection[str]): Its fields in multi-data sections
        now (datetime): The moment of the write (UTC)
        person_id (int | None): The person linked to the writing user, or None

    Returns:
        list[tuple[dict[str, Any], Any]]: Each field's definition and the value to write, in the rule's order
    """
    return [(definitions[name], resolve_rule_value(stored, field_kind(definitions[name]), now, person_id))
            for name, stored in (rule.get(FieldRuleKey.SET.value) or {}).items()
            if name in definitions and name not in mds_names]


def _value_problems(definition: Mapping[str, Any], value: Any, value_rules: Mapping[str, FieldValueRule],
                    budget: PatternBudget) -> list[str]:
    """
    Judges one value a rule would write against its field

    Args:
        definition (Mapping[str, Any]): The field's definition
        value (Any): The resolved value
        value_rules (Mapping[str, FieldValueRule]): The Type's field value rules
        budget (PatternBudget): The write's pattern time budget

    Returns:
        list[str]: The problems - a required field emptied, a pattern or a cap broken
    """
    name: str = definition[FieldKey.NAME.value]

    if definition.get(FieldKey.REQUIRED.value) is True and has_no_value(value):
        return [FieldRuleMessage.REQUIRED_EMPTIED.value.format(field=name)]

    if name in value_rules:
        return find_value_errors(name, value, value_rules[name], budget)

    return []


def _write(after: dict[str, Any], application: RuleApplication, rule: Mapping[str, Any],
           definition: Mapping[str, Any], value: Any) -> None:
    """
    Writes one rule value into the state, recording it when it changes the value

    Args:
        after (dict[str, Any]): The state written
        application (RuleApplication): The record
        rule (Mapping[str, Any]): The rule
        definition (Mapping[str, Any]): The field's definition
        value (Any): The value
    """
    name: str = definition[FieldKey.NAME.value]
    entries: list[dict[str, Any]] = after.setdefault(CmdbObjectKey.FIELDS.value, [])
    entry: dict[str, Any] | None = next((entry for entry in entries if isinstance(entry, dict)
                                         and entry.get(CmdbObjectFieldKey.NAME.value) == name), None)
    previous: Any = entry.get(CmdbObjectFieldKey.VALUE.value) if entry is not None else None

    if previous == value:
        return

    if entry is None:
        entries.append({CmdbObjectFieldKey.NAME.value: name, CmdbObjectFieldKey.VALUE.value: value,
                        CmdbObjectFieldKey.TYPE.value: definition.get(FieldKey.TYPE.value)})
    else:
        entry[CmdbObjectFieldKey.VALUE.value] = value

    application.changes.append({RuleChangeKey.RULE_ID.value: rule[FieldRuleKey.PUBLIC_ID.value],
                                RuleChangeKey.RULE_NAME.value: rule.get(FieldRuleKey.NAME.value),
                                RuleChangeKey.FIELD.value: name, RuleChangeKey.BEFORE.value: previous,
                                RuleChangeKey.AFTER.value: value})
