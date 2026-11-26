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
The constants of the Field Rules: the trigger keys, the value tokens, the keys of one recorded rule change
and the messages
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AUDIT_FLAG',
    'TriggerKey',
    'RuleToken',
    'RuleChangeKey',
    'FieldRuleMessage',
]

# The one flag a trigger may name - the field definition key of the audit flag
AUDIT_FLAG: str = 'audit_relevant'


class TriggerKey(BaseStrEnum):
    """
    The keys of a ``when`` / ``unless``: ``{changed: [field names]}`` - one of them changed; ``{changed_any: {flag:
    audit_relevant}}`` - a field carrying the flag changed; ``{changed_any: {class: <name>}}`` - a field of the class
    """
    CHANGED = 'changed'
    CHANGED_ANY = 'changed_any'
    FLAG = 'flag'
    CLASS = 'class'


class RuleToken(BaseStrEnum):
    """
    The values a rule may set besides a literal: the moment of the write, and the person linked to the writing user
    """
    NOW = '${now}'
    USER_PERSON = '${user.person}'


class RuleChangeKey(BaseStrEnum):
    """The keys of one change a rule made, as the object log records it"""
    RULE_ID = 'rule_id'
    RULE_NAME = 'rule_name'
    FIELD = 'field'
    BEFORE = 'before'
    AFTER = 'after'


class FieldRuleMessage(BaseStrEnum):
    """What a refused Field Rule, or a write a rule cannot complete, says"""
    BAD_TRIGGER = (
        "'{key}' is {{changed: [field names]}}, {{changed_any: {{flag: audit_relevant}}}} or "
        "{{changed_any: {{class: <field class>}}}}!"
    )
    BAD_SET = "'set' names each field by its name, with the value to write!"
    NO_TYPES = "A Field Rule applies to '*' or to at least one Type!"
    FIELD_NOT_ON_TYPE = (
        "The field '{field}' is not on Type {type_id} - a rule sets only fields every one of its Types has!"
    )
    FIELD_RETYPED = "the field '{field}' would become a {kind} field"
    NO_CARRIER = "No Type carries the field '{field}' - a rule sets only fields its Types have!"
    UNKNOWN_TYPES = "The Field Rule names Types that do not exist: {ids}"
    FIELD_KINDS_DIFFER = (
        "The field '{field}' has different kinds on the rule's Types - it cannot be set on all of them!"
    )
    FIELD_IN_SECTION = "The field '{field}' sits in a multi-data section - a rule sets only top-level fields!"
    FORBIDDEN_FIELD = "The field '{field}' decides where an object is (location / network) - no rule may set it!"
    SCOPE_FIELD = (
        "The field '{field}' is compared by the scope of the assignments {assignment_ids} - no rule may set it!"
    )
    RULE_FIELD = "The field '{field}' is set by the Field Rules {rule_ids} - no scope may compare it!"
    OVERLAP = "The field '{field}' is already set by the Field Rule {rule_id} on the same Types - one rule per field!"
    BAD_VALUE = "The value for '{field}' does not fit the field: {problem}"
    TOKEN_NOT_FOR_FIELD = "'{token}' cannot be set on the field '{field}' ({kind})!"
    UNKNOWN_CLASS = "The trigger names the field class '{name}', which does not exist!"
    UNKNOWN_TRIGGER_FIELD = "The trigger names the field '{field}', which none of the rule's Types has!"
    NAME_TAKEN = "A Field Rule named '{name}' exists already!"
    NAME_FIXED = "The name of Field Rule {public_id} cannot change - '{stored}' stays!"
    REQUIRED_EMPTIED = "the field '{field}' is required"
    BEYOND_REACH = "The Field Rule would set {fields} on Type {type_id}, which you may not write yourself!"
    APPLY_REFUSED = "The Field Rule '{name}' would write an invalid value: {problems}"
    TYPE_BREAKS_RULE = "The Field Rule '{name}' sets the field '{field}', which the change would break: {problem}"
