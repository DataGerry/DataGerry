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
Unit tests: the users written by a sign-in are synced - LDAP and the hosted cloud's admin set-up

Pinned: the LDAP group update and the LDAP provisioning, and the cloud admin's create and update, each hand the stored
user to ``sync_user_outside_request`` on the user's tenant
"""
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
import cmdb.interface.cloud_user_helper as cloud_user_helper
from tests.utils.cmdb_app_stub import stub_cmdb_app
# -------------------------------------------------------------------------------------------------------------------- #

LDAP_PATH: str = 'cmdb.security.auth.providers.ldap_auth_provider'
CLOUD_PATH: str = 'cmdb.interface.cloud_user_helper'
USER: CmdbUser = CmdbUser(public_id=7, user_name='ann', active=True, group_ids=[2])
TENANT: str = 'tenant-db'
SUBSCRIPTION: dict[str, Any] = {'database': TENANT, 'api_level': 1, 'config_item_limit': 10}
USER_DATA: dict[str, Any] = {'email': 'a@test.com', 'user_name': 'admin', 'password': 'digest'}


def _ldap_provider() -> LdapAuthenticationProvider:
    """A provider whose only collaborator is a mocked users manager"""
    provider = LdapAuthenticationProvider.__new__(LdapAuthenticationProvider)
    provider.users_manager = MagicMock(db_name=TENANT)

    return provider


def test_the_ldap_group_update_syncs_the_user() -> None:
    """After its groups are stored"""
    provider = _ldap_provider()

    with patch(f'{LDAP_PATH}.sync_user_outside_request') as sync:
        provider._apply_mapped_groups(USER, [3])  # pylint: disable=protected-access

    sync.assert_called_once_with(provider.users_manager.dbm, TENANT, USER)
    assert USER.group_ids == [3]


def test_the_ldap_provisioning_syncs_the_new_user() -> None:
    """The user as read back"""
    provider = _ldap_provider()
    provider.users_manager.get_user.return_value = USER

    with patch(f'{LDAP_PATH}.sync_user_outside_request') as sync:
        provider._provision_user('ann', [2])  # pylint: disable=protected-access

    sync.assert_called_once_with(provider.users_manager.dbm, TENANT, USER)


def test_the_cloud_admin_create_and_update_sync_the_admin() -> None:
    """On the subscription's tenant, the admin as written"""
    users_manager = MagicMock()
    users_manager.get_next_public_id.return_value = 41
    app = stub_cmdb_app()

    for stored in (None, CmdbUser(public_id=41, user_name='admin', active=True)):
        users_manager.get_user_by.return_value = stored

        with patch(f'{CLOUD_PATH}.UsersManager', return_value=users_manager), \
             patch(f'{CLOUD_PATH}.sync_user_outside_request') as sync, app.test_request_context():
            cloud_user_helper.set_admin_user(USER_DATA, SUBSCRIPTION)

        database_manager, tenant, admin = sync.call_args.args
        assert (database_manager, tenant, admin.public_id) == (app.database_manager, TENANT, 41)
