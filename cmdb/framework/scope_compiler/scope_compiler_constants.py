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
Constants of the access scope compiler: the block keys, the comparison operators, which operators each field kind takes,
the caps and the refusal messages
"""
from cmdb.models.type_model import FieldType
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The caps of one scope (ruled R2): blocks, values of an in / not_in list, characters of one text value
MAX_SCOPE_BLOCKS: int = 50
MAX_LIST_VALUES: int = 1000
MAX_TEXT_LENGTH: int = 1000
MAX_FIELD_NAME_LENGTH: int = 255
# How far back a relative date may reach: about a hundred years
MAX_DAYS_AGO: int = 36500
# The two bounds of a between
BETWEEN_BOUNDS: int = 2


class ScopeBlockKey(BaseStrEnum):
    """
    The keys of one field comparison block of a scope: ``{field, op, value}``
    """
    FIELD = 'field'
    OP = 'op'
    VALUE = 'value'


class ScopeBlockKind(BaseStrEnum):
    """
    The blocks beside the field comparisons (ruled R16, phase 11 D9): ``{within: <location object id>}`` - the
    location's subtree, the location included; ``{in_network: <subnet / supernet id or CIDR>}`` - objects with an
    interface row in the network; ``{related_to: <object id>, relation?: <relation id>}`` - the objects an object
    relation links to that object, either direction, optionally of one relation only
    """
    WITHIN = 'within'
    IN_NETWORK = 'in_network'
    RELATED_TO = 'related_to'


# The optional second key of a related_to block: the relation (definition) the link must be an instance of
RELATION_FILTER_KEY: str = 'relation'


class UserTokenKey(BaseStrEnum):
    """
    The one key of a user token value - ``{user: person}`` / ``{user: groups}`` (ruled R13)
    """
    USER = 'user'


class UserToken(BaseStrEnum):
    """
    What a user token stands for: the signed-in user's synced person, or the person groups the group sync links to the
    user's user groups (R14); unresolvable, it matches nothing (R15)
    """
    PERSON = 'person'
    GROUPS = 'groups'


class RelativeDateKey(BaseStrEnum):
    """
    The one key of a relative date value - ``{days_ago: n}``: n days before the day the scope is evaluated (UTC)
    """
    DAYS_AGO = 'days_ago'


class ScopeOperator(BaseStrEnum):
    """
    The comparisons a scope block may make (concept p. 4)
    """
    EQUALS = 'equals'
    NOT_EQUALS = 'not_equals'
    IN = 'in'
    NOT_IN = 'not_in'
    CONTAINS = 'contains'
    STARTS_WITH = 'starts_with'
    LT = 'lt'
    LTE = 'lte'
    GT = 'gt'
    GTE = 'gte'
    BETWEEN = 'between'
    EXISTS = 'exists'
    IS_EMPTY = 'is_empty'


# The operators a user token may stand in (R13): one person / group of a single selector, the list of a single selector,
# the members of a multi-value one
TOKEN_OPERATORS: frozenset[ScopeOperator] = frozenset({ScopeOperator.EQUALS, ScopeOperator.IN, ScopeOperator.CONTAINS})

# The operators taking no value, a list of values, and a pair; every other operator takes one value
NO_VALUE_OPERATORS: frozenset[ScopeOperator] = frozenset({ScopeOperator.EXISTS, ScopeOperator.IS_EMPTY})
LIST_OPERATORS: frozenset[ScopeOperator] = frozenset({ScopeOperator.IN, ScopeOperator.NOT_IN})
PAIR_OPERATORS: frozenset[ScopeOperator] = frozenset({ScopeOperator.BETWEEN})

_PRESENCE: frozenset[ScopeOperator] = frozenset({ScopeOperator.EXISTS, ScopeOperator.IS_EMPTY})
_EQUALITY: frozenset[ScopeOperator] = frozenset({ScopeOperator.EQUALS, ScopeOperator.NOT_EQUALS, ScopeOperator.IN,
                                                 ScopeOperator.NOT_IN})
_ORDER: frozenset[ScopeOperator] = frozenset({ScopeOperator.LT, ScopeOperator.LTE, ScopeOperator.GT, ScopeOperator.GTE,
                                              ScopeOperator.BETWEEN})

# A multi-value person selector: its value is a list of ids
MULTIPLE_PERSON_KIND: str = 'person-multiple'

# Which operators each comparable field kind takes (ruled R7, R8) - a kind not listed cannot be compared: password (an
# oracle), location (through 'within'), ref-section
KIND_OPERATORS: dict[str, frozenset[ScopeOperator]] = {
    FieldType.TEXT.value: _PRESENCE | _EQUALITY | {ScopeOperator.CONTAINS, ScopeOperator.STARTS_WITH},
    FieldType.TEXTAREA.value: _PRESENCE | _EQUALITY | {ScopeOperator.CONTAINS, ScopeOperator.STARTS_WITH},
    FieldType.SELECT.value: _PRESENCE | _EQUALITY,
    FieldType.RADIO.value: _PRESENCE | _EQUALITY,
    FieldType.NUMBER.value: _PRESENCE | _EQUALITY | _ORDER,
    FieldType.DATE.value: _PRESENCE | {ScopeOperator.EQUALS, ScopeOperator.NOT_EQUALS} | _ORDER,
    FieldType.CHECKBOX.value: _PRESENCE | {ScopeOperator.EQUALS, ScopeOperator.NOT_EQUALS},
    FieldType.REFERENCE.value: _PRESENCE | _EQUALITY,
    FieldType.PERSON.value: _PRESENCE | _EQUALITY,
    MULTIPLE_PERSON_KIND: _PRESENCE | {ScopeOperator.CONTAINS},
}

# The kinds whose values are ids (whole numbers)
ID_KINDS: frozenset[str] = frozenset({FieldType.REFERENCE.value, FieldType.PERSON.value, MULTIPLE_PERSON_KIND})
# The kinds whose values are texts
TEXT_KINDS: frozenset[str] = frozenset({FieldType.TEXT.value, FieldType.TEXTAREA.value, FieldType.SELECT.value,
                                        FieldType.RADIO.value})
# The kinds whose values are among the field's options
OPTION_KINDS: frozenset[str] = frozenset({FieldType.SELECT.value, FieldType.RADIO.value})

# The BSON type each comparable kind stores its values as: a negation only matches a value of that type - a value
# stored with another type (T583) never satisfies it (fail closed, ruled R9)
KIND_BSON_TYPES: dict[str, str] = {
    FieldType.TEXT.value: 'string',
    FieldType.TEXTAREA.value: 'string',
    FieldType.SELECT.value: 'string',
    FieldType.RADIO.value: 'string',
    FieldType.NUMBER.value: 'number',
    FieldType.DATE.value: 'date',
    FieldType.CHECKBOX.value: 'bool',
    FieldType.REFERENCE.value: 'number',
    FieldType.PERSON.value: 'number',
    MULTIPLE_PERSON_KIND: 'array',
}

# Date values are sent as days
DATE_FORMAT: str = '%Y-%m-%d'


class ScopeMessage(BaseStrEnum):
    """
    Why a scope is refused - each a format string; one 400 joins every problem of the write
    """
    NOT_A_LIST = "A scope is '*' or a list of conditions!"
    EMPTY = "A scope lists at least one condition - '*' covers every object!"
    TOO_MANY_BLOCKS = "A scope lists at most {limit} conditions, not {count}!"
    NOT_A_BLOCK = "Condition {position} is no object with 'field', 'op' and, where the operator takes one, 'value'!"
    UNKNOWN_KEYS = "Condition {position} carries unknown keys {keys}!"
    BAD_FIELD = "Condition {position} names no field - a non-empty text of at most {limit} characters!"
    UNKNOWN_OPERATOR = "Condition {position} uses the unknown operator '{op}'!"
    VALUE_NOT_ALLOWED = "Condition {position}: '{op}' takes no value!"
    VALUE_MISSING = "Condition {position}: '{op}' needs a value!"
    NOT_A_SCALAR = "Condition {position}: a value is a text, a number, true / false or {{days_ago: n}} - not {value}!"
    NOT_A_LIST_VALUE = "Condition {position}: '{op}' takes a list of 1 to {limit} values!"
    NOT_A_PAIR = "Condition {position}: 'between' takes a list of two values, the lower first!"
    TEXT_TOO_LONG = "Condition {position}: a text value has at most {limit} characters!"
    BAD_RELATIVE_DATE = "Condition {position}: days_ago is a whole number from 0 to {limit}!"
    NO_CARRIER = "No Type of the scope role carries the field '{field}'!"
    KINDS_DISAGREE = "The Types of the scope role disagree on the kind of the field '{field}': {kinds}!"
    NOT_COMPARABLE = "The field '{field}' ({kind}) cannot be compared in a scope!"
    IN_MULTI_DATA_SECTION = "The field '{field}' sits in a multi-data section and cannot be compared in a scope!"
    OPERATOR_NOT_FOR_KIND = "The field '{field}' ({kind}) cannot be compared with '{op}'!"
    VALUE_MISFIT = "The value {value} of the condition on the field '{field}' is not {expected}!"
    NOT_AN_OPTION = "The value '{value}' is no option of the field '{field}'!"
    BETWEEN_ORDER = "The lower bound of 'between' on the field '{field}' is above its upper bound!"
    STALE_ON_TYPE = (
        "The field '{field}' of Type {type_id} is compared by the scope of the assignments {assignment_ids} - "
        "it cannot be removed or change its kind while they do!"
    )
    STALE_ON_ROLE = "Scope role {role_id} would leave the scope of assignment {assignment_id} invalid: {problems}"
    BAD_LOCATION = "Condition {position}: 'within' names a location by its object id - a whole number from 1!"
    BAD_RELATED_TO = (
        "Condition {position}: 'related_to' names an object by its id, the optional 'relation' a relation by its id - "
        "whole numbers from 1!"
    )
    BAD_NETWORK = (
        "Condition {position}: 'in_network' names a subnet or supernet by its object id, or a CIDR range like "
        "'10.0.0.0/8' - not {value}!"
    )
    BAD_TOKEN = "Condition {position}: a user token is {{user: person}} or {{user: groups}} - not {value}!"
    TOKEN_NOT_FOR_OPERATOR = "Condition {position}: a user token stands only in 'equals', 'in' or 'contains'!"
    TOKEN_NOT_FOR_FIELD = (
        "The field '{field}' cannot take the user token '{token}' - it must be a person selector selecting {kind}!"
    )
    STALE_SELECTABLE = (
        "The person selector '{field}' of Type {type_id} is compared with a user token by the scope of the "
        "assignments {assignment_ids} - it must keep selecting {kind}!"
    )


class Expected(BaseStrEnum):
    """
    What a value must be, as a VALUE_MISFIT message names it
    """
    TEXT = 'a text'
    NUMBER = 'a number'
    WHOLE_NUMBER = 'a whole number (an id)'
    BOOLEAN = 'true or false'
    DATE = 'a date (YYYY-MM-DD) or {days_ago: n}'
