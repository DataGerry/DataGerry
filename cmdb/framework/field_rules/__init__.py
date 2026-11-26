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
Field Rules (ACL feature): fields the server sets when a user's write changes other fields - the rule's
shape, its triggers, its values, applying the rules to a write, and judging a rule before it is stored
"""
from .field_rule_constants import (
    AUDIT_FLAG,
    FieldRuleMessage,
    RuleChangeKey,
    RuleToken,
    TriggerKey,
)
from .rule_shape import rule_shape_problems
from .rule_triggers import rule_runs, trigger_fields, triggered
from .rule_values import cast_rule_value, field_kind, resolve_rule_value
from .rule_engine import RuleApplication, apply_rules, rules_on_type
from .rule_judge import (
    FORBIDDEN_KINDS,
    ScopeComparison,
    judge_field_rule,
    rule_set_fields,
    type_change_rule_problems,
    types_overlap,
)
from .rule_reach import group_may_trigger, reach_problems
from .rule_reads import load_active_rules, run_field_rules
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AUDIT_FLAG',
    'FieldRuleMessage',
    'RuleChangeKey',
    'RuleToken',
    'TriggerKey',
    'rule_shape_problems',
    'rule_runs',
    'trigger_fields',
    'triggered',
    'cast_rule_value',
    'field_kind',
    'resolve_rule_value',
    'RuleApplication',
    'apply_rules',
    'rules_on_type',
    'FORBIDDEN_KINDS',
    'ScopeComparison',
    'judge_field_rule',
    'types_overlap',
    'rule_set_fields',
    'type_change_rule_problems',
    'group_may_trigger',
    'reach_problems',
    'load_active_rules',
    'run_field_rules',
]
