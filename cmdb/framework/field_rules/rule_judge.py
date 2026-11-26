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
Judging a Field Rule before it is stored - pure

The callers read what a rule is judged against - the Types it names, the stored field class names, the other stored
rules and what the stored scopes compare - and get back the ``set`` to store (each value cast to its field's kind) and
every problem, for the one 400 of the write:

* the shape (``rule_shape_problems``); nothing else is judged while it fails;
* every ``set`` field on every listed Type (a rule on every Type: on at least one, every carrier of one kind), at the
  top level, never a location field, its value fitting the field;
* every field a ``changed`` trigger names on one of the rule's Types, every class a trigger names stored;
* no other active rule setting one of its fields on an overlapping Type set (an inactive rule is not judged - it
  runs nowhere - and is judged again when it is activated);
* no stored scope comparing one of its fields on an overlapping Type set
"""
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from cmdb.models.access_model import ALL_TYPES, FieldRuleKey
from cmdb.models.type_model import TypeSchemaKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.framework.scope_compiler import ScopeField, field_views_of_document
from cmdb.framework.field_rules.field_rule_constants import FieldRuleMessage, TriggerKey
from cmdb.framework.field_rules.rule_shape import rule_shape_problems
from cmdb.framework.field_rules.rule_values import cast_rule_value
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'FORBIDDEN_KINDS',
    'ScopeComparison',
    'types_overlap',
    'judge_field_rule',
    'type_change_rule_problems',
    'rule_set_fields',
]

# The kinds no rule may set: they decide where an object is (the IPAM interface rows sit in a multi-data section)
FORBIDDEN_KINDS: frozenset[str] = frozenset({FieldType.LOCATION.value})


@dataclass(frozen=True)
class ScopeComparison:
    """
    What one stored conditional assignment compares

    Attributes:
        assignment_id (int): The assignment's public_id
        types (Any): Its role's Types - ``ALL_TYPES`` or ids
        fields (frozenset[str]): The field names its scope compares
    """
    assignment_id: int
    types: Any
    fields: frozenset[str]


def types_overlap(first: Any, second: Any) -> bool:
    """
    Whether two Type sets share a Type

    Args:
        first (Any): ``ALL_TYPES`` or ids
        second (Any): ``ALL_TYPES`` or ids

    Returns:
        bool: True when either covers every Type and the other at least one, or the id lists intersect
    """
    if first == ALL_TYPES:
        return second == ALL_TYPES or bool(second)

    if second == ALL_TYPES:
        return bool(first)

    return bool(set(first or []) & set(second or []))


def judge_field_rule(rule: Mapping[str, Any], type_documents: list[dict[str, Any]], class_names: Collection[str],
                     other_rules: Iterable[Mapping[str, Any]], comparisons: Iterable[ScopeComparison]
                     ) -> tuple[dict[str, Any], list[str]]:
    """
    Judges a rule as it would be stored

    Args:
        rule (Mapping[str, Any]): The rule as it would be stored (``types`` already checked to name stored Types)
        type_documents (list[dict[str, Any]]): Its Types' documents (``public_id``, ``fields``, ``render_meta``)
        class_names (Collection[str]): The stored field class names, ``system`` included
        other_rules (Iterable[Mapping[str, Any]]): The other stored rules
        comparisons (Iterable[ScopeComparison]): What the stored conditional assignments compare

    Returns:
        tuple[dict[str, Any], list[str]]: The ``set`` to store (cast) and every problem
    """
    sent: Any = rule.get(FieldRuleKey.SET.value)
    problems: list[str] = rule_shape_problems(dict(rule))

    if problems:
        return sent, problems

    every_type: bool = rule.get(FieldRuleKey.TYPES.value) == ALL_TYPES
    views: list[tuple[Any, dict[str, ScopeField]]] = [
        (document.get(TypeSchemaKey.PUBLIC_ID.value), field_views_of_document(document)) for document in type_documents
    ]
    cast: dict[str, Any] = {}

    for name, value in sent.items():
        field, field_problems = _resolve(name, views, every_type)
        problems += field_problems

        if field is None:
            continue

        try:
            cast[name] = cast_rule_value(name, field, value)
        except ValueError as err:
            problems.append(str(err))

    problems += _trigger_problems(rule, views, class_names)
    problems += _overlap_problems(rule, other_rules)
    problems += _scope_problems(rule, comparisons)

    return (sent if problems else cast), problems


def _resolve(name: str, views: list[tuple[Any, dict[str, ScopeField]]], every_type: bool
             ) -> tuple[ScopeField | None, list[str]]:
    """
    Resolves one ``set`` field across the rule's Types

    Args:
        name (str): The field's name
        views (list[tuple[Any, dict[str, ScopeField]]]): Each Type's id and fields
        every_type (bool): Whether the rule covers every Type - then a Type without the field is skipped

    Returns:
        tuple[ScopeField | None, list[str]]: The field (None when refused) and the problems
    """
    carriers: list[ScopeField] = [fields[name] for _, fields in views if name in fields]
    problems: list[str] = []

    if every_type:
        if not carriers:
            problems.append(FieldRuleMessage.NO_CARRIER.value.format(field=name))
    else:
        problems += [FieldRuleMessage.FIELD_NOT_ON_TYPE.value.format(field=name, type_id=type_id)
                     for type_id, fields in views if name not in fields]

    if any(carrier.in_mds for carrier in carriers):
        problems.append(FieldRuleMessage.FIELD_IN_SECTION.value.format(field=name))

    kinds: set[str] = {carrier.kind for carrier in carriers}

    if kinds & FORBIDDEN_KINDS:
        problems.append(FieldRuleMessage.FORBIDDEN_FIELD.value.format(field=name))
    elif len(kinds) > 1:
        problems.append(FieldRuleMessage.FIELD_KINDS_DIFFER.value.format(field=name))

    if problems or not carriers:
        return None, problems

    # An option or a selectable kind counts only when every carrier offers it - the value is written on each
    return ScopeField(carriers[0].kind, frozenset.intersection(*(carrier.options for carrier in carriers)), False,
                      frozenset.intersection(*(carrier.selectable for carrier in carriers))), []


def _trigger_problems(rule: Mapping[str, Any], views: list[tuple[Any, dict[str, ScopeField]]],
                      class_names: Collection[str]) -> list[str]:
    """
    Judges what the triggers name

    Args:
        rule (Mapping[str, Any]): The shape-checked rule
        views (list[tuple[Any, dict[str, ScopeField]]]): Each Type's id and fields
        class_names (Collection[str]): The stored field class names

    Returns:
        list[str]: A problem per field no Type of the rule carries and per unknown class
    """
    problems: list[str] = []
    carried: set[str] = {name for _, fields in views for name in fields}

    for key in (FieldRuleKey.WHEN.value, FieldRuleKey.UNLESS.value):
        trigger: Any = rule.get(key)

        if not trigger:
            continue

        problems += [FieldRuleMessage.UNKNOWN_TRIGGER_FIELD.value.format(field=name)
                     for name in trigger.get(TriggerKey.CHANGED.value) or [] if name not in carried]
        class_name: Any = (trigger.get(TriggerKey.CHANGED_ANY.value) or {}).get(TriggerKey.CLASS.value)

        if class_name is not None and class_name not in class_names:
            problems.append(FieldRuleMessage.UNKNOWN_CLASS.value.format(name=class_name))

    return problems


def _overlap_problems(rule: Mapping[str, Any], other_rules: Iterable[Mapping[str, Any]]) -> list[str]:
    """
    Refuses a field another active rule sets on an overlapping Type set - an inactive rule is not judged

    Args:
        rule (Mapping[str, Any]): The rule
        other_rules (Iterable[Mapping[str, Any]]): The other stored rules

    Returns:
        list[str]: A problem per field and rule
    """
    if rule.get(FieldRuleKey.ACTIVE.value) is False:
        return []

    own: Mapping[str, Any] = rule.get(FieldRuleKey.SET.value) or {}
    problems: list[str] = []

    for other in other_rules:
        if other.get(FieldRuleKey.ACTIVE.value) is False or not types_overlap(
                rule.get(FieldRuleKey.TYPES.value), other.get(FieldRuleKey.TYPES.value)):
            continue

        problems += [FieldRuleMessage.OVERLAP.value.format(field=name, rule_id=other[FieldRuleKey.PUBLIC_ID.value])
                     for name in own if name in (other.get(FieldRuleKey.SET.value) or {})]

    return problems


def _scope_problems(rule: Mapping[str, Any], comparisons: Iterable[ScopeComparison]) -> list[str]:
    """
    Refuses a field a stored scope compares on an overlapping Type set

    Args:
        rule (Mapping[str, Any]): The rule
        comparisons (Iterable[ScopeComparison]): What the stored conditional assignments compare

    Returns:
        list[str]: A problem per field, naming the assignments
    """
    holders: dict[str, list[int]] = {}

    for comparison in comparisons:
        if types_overlap(rule.get(FieldRuleKey.TYPES.value), comparison.types):
            for name in comparison.fields:
                holders.setdefault(name, []).append(comparison.assignment_id)

    return [FieldRuleMessage.SCOPE_FIELD.value.format(field=name, assignment_ids=sorted(holders[name]))
            for name in rule.get(FieldRuleKey.SET.value) or {} if name in holders]


def type_change_rule_problems(type_id: int, rules: Iterable[Mapping[str, Any]], before: dict[str, ScopeField],
                              after: dict[str, ScopeField]) -> list[str]:
    """
    Refuses a Type change leaving an active rule covering the Type unable to set one of its fields there: the field
    gone (on a rule naming the Type), retyped to another kind, moved into a multi-data section, made a location field,
    or no longer offering the rule's option / person kind

    Args:
        type_id (int): The Type
        rules (Iterable[Mapping[str, Any]]): The stored rules
        before (dict[str, ScopeField]): The Type's fields as stored (``field_views``)
        after (dict[str, ScopeField]): The Type's fields as the change would store them

    Returns:
        list[str]: A problem per rule and field
    """
    problems: list[str] = []

    for rule in rules:
        rule_types: Any = rule.get(FieldRuleKey.TYPES.value)

        covers: bool = rule_types == ALL_TYPES or type_id in (rule_types or [])

        if rule.get(FieldRuleKey.ACTIVE.value) is False or not covers:
            continue

        for name, value in (rule.get(FieldRuleKey.SET.value) or {}).items():
            if rule_types == ALL_TYPES and name not in after:
                continue

            field, field_problems = _resolve(name, [(type_id, after)], False)

            if field is not None and name in before and before[name].kind != field.kind:
                field_problems = [FieldRuleMessage.FIELD_RETYPED.value.format(field=name, kind=field.kind)]
            elif field is not None:
                try:
                    cast_rule_value(name, field, value)
                except ValueError as err:
                    field_problems = [str(err)]

            problems += [FieldRuleMessage.TYPE_BREAKS_RULE.value.format(
                name=rule.get(FieldRuleKey.NAME.value), field=name, problem=problem) for problem in field_problems]

    return problems


def rule_set_fields(rules: Iterable[Mapping[str, Any]], types: Any) -> dict[str, list[int]]:
    """
    The fields the active rules set on a Type set - what no scope may compare there

    Args:
        rules (Iterable[Mapping[str, Any]]): The stored rules
        types (Any): ``ALL_TYPES`` or ids - a scope role's Types

    Returns:
        dict[str, list[int]]: By field name, the rules setting it, ascending
    """
    setters: dict[str, list[int]] = {}

    for rule in rules:
        active: bool = rule.get(FieldRuleKey.ACTIVE.value) is not False

        if active and types_overlap(rule.get(FieldRuleKey.TYPES.value), types):
            for name in rule.get(FieldRuleKey.SET.value) or {}:
                setters.setdefault(name, []).append(rule[FieldRuleKey.PUBLIC_ID.value])

    return {name: sorted(ids) for name, ids in setters.items()}
