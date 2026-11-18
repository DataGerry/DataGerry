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
Integration tests for the LDAP group sync's administrator rule against a real MongoDB

A mapping row names the administrator group and the directory no longer gives it. Whether the user keeps it depends
on the stored administrators, counted for real (`UsersManager.has_other_active_member`): the last active one keeps
it, a user beside another active administrator loses it. Only the directory is replaced
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import UsersManager
from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

PROVIDER_PATH: str = 'cmdb.security.auth.providers.ldap_auth_provider'
USER_ID: int = 94591
USER_NAME: str = 'ldap-admin-sync'
USER_DN: str = f'uid={USER_NAME},dc=example,dc=com'
DEFAULT_GROUP_ID: int = 2
ADMINS_DN: str = 'cn=admins,dc=example,dc=com'


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """An LDAP administrator; every other administrator's `active` flag restored afterwards"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({'public_id': USER_ID, 'user_name': USER_NAME, 'active': True, 'group_ids': [ADMIN_GROUP_ID],
                      'authenticator': LdapAuthenticationProvider.get_name(),
                      'registration_time': datetime.now(timezone.utc)})
    other_admins: dict[int, bool] = {user['public_id']: user['active'] for user in
                                     users.find({'group_ids': ADMIN_GROUP_ID, 'public_id': {'$ne': USER_ID}})}

    yield users

    users.delete_many({'public_id': USER_ID})

    for public_id, active in other_admins.items():
        users.update_one({'public_id': public_id}, {'$set': {'active': active}})


def _login(database_manager: MongoDatabaseManager) -> CmdbUser:
    """An LDAP login of the test user, the directory giving no group"""
    config = LdapAuthenticationProviderConfig(
        active=True, default_group=DEFAULT_GROUP_ID,
        search={'basedn': 'dc=example,dc=com', 'searchfilter': '(uid=%username%)'},
        groups={'active': True, 'searchfiltergroup': '(memberUid=%username%)',
                'mapping': [{'group_dn': ADMINS_DN, 'group_id': ADMIN_GROUP_ID}]},
    )
    service = MagicMock(name='service_connection')
    service.bind.return_value = True
    searches: SimpleNamespace = SimpleNamespace(count=0)

    def _search(*_args: Any, **_kwargs: Any) -> bool:
        searches.count += 1
        service.entries = [SimpleNamespace(entry_dn=USER_DN)] if searches.count == 1 else []
        return True

    service.search.side_effect = _search

    with patch(f'{PROVIDER_PATH}.Server'), \
         patch(f'{PROVIDER_PATH}.Connection', side_effect=lambda *args, **_kw: service if len(args) == 1
               else MagicMock(name='user_connection')):
        provider = LdapAuthenticationProvider(config=config, security_manager=MagicMock(),
                                              users_manager=UsersManager(database_manager))

        return provider.authenticate(USER_NAME, 'directory-secret')


@pytest.mark.usefixtures('rest_api_app_context')
def test_the_last_active_administrator_keeps_the_group(database_manager: MongoDatabaseManager, users) -> None:
    """Every other administrator deactivated: the group stays, the default group is added"""
    users.update_many({'group_ids': ADMIN_GROUP_ID, 'public_id': {'$ne': USER_ID}}, {'$set': {'active': False}})

    assert _login(database_manager).group_ids == [ADMIN_GROUP_ID, DEFAULT_GROUP_ID]
    assert users.find_one({'public_id': USER_ID})['group_ids'] == [ADMIN_GROUP_ID, DEFAULT_GROUP_ID]


@pytest.mark.usefixtures('rest_api_app_context')
def test_beside_another_active_administrator_the_group_goes(database_manager: MongoDatabaseManager, users) -> None:
    """The seeded bootstrap administrator is active: the directory decides"""
    assert _login(database_manager).group_ids == [DEFAULT_GROUP_ID]
    assert users.find_one({'public_id': USER_ID})['group_ids'] == [DEFAULT_GROUP_ID]
