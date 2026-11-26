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
Unit tests for access_routes.access_scope_guard - the route side of the stale-scope rules (phase 9 step 3, R11)

Pure: the managers are stand-ins. Pinned: with no conditional assignment nothing more is read and nothing refused;
only assignments whose role covers the Type are judged (a role on every Type covers it); the Type blocker joins the
problems; the role guard reads the new Types (every Type for '*') only for a role with conditional assignments
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model import CmdbType
from cmdb.framework.scope_compiler import ScopeMessage
from cmdb.interface.rest_api.routes.access_routes import access_scope_guard as guard
from cmdb.interface.rest_api.routes.access_routes.access_scope_guard import (
    guard_role_scope_change,
    scope_field_change_blocker,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 5
SCOPE: list[dict[str, Any]] = [{'field': 'host', 'op': 'exists'}]
COVERING: dict[str, Any] = {'public_id': 11, 'group_id': 1, 'role_id': 21, 'scope': SCOPE}
EVERY_TYPE: dict[str, Any] = {'public_id': 12, 'group_id': 1, 'role_id': 22, 'scope': SCOPE}
ELSEWHERE: dict[str, Any] = {'public_id': 13, 'group_id': 1, 'role_id': 23, 'scope': SCOPE}


def _type(*fields: dict[str, Any]) -> CmdbType:
    """A Type stand-in with the fields and no multi-data section"""
    a_type = MagicMock(spec=CmdbType)
    a_type.public_id = TYPE_ID
    a_type.get_fields.return_value = list(fields)
    a_type.get_all_mds_fields.return_value = []

    return a_type


@pytest.fixture(name='managers')
def fixture_managers(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Three conditional assignments: a role on the Type, one on every Type, one elsewhere"""
    assignments, roles, types = MagicMock(), MagicMock(), MagicMock()
    assignments.conditional_assignments.return_value = [COVERING, EVERY_TYPE, ELSEWHERE]
    roles.roles_by_ids.return_value = [{'public_id': 21, 'types': [TYPE_ID]}, {'public_id': 22, 'types': '*'},
                                       {'public_id': 23, 'types': [99]}]
    types.find.return_value = [{'public_id': 99, 'fields': [{'name': 'other', 'type': 'text'}]}]
    managers = {'ACCESS_ASSIGNMENTS': assignments, 'SCOPE_ROLES': roles, 'TYPES': types}
    provider = MagicMock()
    provider.get_manager.side_effect = lambda manager_type, _user: managers[manager_type.name]
    monkeypatch.setattr(guard, 'ManagerProvider', provider)

    return managers


def test_removing_a_compared_field_names_the_covering_assignments(managers: dict[str, MagicMock]) -> None:
    """The role on every Type covers it too; the one elsewhere does not"""
    blocker = scope_field_change_blocker(MagicMock(), _type({'name': 'host', 'type': 'text'}), _type())

    assert blocker == ScopeMessage.STALE_ON_TYPE.value.format(field='host', type_id=TYPE_ID, assignment_ids=[11, 12])


def test_no_conditional_assignment_reads_nothing_more(managers: dict[str, MagicMock]) -> None:
    """The common case"""
    managers['ACCESS_ASSIGNMENTS'].conditional_assignments.return_value = []

    assert scope_field_change_blocker(MagicMock(), _type({'name': 'host', 'type': 'text'}), _type()) is None
    managers['SCOPE_ROLES'].roles_by_ids.assert_not_called()


def test_a_role_update_leaving_no_carrier_is_refused(managers: dict[str, MagicMock]) -> None:
    """Its new Types read by id"""
    with pytest.raises(HTTPException) as raised:
        guard_role_scope_change(MagicMock(), 23, {'types': [99]})

    assert raised.value.code == HTTPStatus.BAD_REQUEST
    assert ScopeMessage.NO_CARRIER.value.format(field='host') in raised.value.description
    assert managers['TYPES'].find.call_args.kwargs['criteria'] == {'public_id': {'$in': [99]}}


def test_a_role_on_every_type_reads_every_type(managers: dict[str, MagicMock]) -> None:
    """No criteria"""
    with pytest.raises(HTTPException):
        guard_role_scope_change(MagicMock(), 23, {'types': '*'})

    assert managers['TYPES'].find.call_args.kwargs['criteria'] == {}


def test_a_role_without_conditional_assignments_reads_no_type(managers: dict[str, MagicMock]) -> None:
    """Nothing to judge"""
    guard_role_scope_change(MagicMock(), 77, {'types': [99]})

    managers['TYPES'].find.assert_not_called()
