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
Unit tests for cmdb.framework.access_engine.access_grants_reads

Past MagicMock managers and a stubbed ManagerProvider: the three reads each answer feeds its own part of the grants;
within a request the grants are read once per tenant + group ids - another tenant or membership reads again, a failed
read is not kept, forget_grants drops them; outside a request every call reads
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

from cmdb.framework.access_engine import access_grants_reads
from cmdb.framework.access_engine import (
    AccessGrants,
    TypeSet,
    forget_grants,
    grants_cache_key,
    load_access_rules,
    load_grants,
    read_grants,
)
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.access_model import ScopeOperation
from cmdb.models.user_model import CmdbUser
from cmdb.errors.manager.access_assignments_manager import AccessAssignmentsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 51
FIRST_GROUP_ID: int = 21
SECOND_GROUP_ID: int = 22
OTHER_GROUP_ID: int = 23
OWN_ROLE_ID: int = 31
OTHER_ROLE_ID: int = 32
OWN_TYPE_ID: int = 11
OTHER_TYPE_ID: int = 12
OWN_ASSIGNMENT_ID: int = 41
TENANT: str = 'tenant-a'
OTHER_TENANT: str = 'tenant-b'

OWN_ASSIGNMENT: dict[str, Any] = {'public_id': OWN_ASSIGNMENT_ID, 'group_id': FIRST_GROUP_ID, 'role_id': OWN_ROLE_ID,
                                  'scope': '*', 'description': ''}
OWN_ROLE: dict[str, Any] = {'public_id': OWN_ROLE_ID, 'types': [OWN_TYPE_ID], 'operations': ['view'],
                            'write_regular_fields': True, 'field_classes': []}
OTHER_ROLE: dict[str, Any] = {'public_id': OTHER_ROLE_ID, 'types': [OTHER_TYPE_ID], 'operations': ['edit'],
                              'write_regular_fields': True, 'field_classes': []}


def _managers() -> tuple[MagicMock, MagicMock]:
    """An assignments manager answering the user's assignment and both assigned roles, a roles manager both roles"""
    assignments = MagicMock()
    assignments.assignments_of_groups.return_value = [OWN_ASSIGNMENT]
    assignments.assigned_role_ids.return_value = [OWN_ROLE_ID, OTHER_ROLE_ID]
    roles = MagicMock()
    roles.roles_by_ids.return_value = [OWN_ROLE, OTHER_ROLE]

    return assignments, roles


def _user(group_ids: list[int], database: str = TENANT) -> CmdbUser:
    """A user in the given groups"""
    return CmdbUser(public_id=USER_ID, user_name='reader', active=True, group_ids=group_ids, database=database)


class TestReadGrants:
    """read_grants"""

    def test_each_read_feeds_its_part(self) -> None:
        """The user's assignment grants, the other role only restricts"""
        assignments, roles = _managers()

        grants: AccessGrants = read_grants(assignments, roles, [SECOND_GROUP_ID, FIRST_GROUP_ID, FIRST_GROUP_ID])

        assignments.assignments_of_groups.assert_called_once_with([FIRST_GROUP_ID, SECOND_GROUP_ID])
        roles.roles_by_ids.assert_called_once_with([OWN_ROLE_ID, OTHER_ROLE_ID])
        assert grants.restricted == TypeSet.of([OWN_TYPE_ID, OTHER_TYPE_ID])
        assert grants.allows(ScopeOperation.VIEW, OWN_TYPE_ID)
        assert not grants.allows(ScopeOperation.EDIT, OTHER_TYPE_ID)
        assert grants.granting_assignment_ids(ScopeOperation.VIEW, OWN_TYPE_ID) == [OWN_ASSIGNMENT_ID]


@pytest.fixture(name='provider')
def fixture_provider(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A ManagerProvider answering the user's database as the tenant and fresh mock managers"""
    assignments, roles = _managers()
    provider = MagicMock()
    provider.tenant_database.side_effect = lambda user: user.database
    provider.get_manager.side_effect = lambda kind, _user: {ManagerType.ACCESS_ASSIGNMENTS: assignments,
                                                            ManagerType.SCOPE_ROLES: roles}[kind]
    monkeypatch.setattr(access_grants_reads, 'ManagerProvider', provider)

    return {'assignments': assignments, 'roles': roles}


def _reads(provider: dict[str, Any]) -> int:
    """How often the grants were read"""
    return provider['assignments'].assignments_of_groups.call_count


class TestLoadGrants:
    """load_grants + forget_grants"""

    def test_read_once_per_request(self, provider: dict[str, Any]) -> None:
        """The second ask answers the kept grants"""
        with Flask(__name__).test_request_context('/'):
            first: AccessGrants = load_grants(_user([FIRST_GROUP_ID]))

            assert load_grants(_user([FIRST_GROUP_ID])) is first
            assert _reads(provider) == 1

    @pytest.mark.parametrize('other', [_user([FIRST_GROUP_ID], OTHER_TENANT), _user([OTHER_GROUP_ID])],
                             ids=['other-tenant', 'other-groups'])
    def test_another_tenant_or_membership_reads_again(self, provider: dict[str, Any], other: CmdbUser) -> None:
        """Never answered from another key"""
        with Flask(__name__).test_request_context('/'):
            load_grants(_user([FIRST_GROUP_ID]))
            load_grants(other)

            assert _reads(provider) == 2

    def test_the_group_order_does_not_matter(self, provider: dict[str, Any]) -> None:
        """Sorted, each once"""
        with Flask(__name__).test_request_context('/'):
            load_grants(_user([FIRST_GROUP_ID, SECOND_GROUP_ID]))
            load_grants(_user([SECOND_GROUP_ID, FIRST_GROUP_ID, SECOND_GROUP_ID]))

            assert _reads(provider) == 1

    def test_a_failed_read_is_not_kept(self, provider: dict[str, Any]) -> None:
        """It raises, and the next ask reads again"""
        provider['assignments'].assignments_of_groups.side_effect = [AccessAssignmentsManagerGetError('down'),
                                                                     [OWN_ASSIGNMENT]]

        with Flask(__name__).test_request_context('/'):
            with pytest.raises(AccessAssignmentsManagerGetError):
                load_grants(_user([FIRST_GROUP_ID]))

            assert load_grants(_user([FIRST_GROUP_ID])).allows(ScopeOperation.VIEW, OWN_TYPE_ID)
            assert _reads(provider) == 2

    def test_forget_grants_drops_them(self, provider: dict[str, Any]) -> None:
        """A changed assignment is read again in the same request"""
        with Flask(__name__).test_request_context('/'):
            load_grants(_user([FIRST_GROUP_ID]))
            forget_grants()
            load_grants(_user([FIRST_GROUP_ID]))

            assert _reads(provider) == 2

    def test_outside_a_request_every_call_reads(self, provider: dict[str, Any]) -> None:
        """Nothing kept; forgetting is harmless"""
        load_grants(_user([FIRST_GROUP_ID]))
        load_grants(_user([FIRST_GROUP_ID]))
        forget_grants()

        assert _reads(provider) == 2


@pytest.mark.usefixtures('provider')
def test_the_cache_key() -> None:
    """Tenant + sorted unique group ids"""
    assert grants_cache_key(_user([SECOND_GROUP_ID, FIRST_GROUP_ID, SECOND_GROUP_ID])) == (
        TENANT, (FIRST_GROUP_ID, SECOND_GROUP_ID))


class TestLoadAccessRules:
    """load_access_rules - every assignment with its roles, kept beside the grants"""

    @staticmethod
    def _every(provider: dict[str, Any]) -> list[dict[str, Any]]:
        """Every assignment answered: the user's and another group's"""
        every: list[dict[str, Any]] = [OWN_ASSIGNMENT, {**OWN_ASSIGNMENT, 'public_id': 42, 'group_id': OTHER_GROUP_ID,
                                                        'role_id': OTHER_ROLE_ID}]
        provider['assignments'].all_assignments.return_value = every

        return every

    def test_every_assignment_and_the_roles_they_name(self, provider: dict[str, Any]) -> None:
        """Two reads; the role ids ascending, each once"""
        every = self._every(provider)

        rules = load_access_rules(_user([FIRST_GROUP_ID]))

        provider['roles'].roles_by_ids.assert_called_once_with([OWN_ROLE_ID, OTHER_ROLE_ID])
        assert rules == (every, [OWN_ROLE, OTHER_ROLE])

    def test_read_once_per_request_and_tenant_whatever_the_groups(self, provider: dict[str, Any]) -> None:
        """Another membership answers the kept rules; another tenant reads again"""
        self._every(provider)

        with Flask(__name__).test_request_context('/'):
            first = load_access_rules(_user([FIRST_GROUP_ID]))

            assert load_access_rules(_user([OTHER_GROUP_ID])) is first
            load_access_rules(_user([FIRST_GROUP_ID], OTHER_TENANT))
            assert provider['assignments'].all_assignments.call_count == 2

    def test_forget_grants_drops_them_too(self, provider: dict[str, Any]) -> None:
        """An access write in the request reads them again"""
        self._every(provider)

        with Flask(__name__).test_request_context('/'):
            load_access_rules(_user([FIRST_GROUP_ID]))
            forget_grants()
            load_access_rules(_user([FIRST_GROUP_ID]))

            assert provider['assignments'].all_assignments.call_count == 2

    def test_kept_apart_from_a_users_grants(self, provider: dict[str, Any]) -> None:
        """The grants of the same tenant are another entry"""
        self._every(provider)

        with Flask(__name__).test_request_context('/'):
            load_grants(_user([FIRST_GROUP_ID]))
            rules = load_access_rules(_user([FIRST_GROUP_ID]))

            assert isinstance(rules, tuple) and _reads(provider) == 1
