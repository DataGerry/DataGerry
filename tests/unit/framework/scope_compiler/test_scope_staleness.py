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
Unit tests for scope_compiler.scope_staleness - the stale-scope rules (phase 9 step 3, ruled R11)

Pinned: which assignments are conditional and the fields they compare; a Type update removing, retyping or moving into
a multi-data section a compared field is named with the assignments, keeping it (or a field the Type never carried) is
not; a role update leaving a condition without a carrier, with disagreeing kinds or a value its kind refuses is named,
a new Type without the field is fine
"""
from typing import Any

import pytest

from cmdb.framework.scope_compiler import (
    ScopeField,
    ScopeMessage,
    is_conditional,
    role_change_problems,
    scope_field_names,
    type_change_problems,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 5
ROLE_ID: int = 6


def _assignment(public_id: int, scope: Any) -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': 1, 'role_id': ROLE_ID, 'scope': scope}


HOST_EQUALS: dict[str, Any] = _assignment(11, [{'field': 'host', 'op': 'equals', 'value': 'a'},
                                               {'field': 'size', 'op': 'gt', 'value': 1}])
HOST_EXISTS: dict[str, Any] = _assignment(12, [{'field': 'host', 'op': 'exists'}])
EVERY_OBJECT: dict[str, Any] = _assignment(13, '*')
BEFORE: dict[str, ScopeField] = {'host': ScopeField('text'), 'size': ScopeField('number')}


@pytest.mark.parametrize('assignment, conditional, names', [
    (HOST_EQUALS, True, ['host', 'size']), (EVERY_OBJECT, False, []), (_assignment(14, ['junk']), False, []),
], ids=['conditions', 'every-object', 'malformed'])
def test_conditional_and_its_fields(assignment: dict[str, Any], conditional: bool, names: list[str]) -> None:
    """Only a well-formed condition list"""
    assert (is_conditional(assignment), scope_field_names(assignment)) == (conditional, names)


class TestTypeChangeProblems:
    """A Type update"""

    @pytest.mark.parametrize('after', [
        {'size': ScopeField('number')},
        {'host': ScopeField('textarea'), 'size': ScopeField('number')},
        {'host': ScopeField('text', in_mds=True), 'size': ScopeField('number')},
    ], ids=['removed', 'retyped', 'moved-into-mds'])
    def test_a_compared_field_changing_is_named_with_its_assignments(self, after: dict[str, ScopeField]) -> None:
        """Both assignments comparing it, ascending"""
        assert type_change_problems(TYPE_ID, BEFORE, after, [HOST_EXISTS, HOST_EQUALS, EVERY_OBJECT]) == [
            ScopeMessage.STALE_ON_TYPE.value.format(field='host', type_id=TYPE_ID, assignment_ids=[11, 12])]

    def test_a_kept_field_and_one_the_type_never_carried_pass(self) -> None:
        """Options may change; a new field is fine"""
        assert not type_change_problems(TYPE_ID, {'size': ScopeField('number')},
                                        {'size': ScopeField('number'), 'host': ScopeField('text')}, [HOST_EQUALS])


class TestRoleChangeProblems:
    """A role update"""

    def test_a_new_type_without_the_field_is_fine(self) -> None:
        """Its objects never match"""
        assert not role_change_problems(ROLE_ID, [HOST_EQUALS, EVERY_OBJECT], [BEFORE, {}])

    @pytest.mark.parametrize('types, part', [
        ([{'size': ScopeField('number')}], ScopeMessage.NO_CARRIER.value.format(field='host')),
        ([BEFORE, {'host': ScopeField('number')}],
         ScopeMessage.KINDS_DISAGREE.value.format(field='host', kinds=['number', 'text'])),
        ([{'host': ScopeField('select', frozenset({'b'})), 'size': ScopeField('number')}],
         ScopeMessage.NOT_AN_OPTION.value.format(value='a', field='host')),
    ], ids=['no-carrier-left', 'kinds-disagree', 'value-refused'])
    def test_a_condition_left_invalid_is_named(self, types: list[dict[str, ScopeField]], part: str) -> None:
        """The assignment and why"""
        assert role_change_problems(ROLE_ID, [HOST_EQUALS], types) == [ScopeMessage.STALE_ON_ROLE.value.format(
            role_id=ROLE_ID, assignment_id=11, problems=part)]
