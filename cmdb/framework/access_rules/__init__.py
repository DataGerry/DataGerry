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
The write rules of the access rules: what a field class, a scope role and an assignment must satisfy before they are
stored, beyond their schemas. Each rule answers its problem (or problems) as text; the route answers them as one 400
"""
from .access_rule_constants import AccessRuleMessage, ReachPart
from .access_rule_reads import clashes
from .field_class_rules import field_class_name_change, field_class_name_taken
from .scope_role_rules import (
    unknown_type_ids,
    unknown_field_classes,
    scope_role_reference_problems,
    scope_role_name_taken,
)
from .assignment_rules import canonical_scope, assignment_reference_problems, assignment_taken
from .escalation_rules import types_beyond, beyond_reach, own_reach_problem
from .type_access_states import (
    TypeAccessState,
    assigned_roles,
    viewable_types,
    type_states,
    changed_types,
    access_change_problems,
    involved_types,
)
from .access_reference_rules import field_class_in_use, scope_role_in_use, delete_group_assignments
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AccessRuleMessage',
    'ReachPart',
    'types_beyond',
    'beyond_reach',
    'own_reach_problem',
    'TypeAccessState',
    'assigned_roles',
    'viewable_types',
    'type_states',
    'changed_types',
    'access_change_problems',
    'involved_types',
    'clashes',
    'field_class_name_change',
    'field_class_name_taken',
    'unknown_type_ids',
    'unknown_field_classes',
    'scope_role_reference_problems',
    'scope_role_name_taken',
    'canonical_scope',
    'assignment_reference_problems',
    'assignment_taken',
    'field_class_in_use',
    'scope_role_in_use',
    'delete_group_assignments',
]
