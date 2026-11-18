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
Functional tests: what an LDAP login does to a stored user's groups - through `POST /auth/login`, on real data

The auth section is stored with LDAP and group mapping on; only the directory (`ldap3`'s Server / Connection) is
replaced, answering the user's DN and the directory groups each test names. Pinned:

  - every mapping row matching a directory group gives its group - provisioned with all of them
  - a login replaces the mapping-managed groups (every group a row names, and the default group) and keeps a group
    assigned by hand
  - the bootstrap administrator never loses the administrator group to a mapping; the login goes on
  - the login answer's `effective_rights` are those of the synced groups
"""
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.group_model import ADMIN_GROUP_ID, CmdbUserGroup
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.responses.login_response import EFFECTIVE_RIGHTS_KEY
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROVIDER_PATH: str = 'cmdb.security.auth.providers.ldap_auth_provider'

USER_NAME: str = 'ldap-sync-user'
PASSWORD: str = 'directory-secret'
USER_DN: str = f'uid={USER_NAME},ou=people,dc=example,dc=com'
STAFF_DN: str = 'cn=staff,ou=groups,dc=example,dc=com'
OPS_DN: str = 'cn=ops,ou=groups,dc=example,dc=com'
ADMINS_DN: str = 'cn=admins,ou=groups,dc=example,dc=com'

STAFF_GROUP_ID: int = 94571
OPS_GROUP_ID: int = 94572
DEFAULT_GROUP_ID: int = 94573
HAND_GROUP_ID: int = 94574
GROUP_IDS: list[int] = [STAFF_GROUP_ID, OPS_GROUP_ID, DEFAULT_GROUP_ID, HAND_GROUP_ID]
GROUP_RIGHTS: dict[int, list[str]] = {
    STAFF_GROUP_ID: [TypeRight.VIEW.value],
    OPS_GROUP_ID: [ObjectRightName.VIEW.value],
    DEFAULT_GROUP_ID: [],
    HAND_GROUP_ID: [],
}
MAPPING: list[dict[str, Any]] = [
    {'group_dn': STAFF_DN, 'group_id': STAFF_GROUP_ID},
    {'group_dn': OPS_DN, 'group_id': OPS_GROUP_ID},
    {'group_dn': ADMINS_DN, 'group_id': ADMIN_GROUP_ID},
]
BOOTSTRAP_USER_NAME: str = 'admin'


def _section() -> dict[str, Any]:
    """LDAP on with group mapping, beside the local provider"""
    ldap_config: dict[str, Any] = {
        **deepcopy(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES), 'active': True,
        'default_group': DEFAULT_GROUP_ID,
        'search': {'basedn': 'dc=example,dc=com', 'searchfilter': '(uid=%username%)'},
        'groups': {'active': True, 'searchfiltergroup': '(memberUid=%username%)', 'mapping': MAPPING},
    }

    return {'enable_external': True, 'token_lifetime': 60, 'providers': [
        {'class_name': LocalAuthenticationProvider.get_name(), 'config': {'active': True}},
        {'class_name': LdapAuthenticationProvider.get_name(), 'config': ldap_config},
    ]}


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str) -> Any:
    """The stored auth section, the four groups; the test user and the section restored afterwards"""
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    section_before = settings.find_one({'_id': AUTH_SETTINGS_ID})
    bootstrap_before: dict[str, Any] = users.find_one({'public_id': CmdbUser.ADMIN_PUBLIC_ID})

    def _purge() -> None:
        users.delete_many({'user_name': USER_NAME})
        groups.delete_many({'public_id': {'$in': GROUP_IDS}})

    _purge()
    settings.replace_one({'_id': AUTH_SETTINGS_ID}, {'_id': AUTH_SETTINGS_ID, **_section()}, upsert=True)
    groups.insert_many([{'public_id': group_id, 'name': f'ldap-sync-{group_id}', 'label': 'LDAP sync',
                         'rights': rights} for group_id, rights in GROUP_RIGHTS.items()])

    yield users

    _purge()
    users.replace_one({'public_id': CmdbUser.ADMIN_PUBLIC_ID}, bootstrap_before)

    if section_before is None:
        settings.delete_one({'_id': AUTH_SETTINGS_ID})
    else:
        settings.replace_one({'_id': AUTH_SETTINGS_ID}, section_before)


def _ldap_login(rest_api: Any, user_name: str, directory_groups: list[str]) -> Any:
    """POST /auth/login with the directory answering the user's DN, then the given groups"""
    service = MagicMock(name='service_connection')
    service.bind.return_value = True
    searches: SimpleNamespace = SimpleNamespace(count=0)

    def _search(*_args: Any, **_kwargs: Any) -> bool:
        searches.count += 1
        service.entries = ([SimpleNamespace(entry_dn=USER_DN)] if searches.count == 1
                           else [SimpleNamespace(entry_dn=dn) for dn in directory_groups])
        return True

    service.search.side_effect = _search

    with patch(f'{PROVIDER_PATH}.Server'), \
         patch(f'{PROVIDER_PATH}.Connection', side_effect=lambda *args, **_kw: service if len(args) == 1
               else MagicMock(name='user_connection')):
        return rest_api.post(LOGIN_URL, json={'user_name': user_name, 'password': PASSWORD}, unauthorized=True)


def _store(users: Any, group_ids: list[int]) -> None:
    """The test user, stored as an LDAP user in the given groups"""
    users.insert_one({'public_id': 94581, 'user_name': USER_NAME, 'active': True, 'group_ids': group_ids,
                      'authenticator': LdapAuthenticationProvider.get_name(),
                      'registration_time': datetime.now(timezone.utc)})


def _groups_of(users: Any, user_name: str) -> list[int]:
    """The stored group list"""
    return users.find_one({'user_name': user_name})['group_ids']


def test_a_new_user_is_provisioned_into_every_mapped_group(rest_api, users) -> None:
    """Two matching rows: both groups, and the login answers the rights of both"""
    response = _ldap_login(rest_api, USER_NAME, [STAFF_DN, OPS_DN])

    assert response.status_code == HTTPStatus.OK
    assert _groups_of(users, USER_NAME) == [STAFF_GROUP_ID, OPS_GROUP_ID]
    assert {right['name'] for right in response.get_json()[EFFECTIVE_RIGHTS_KEY]} == \
        {TypeRight.VIEW.value, ObjectRightName.VIEW.value}


def test_a_login_replaces_the_managed_groups_and_keeps_a_hand_assigned_one(rest_api, users) -> None:
    """The default group goes for the mapped one; the group no row names stays"""
    _store(users, [DEFAULT_GROUP_ID, HAND_GROUP_ID])

    assert _ldap_login(rest_api, USER_NAME, [OPS_DN]).status_code == HTTPStatus.OK
    assert _groups_of(users, USER_NAME) == [OPS_GROUP_ID, HAND_GROUP_ID]


def test_a_group_the_directory_no_longer_gives_goes(rest_api, users) -> None:
    """No matching row any more: the default group, the hand-assigned one kept"""
    _store(users, [STAFF_GROUP_ID, HAND_GROUP_ID])

    assert _ldap_login(rest_api, USER_NAME, []).status_code == HTTPStatus.OK
    assert _groups_of(users, USER_NAME) == [DEFAULT_GROUP_ID, HAND_GROUP_ID]


def test_the_bootstrap_administrator_keeps_the_administrator_group(rest_api, users) -> None:
    """A row maps the admins group to group 1, and the directory gives none: user 1 keeps it, the login goes on"""
    users.update_one({'public_id': CmdbUser.ADMIN_PUBLIC_ID},
                     {'$set': {'authenticator': LdapAuthenticationProvider.get_name()}})

    assert _ldap_login(rest_api, BOOTSTRAP_USER_NAME, []).status_code == HTTPStatus.OK
    assert _groups_of(users, BOOTSTRAP_USER_NAME) == [ADMIN_GROUP_ID, DEFAULT_GROUP_ID]
