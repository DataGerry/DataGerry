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
Unit tests for cmdb.framework.access_engine.access_decision

Each operation is judged on its states - view and delete the stored object, create the new one, edit both; a missing
state is a caller's mistake (ValueError). A denied Type answers the scope step with that Type; a write changing a field
the granting roles may not write answers the field step with the refused names - an unchanged form passes; an
unrestricted Type answers the unrestricted step. A trace names the granting assignments; can() reads the grants once
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import access_decision
from cmdb.framework.access_engine import (
    FIELDS_REFUSED_MESSAGE,
    MISSING_STATE_MESSAGE,
    OPERATION_REFUSED_MESSAGE,
    AccessDecision,
    AccessDecisionStep,
    AccessGrants,
    build_grants,
    can,
    decide,
    judged_states,
    refusal_message,
    refused_fields,
)
from cmdb.models.access_model import ScopeOperation
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
GONE_TYPE_ID: int = 99
USER_GROUP_ID: int = 21
VIEW = ScopeOperation.VIEW
CREATE = ScopeOperation.CREATE
EDIT = ScopeOperation.EDIT
DELETE = ScopeOperation.DELETE
SCOPE = AccessDecisionStep.SCOPE
FIELD_CLASS = AccessDecisionStep.FIELD_CLASS
UNRESTRICTED = AccessDecisionStep.UNRESTRICTED

# Servers: view + create + edit + delete, regular fields written (41) and view again (43); routers: view + edit + delete
# but no regular field (42)
GRANTS: AccessGrants = build_grants(
    [{'public_id': 41, 'group_id': USER_GROUP_ID, 'role_id': 31, 'scope': '*'},
     {'public_id': 42, 'group_id': USER_GROUP_ID, 'role_id': 32, 'scope': '*'},
     {'public_id': 43, 'group_id': USER_GROUP_ID, 'role_id': 33, 'scope': '*'}],
    [{'public_id': 31, 'types': [SERVER_TYPE_ID], 'operations': ['view', 'create', 'edit', 'delete'],
      'write_regular_fields': True},
     {'public_id': 32, 'types': [ROUTER_TYPE_ID], 'operations': ['view', 'edit', 'delete'],
      'write_regular_fields': False},
     {'public_id': 33, 'types': [SERVER_TYPE_ID], 'operations': ['view'], 'write_regular_fields': False}],
    [USER_GROUP_ID],
)
# Servers and routers restricted by another group's role; the user holds nothing - only the free Type is open
NO_GRANTS: AccessGrants = build_grants(
    [], [{'public_id': 31, 'types': [SERVER_TYPE_ID, ROUTER_TYPE_ID], 'operations': ['view']}], [USER_GROUP_ID])


def _object(type_id: int, hostname: Any = 'srv-1', extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """An object of a Type with a hostname field"""
    fields: list[dict[str, Any]] = [{'name': 'hostname', 'value': hostname, 'type': 'text'}]
    fields += [{'name': name, 'value': value, 'type': 'text'} for name, value in (extra or {}).items()]

    return {'public_id': 61, 'type_id': type_id, 'fields': fields}


class TestJudgedStates:
    """judged_states"""

    @pytest.mark.parametrize('operation, before, after, state', [
        (VIEW, None, {}, 'before'), (DELETE, None, {}, 'before'), (EDIT, None, {'a': 1}, 'before'),
        (CREATE, {}, None, 'after'), (EDIT, {'a': 1}, None, 'after'),
    ], ids=['view', 'delete', 'edit-before', 'create', 'edit-after'])
    def test_a_missing_state_is_a_callers_mistake(self, operation: ScopeOperation, before: Any, after: Any,
                                                  state: str) -> None:
        """Never a refusal"""
        with pytest.raises(ValueError) as raised:
            judged_states(operation, before, after)

        assert str(raised.value) == MISSING_STATE_MESSAGE.format(operation=operation.value, state=state)

    def test_edit_judges_both_in_order(self) -> None:
        """Before, then after"""
        before: dict[str, Any] = _object(SERVER_TYPE_ID)
        after: dict[str, Any] = _object(ROUTER_TYPE_ID)

        assert judged_states(EDIT, before, after) == [before, after]


class TestScopeStep:
    """The Types of the judged states"""

    def test_a_granted_type(self) -> None:
        """Allowed through the assignments"""
        assert decide(GRANTS, VIEW, before=_object(SERVER_TYPE_ID)) == AccessDecision(True, VIEW, SCOPE,
                                                                                      SERVER_TYPE_ID)

    def test_an_unrestricted_type(self) -> None:
        """Nobody restricts it - every operation, every field"""
        decision: AccessDecision = decide(NO_GRANTS, CREATE, after=_object(FREE_TYPE_ID))

        assert decision == AccessDecision(True, CREATE, UNRESTRICTED, FREE_TYPE_ID)

    def test_a_denied_type_names_itself(self) -> None:
        """Create on servers is granted nowhere in NO_GRANTS"""
        assert decide(NO_GRANTS, CREATE, after=_object(SERVER_TYPE_ID)) == AccessDecision(False, CREATE, SCOPE,
                                                                                          SERVER_TYPE_ID)

    @pytest.mark.parametrize('before_type, after_type, denied', [
        (FREE_TYPE_ID, SERVER_TYPE_ID, SERVER_TYPE_ID), (SERVER_TYPE_ID, FREE_TYPE_ID, SERVER_TYPE_ID),
    ], ids=['into-reach', 'out-of-reach'])
    def test_edit_judges_both_states(self, before_type: int, after_type: int, denied: int) -> None:
        """Nobody moves an object out of or into a Type they may not edit"""
        decision: AccessDecision = decide(NO_GRANTS, EDIT, _object(before_type), _object(after_type))

        assert (decision.allowed, decision.step, decision.type_id) == (False, SCOPE, denied)

    def test_create_ignores_a_before_and_delete_an_after(self) -> None:
        """Each its own state"""
        assert decide(GRANTS, CREATE, before=_object(ROUTER_TYPE_ID), after=_object(SERVER_TYPE_ID)).allowed
        assert decide(GRANTS, DELETE, before=_object(SERVER_TYPE_ID), after=_object(GONE_TYPE_ID)).allowed


class TestFieldStep:
    """The changed fields of a create or an edit"""

    def test_a_change_the_roles_may_not_write(self) -> None:
        """Routers: edit without regular fields - the changed names are refused"""
        before: dict[str, Any] = _object(ROUTER_TYPE_ID, 'r-1', {'ip': '10.0.0.1', 'rack': 'A'})
        after: dict[str, Any] = _object(ROUTER_TYPE_ID, 'r-2', {'ip': '10.0.0.2', 'rack': 'A'})

        assert decide(GRANTS, EDIT, before, after) == AccessDecision(False, EDIT, FIELD_CLASS, ROUTER_TYPE_ID,
                                                                     ('hostname', 'ip'))

    def test_an_unchanged_form_passes(self) -> None:
        """Edit granted, nothing written"""
        state: dict[str, Any] = _object(ROUTER_TYPE_ID)

        assert decide(GRANTS, EDIT, state, dict(state)).allowed

    def test_a_writing_role_on_the_type_writes(self) -> None:
        """Servers: the edit role writes regular fields"""
        assert decide(GRANTS, EDIT, _object(SERVER_TYPE_ID, 'a'), _object(SERVER_TYPE_ID, 'b')).allowed

    def test_the_fields_are_judged_on_the_type_stored_as(self) -> None:
        """Edit is granted on both Types, but only the servers' role writes regular fields - into routers, no"""
        decision: AccessDecision = decide(GRANTS, EDIT, _object(SERVER_TYPE_ID, 'a'), _object(ROUTER_TYPE_ID, 'b'))

        assert decision == AccessDecision(False, EDIT, FIELD_CLASS, ROUTER_TYPE_ID, ('hostname',))
        assert decide(GRANTS, EDIT, _object(ROUTER_TYPE_ID, 'a'), _object(SERVER_TYPE_ID, 'b')).allowed

    def test_delete_writes_no_field(self) -> None:
        """Routers may be deleted without writing fields"""
        assert decide(GRANTS, DELETE, before=_object(ROUTER_TYPE_ID)).allowed

    def test_refused_fields_answers_nothing_for_a_writing_role(self) -> None:
        """Every change allowed"""
        assert not refused_fields(GRANTS, EDIT, SERVER_TYPE_ID, ['hostname'])
        assert refused_fields(GRANTS, EDIT, ROUTER_TYPE_ID, ['hostname', 'ip']) == ('hostname', 'ip')


class TestTrace:
    """trace=True"""

    def test_the_granting_assignments(self) -> None:
        """Both server roles grant view"""
        assert decide(GRANTS, VIEW, before=_object(SERVER_TYPE_ID), trace=True).assignment_ids == (41, 43)

    def test_a_field_refusal_names_the_granting_assignment(self) -> None:
        """Edit on routers is granted by 42 - which writes no regular field"""
        decision: AccessDecision = decide(GRANTS, EDIT, _object(ROUTER_TYPE_ID), _object(ROUTER_TYPE_ID, 'x'),
                                          trace=True)

        assert (decision.step, decision.assignment_ids) == (FIELD_CLASS, (42,))

    def test_without_a_trace_no_assignment_is_named(self) -> None:
        """Nothing computed"""
        assert not decide(GRANTS, VIEW, before=_object(SERVER_TYPE_ID)).assignment_ids


def test_can_decides_from_the_users_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    """One grants read, the user handed through"""
    asked: list[CmdbUser] = []
    user: CmdbUser = CmdbUser(public_id=51, user_name='editor', active=True, group_ids=[USER_GROUP_ID])
    monkeypatch.setattr(access_decision, 'load_grants', lambda reader: asked.append(reader) or GRANTS)

    assert can(user, VIEW, before=_object(SERVER_TYPE_ID)).allowed
    assert asked == [user]


class TestRefusalMessage:
    """refusal_message"""

    def test_an_allowed_decision_says_nothing(self) -> None:
        """No refusal"""
        assert refusal_message(AccessDecision(True, VIEW, SCOPE, SERVER_TYPE_ID)) is None

    def test_refused_fields_are_named(self) -> None:
        """The field step names the fields and the Type"""
        decision = AccessDecision(False, EDIT, FIELD_CLASS, ROUTER_TYPE_ID, ('hostname', 'ip'))

        expected: str = FIELDS_REFUSED_MESSAGE.format(names=['hostname', 'ip'], type_id=ROUTER_TYPE_ID)

        assert refusal_message(decision) == expected

    def test_a_refused_operation_names_it_and_the_type(self) -> None:
        """The scope step"""
        assert refusal_message(AccessDecision(False, CREATE, SCOPE, SERVER_TYPE_ID)) == \
            OPERATION_REFUSED_MESSAGE.format(operation='create', type_id=SERVER_TYPE_ID)
