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
Unit tests for explaining access to one object (``access_explanation``) - pure: grants built from documents, the
evaluation by ``build_scope_evaluation``

Pinned: the states each operation is explained on; the decisive step in order - inactive user, missing object right,
inactive Type (writes only), then the engine's step and trace; each condition marked on its own and every condition met
exactly when the engine's compiled scope matches; an assignment's row (unconditional, matched, what it grants here); a
condition naming the member makes a group's scope refusal depend on the member; the field list names the rules setting
each field
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.access_engine import (
    ExplainSubject,
    build_grants,
    condition_marks,
    explain_assignment,
    explain_operation,
    explain_operations,
    explained_states,
    field_rows,
    group_verdict,
    names_member,
)
from cmdb.framework.access_engine.scope_evaluation import build_scope_evaluation
from cmdb.framework.scope_compiler import (
    ScopeContext,
    document_matches,
    field_views_of_document,
    resolve_scope_fields,
)
from cmdb.models.access_model import ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

SERVER, OTHER = 11, 12
GROUP: int = 21
CONDITIONAL, FULL, MEMBER = 1, 2, 3
NOW: datetime = datetime(2026, 11, 26, tzinfo=timezone.utc)
VIEW, CREATE, EDIT, DELETE = ScopeOperation.VIEW, ScopeOperation.CREATE, ScopeOperation.EDIT, ScopeOperation.DELETE
SCOPE: list[dict[str, Any]] = [{'field': 'site', 'op': 'equals', 'value': 'fulda'},
                               {'field': 'size', 'op': 'gt', 'value': 10}]
MEMBER_SCOPE: list[dict[str, Any]] = [{'field': 'owner', 'op': 'equals', 'value': {'user': 'person'}}]
TYPE_DOCUMENT: dict[str, Any] = {'public_id': SERVER, 'fields': [{'name': 'site', 'type': 'text'},
                                                                 {'name': 'size', 'type': 'number'},
                                                                 {'name': 'owner', 'type': 'person',
                                                                  'selectable': ['PERSON']}],
                                 'render_meta': {'sections': []}}
EVERYONE: ExplainSubject = ExplainSubject(True, lambda _right: True)


def _grants(scope: Any = None, operations: tuple[str, ...] = ('view', 'edit', 'create')) -> Any:
    """One assignment of the group on the server Type"""
    return build_grants([{'public_id': CONDITIONAL, 'group_id': GROUP, 'role_id': 31,
                          'scope': SCOPE if scope is None else scope}],
                        [{'public_id': 31, 'types': [SERVER], 'operations': list(operations),
                          'write_regular_fields': True}], [GROUP])


def _object(site: str = 'fulda', size: int = 20) -> dict[str, Any]:
    """A server"""
    return {'public_id': 5, 'type_id': SERVER, 'fields': [{'name': 'site', 'value': site},
                                                         {'name': 'size', 'value': size}]}


def _evaluation(grants: Any) -> Any:
    """The conditional entries compiled without user tokens"""
    return build_scope_evaluation(tuple(entry for entry in grants.entries if entry.conditional), [TYPE_DOCUMENT],
                                  ScopeContext(), NOW)


def _marks(document: dict[str, Any], scope: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The conditions marked on a document"""
    conditions: list[dict[str, Any]] = SCOPE if scope is None else scope
    fields, _ = resolve_scope_fields([condition['field'] for condition in conditions],
                                     [field_views_of_document(TYPE_DOCUMENT)])

    return condition_marks(conditions, fields, NOW, ScopeContext(), document)


class TestStates:
    """What each operation is judged on"""

    def test_the_states(self) -> None:
        """View / delete the stored object, create an object like it, edit it unchanged"""
        document: dict[str, Any] = _object()

        assert explained_states(VIEW, document) == (document, None)
        assert explained_states(DELETE, document) == (document, None)
        assert explained_states(CREATE, document) == (None, document)
        assert explained_states(CREATE, document, {'size': 'system'}) == (
            None, {**document, 'fields': [{'name': 'site', 'value': 'fulda'}]})
        assert explained_states(EDIT, document) == (document, document)


class TestSteps:
    """The decisive step of one operation"""

    def test_the_engine_decides_with_its_trace(self) -> None:
        """Allowed by the matching assignment, delete not granted"""
        grants = _grants()
        rows = explain_operations(EVERYONE, grants, _evaluation(grants), _object(), True, {})

        assert [(row['operation'], row['allowed'], row['step'], row['assignment_ids']) for row in rows] == [
            ('view', True, 'scope', [CONDITIONAL]), ('create', True, 'scope', [CONDITIONAL]),
            ('edit', True, 'scope', [CONDITIONAL]), ('delete', False, 'scope', [])]
        assert rows[0]['right'] == 'base.framework.object.view'

    @pytest.mark.parametrize('subject, type_active, operation, step', [
        (ExplainSubject(False, lambda _right: True), True, VIEW, 'user_inactive'),
        (ExplainSubject(True, lambda right: right != 'base.framework.object.edit'), True, EDIT, 'functional_right'),
        (EVERYONE, False, EDIT, 'type_inactive'),
    ])
    def test_the_checks_before_the_engine(self, subject: ExplainSubject, type_active: bool,
                                          operation: ScopeOperation, step: str) -> None:
        """Each refuses before the engine is asked"""
        grants = _grants()
        row = explain_operation(subject, grants, _evaluation(grants), _object(), type_active, {}, operation)

        assert (row['allowed'], row['step'], row['assignment_ids']) == (False, step, [])

    def test_an_inactive_type_still_lets_view(self) -> None:
        """Only writes are refused by it"""
        grants = _grants()

        assert explain_operation(EVERYONE, grants, _evaluation(grants), _object(), False, {}, VIEW)['allowed']

    def test_an_open_type_is_unrestricted(self) -> None:
        """No assignment names it"""
        grants = _grants()
        row = explain_operation(EVERYONE, grants, None, {**_object(), 'type_id': OTHER}, True, {}, DELETE)

        assert (row['allowed'], row['step']) == (True, 'unrestricted')

    def test_a_create_refused_by_a_field_class(self) -> None:
        """An object like it carries a classed field the role may not write"""
        grants = _grants()
        row = explain_operation(EVERYONE, grants, _evaluation(grants), _object(), True, {'site': 'compliance'},
                                CREATE)

        assert (row['allowed'], row['step'], row['refused_fields']) == (False, 'field_class', ['site'])


    def test_a_create_leaves_the_system_fields_to_the_server(self) -> None:
        """A filled system field does not refuse an object like it"""
        grants = _grants()
        stamped: dict[str, Any] = {**_object(), 'fields': [*_object()['fields'], {'name': 'stamp', 'value': 'x'}]}
        row = explain_operation(EVERYONE, grants, _evaluation(grants), stamped, True, {'stamp': 'system'}, CREATE)

        assert (row['allowed'], row['step']) == (True, 'scope')
        assert explain_operation(EVERYONE, grants, _evaluation(grants), stamped, True, {'stamp': 'compliance'},
                                 CREATE)['refused_fields'] == ['stamp']


class TestConditions:
    """Each condition marked on the object"""

    @pytest.mark.parametrize('site, size, expected', [
        ('fulda', 20, [True, True]), ('fulda', 5, [True, False]), ('kassel', 20, [False, True]),
        ('kassel', 5, [False, False]),
    ])
    def test_each_condition_alone_and_all_met_is_the_engine_match(self, site: str, size: int,
                                                                   expected: list[bool]) -> None:
        """The marks per condition; all met exactly when the compiled scope matches"""
        document: dict[str, Any] = _object(site, size)
        grants = _grants()
        compiled = _evaluation(grants).grants[0].criteria

        assert [mark['met'] for mark in _marks(document)] == expected
        assert all(expected) is document_matches(document, compiled)

    def test_a_field_that_does_not_resolve_is_not_met(self) -> None:
        """No carrier of the field"""
        assert _marks(_object(), [{'field': 'gone', 'op': 'equals', 'value': 'x'}])[0]['met'] is False


class TestAssignmentRows:
    """One assignment covering the Type"""

    def test_a_matched_conditional_assignment(self) -> None:
        """Its conditions, matched, what it grants here"""
        entry = _grants().entries[0]
        row = explain_assignment(entry, GROUP, SERVER, _marks(_object()))

        assert (row['assignment_id'], row['group_id'], row['unconditional'], row['matched'], row['grants_here']) == (
            CONDITIONAL, GROUP, False, True, ['view', 'create', 'edit'])
        assert row['operations'] == ['create', 'edit', 'view']

    def test_an_unmatched_and_an_unevaluated_one(self) -> None:
        """Not matched grants nothing here; not evaluated answers no marks"""
        entry = _grants().entries[0]

        assert explain_assignment(entry, GROUP, SERVER, _marks(_object('kassel')))['grants_here'] == []
        unevaluated = explain_assignment(entry, GROUP, SERVER, None)
        assert (unevaluated['matched'], [mark['met'] for mark in unevaluated['conditions']]) == (None, [None, None])

    def test_an_unconditional_one(self) -> None:
        """Matched, no conditions"""
        row = explain_assignment(_grants('*').entries[0], GROUP, SERVER, None)

        assert (row['unconditional'], row['matched'], row['conditions']) == (True, True, [])


class TestGroupVerdicts:
    """A group explained without a member"""

    def test_a_member_condition(self) -> None:
        """Named by a user token"""
        assert names_member(_grants(MEMBER_SCOPE).entries[0]) is True
        assert names_member(_grants().entries[0]) is False

    def test_a_scope_refusal_a_member_condition_could_lift_depends_on_the_member(self) -> None:
        """Allowed stays allowed, a refusal before the scope stays denied"""
        member = _grants(MEMBER_SCOPE).entries
        refused = {'allowed': False, 'step': 'scope'}

        assert group_verdict(refused, member, VIEW, SERVER) == 'depends_on_member'
        assert group_verdict(refused, member, DELETE, SERVER) == 'denied'
        assert group_verdict({'allowed': False, 'step': 'functional_right'}, member, VIEW, SERVER) == 'denied'
        assert group_verdict({'allowed': True, 'step': 'scope'}, member, VIEW, SERVER) == 'allowed'


def test_the_field_list_names_the_rules() -> None:
    """Per field its access and the rules setting it"""
    rows = field_rows({'site': 'write', 'size': 'system'}, {'size': [{'public_id': 4, 'name': 'stamp'}]})

    assert rows == [{'name': 'site', 'access': 'write', 'set_by': []},
                    {'name': 'size', 'access': 'system', 'set_by': [{'rule_id': 4, 'rule_name': 'stamp'}]}]
