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
Validation schema for CmdbFieldRule

A CmdbFieldRule sets fields when a user's write changes other fields (collection ``access.fieldRules``). Its
name is a slug, unique and immutable. The schema holds the document's shape; the trigger, the exception and the set
values are judged by the Field Rule rules (``framework/field_rules``), which name every problem

This module is the single source of the document's Cerberus validation schema, consumed as CmdbFieldRule.SCHEMA.
"""
from typing import Any

from cmdb.class_schema.access_model.access_schema_helper import (
    check_role_types,
    get_description_rule,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_cmdb_field_rule_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbFieldRule document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbFieldRule.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running (see class_schema/__init__.py)
    from cmdb.models.access_model.access_constants import FIELD_CLASS_NAME_PATTERN, MAX_RULE_SET_FIELDS, FieldRuleKey

    return {
        FieldRuleKey.PUBLIC_ID.value: {  # public_id of the CmdbFieldRule - the order rules run in
            'type': 'integer',
            'min': 1,
        },
        FieldRuleKey.NAME.value: {  # The identifier: a slug, unique, immutable
            'type': 'string',
            'regex': FIELD_CLASS_NAME_PATTERN,
            'required': True,
        },
        FieldRuleKey.DESCRIPTION.value: get_description_rule(),
        FieldRuleKey.ACTIVE.value: {  # Whether the rule runs
            'type': 'boolean',
            'required': False,
            'default': True,
        },
        FieldRuleKey.TYPES.value: {  # '*' or the ids of the Types it applies to
            'type': ['string', 'list'],
            'required': True,
            'check_with': check_role_types,
        },
        FieldRuleKey.WHEN.value: {  # The trigger - judged by the Field Rule rules
            'type': 'dict',
            'required': True,
        },
        FieldRuleKey.UNLESS.value: {  # The exception - optional
            'type': 'dict',
            'required': False,
            'nullable': True,
        },
        FieldRuleKey.SET.value: {  # The values it writes, by field name
            'type': 'dict',
            'required': True,
            'minlength': 1,
            'maxlength': MAX_RULE_SET_FIELDS,
        },
    }
