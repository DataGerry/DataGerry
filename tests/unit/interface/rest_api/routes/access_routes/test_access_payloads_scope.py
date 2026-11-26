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
Unit tests for the scope half of ``access_payloads`` (phase 9, R29, R30) - the managers stood in

Pinned: a create judges its scope against the role's Types; an update only when it sends ``scope`` or ``role_id``
(a description change never re-judges a stored scope); the stored scope is the cast one; a problem is part of the one
400; without a TypesManager (an internal caller) no scope is judged; ``checked_scope`` answers the stored form, a
missing role or a problem a 400
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.interface.rest_api.routes.access_routes import access_payloads
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
from cmdb.framework.scope_compiler import ScopeMessage
# -------------------------------------------------------------------------------------------------------------------- #

ROLE: dict[str, Any] = {'public_id': 4, 'types': [11]}
TYPES: list[dict[str, Any]] = [{'public_id': 11, 'fields': [{'name': 'size', 'type': 'number'}],
                                'render_meta': {'sections': []}}]
SENT_SCOPE: list[dict[str, Any]] = [{'field': 'size', 'op': 'in', 'value': ['16', 4]}]
CAST_SCOPE: list[dict[str, Any]] = [{'field': 'size', 'op': 'in', 'value': [4, 16]}]
ASSIGNMENT: dict[str, Any] = {'group_id': 2, 'role_id': 4, 'scope': SENT_SCOPE, 'description': ''}


@pytest.fixture(name='managers')
def fixture_managers(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """The role found, its Types read, every reference and uniqueness fine"""
    roles = MagicMock()
    roles.get_item.return_value = ROLE
    types = MagicMock()
    types.find.return_value = TYPES
    monkeypatch.setattr(access_payloads, 'assignment_reference_problems', lambda *_args: [])
    monkeypatch.setattr(access_payloads, 'assignment_taken', lambda *_args: None)

    return {'roles': roles, 'types': types}


def _payload(managers: dict[str, MagicMock], assignment: dict[str, Any], sent: dict[str, Any] | None = None,
             with_types: bool = True) -> dict[str, Any]:
    """assignment_payload with the stand-ins"""
    return access_payloads.assignment_payload(MagicMock(), MagicMock(), managers['roles'], assignment, sent=sent,
                                              types=managers['types'] if with_types else None)


@pytest.mark.parametrize('sent', [None, {'scope': SENT_SCOPE}, {'role_id': 4}], ids=['create', 'scope', 'role'])
def test_the_scope_is_judged_and_stored_cast(managers: dict[str, MagicMock], sent: Any) -> None:
    """A create, an update sending the scope or the role"""
    assert _payload(managers, ASSIGNMENT, sent)['scope'] == CAST_SCOPE
    managers['types'].find.assert_called_once()


def test_an_update_sending_neither_does_not_rejudge(managers: dict[str, MagicMock]) -> None:
    """A description change reads no Type"""
    assert _payload(managers, {**ASSIGNMENT, 'scope': CAST_SCOPE}, {'description': 'x'})['scope'] == CAST_SCOPE
    managers['types'].find.assert_not_called()


def test_without_types_no_scope_is_judged(managers: dict[str, MagicMock]) -> None:
    """An internal caller"""
    _payload(managers, ASSIGNMENT, with_types=False)

    managers['roles'].get_item.assert_not_called()


def test_a_problem_is_part_of_the_one_400(managers: dict[str, MagicMock]) -> None:
    """Named by the compiler"""
    with pytest.raises(BadRequest) as caught:
        _payload(managers, {**ASSIGNMENT, 'scope': [{'field': 'gone', 'op': 'exists'}]})

    assert caught.value.description == ScopeMessage.NO_CARRIER.value.format(field='gone')


def test_checked_scope_answers_the_stored_form(managers: dict[str, MagicMock]) -> None:
    """Nothing written - no manager write called"""
    assert access_payloads.checked_scope(managers['roles'], managers['types'], 4, SENT_SCOPE) == CAST_SCOPE
    assert not [call for call in managers['roles'].mock_calls if 'insert' in str(call) or 'update' in str(call)]


def test_checked_scope_refuses_a_missing_role(managers: dict[str, MagicMock]) -> None:
    """Before any Type read"""
    managers['roles'].get_item.return_value = None

    with patch.object(access_payloads, 'judge_scope') as judged, pytest.raises(BadRequest) as caught:
        access_payloads.checked_scope(managers['roles'], managers['types'], 9, '*')

    assert caught.value.description == AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=9)
    judged.assert_not_called()
