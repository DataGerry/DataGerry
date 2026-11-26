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
Unit tests for access_routes.access_delegation

Pure: the right check, the role read and the grants are stand-ins; the rule is the real one on a patched grants
object where needed. Pinned: who writes as a delegate; a delegate's roles judged in order, a missing one skipped, the
first beyond refused; an editor and an administrator read nothing; the roles a caller may hand out
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.access_routes import access_delegation
from cmdb.interface.rest_api.routes.access_routes.access_delegation import (
    abort_unless_delegable,
    delegable_role_ids,
    delegates_only,
)
# -------------------------------------------------------------------------------------------------------------------- #

DELEGATE: CmdbUser = CmdbUser(public_id=71, user_name='delegate', active=True, group_ids=[21])
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=72, user_name='admin', active=True, group_ids=[21, 1])
WITHIN_ROLE: dict[str, Any] = {'public_id': 31, 'types': [5], 'operations': ['view']}
BEYOND_ROLE: dict[str, Any] = {'public_id': 32, 'types': [6], 'operations': ['edit']}
PROBLEM: str = 'beyond'


@pytest.fixture(name='reads')
def fixture_reads(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """No edit right; the two roles stored; the rule refusing the beyond role only"""
    has_right = MagicMock(return_value=False)
    roles_manager = MagicMock()
    roles_manager.roles_by_ids.return_value = [WITHIN_ROLE, BEYOND_ROLE]
    provider = MagicMock()
    provider.get_manager.return_value = roles_manager
    load = MagicMock(return_value='grants')
    rule = MagicMock(side_effect=lambda _grants, role_id, _role:
                     PROBLEM if role_id == BEYOND_ROLE['public_id'] else None)
    reach = MagicMock(side_effect=lambda _grants, role: ['x'] if role is BEYOND_ROLE else [])
    monkeypatch.setattr(access_delegation, 'user_has_right', has_right)
    monkeypatch.setattr(access_delegation, 'ManagerProvider', provider)
    monkeypatch.setattr(access_delegation, 'load_grants', load)
    monkeypatch.setattr(access_delegation, 'delegation_problem', rule)
    monkeypatch.setattr(access_delegation, 'beyond_reach', reach)

    return {'has_right': has_right, 'roles': roles_manager, 'load': load, 'rule': rule}


class TestDelegatesOnly:
    """Who the delegation rule judges"""

    @pytest.mark.parametrize('user, holds_edit, expected', [
        (DELEGATE, False, True), (DELEGATE, True, False), (ADMINISTRATOR, False, False),
    ], ids=['delegate', 'editor', 'administrator'])
    def test_the_rule_judges_delegates_only(self, reads: dict[str, MagicMock], user: CmdbUser, holds_edit: bool,
                                            expected: bool) -> None:
        """The edit right or the administrator group lifts it"""
        reads['has_right'].return_value = holds_edit

        assert delegates_only(user) is expected


class TestAbortUnlessDelegable:
    """A delegate's write: every role before and after"""

    def test_within_reach_passes(self, reads: dict[str, MagicMock]) -> None:
        """The same role twice is judged once"""
        abort_unless_delegable(DELEGATE, [WITHIN_ROLE['public_id'], WITHIN_ROLE['public_id']])

        reads['rule'].assert_called_once_with('grants', WITHIN_ROLE['public_id'], WITHIN_ROLE)

    @pytest.mark.parametrize('role_ids', [[32, 31], [31, 32]], ids=['before-beyond', 'after-beyond'])
    def test_a_role_beyond_on_either_side_is_a_403(self, reads: dict[str, MagicMock], role_ids: list[int]) -> None:
        """An update changing a role beyond into one within is refused too"""
        with pytest.raises(HTTPException) as raised:
            abort_unless_delegable(DELEGATE, role_ids)

        assert (raised.value.code, raised.value.description) == (HTTPStatus.FORBIDDEN, PROBLEM)

    def test_a_missing_role_is_skipped(self, reads: dict[str, MagicMock]) -> None:
        """The reference rules refuse it"""
        reads['roles'].roles_by_ids.return_value = []

        abort_unless_delegable(DELEGATE, [99])

        reads['rule'].assert_not_called()

    @pytest.mark.parametrize('user, holds_edit, role_ids', [
        (DELEGATE, True, [32]), (ADMINISTRATOR, False, [32]), (DELEGATE, False, []),
    ], ids=['editor', 'administrator', 'no-role'])
    def test_reads_nothing(self, reads: dict[str, MagicMock], user: CmdbUser, holds_edit: bool,
                           role_ids: list[int]) -> None:
        """Not a delegate, or nothing to judge"""
        reads['has_right'].return_value = holds_edit

        abort_unless_delegable(user, role_ids)

        reads['roles'].roles_by_ids.assert_not_called()
        reads['load'].assert_not_called()


class TestDelegableRoleIds:
    """The within_reach list"""

    def test_a_caller_gets_the_roles_within_reach(self, reads: dict[str, MagicMock]) -> None:
        """Ascending ids"""
        assert delegable_role_ids(DELEGATE, [BEYOND_ROLE, WITHIN_ROLE]) == [WITHIN_ROLE['public_id']]

    def test_an_administrator_gets_every_role(self, reads: dict[str, MagicMock]) -> None:
        """No grants read"""
        assert delegable_role_ids(ADMINISTRATOR, [BEYOND_ROLE, WITHIN_ROLE]) == [31, 32]
        reads['load'].assert_not_called()
