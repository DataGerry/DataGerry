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
Integration tests for LDAP in cloud mode, against an auth section stored in MongoDB

The stored section activates LDAP - as a tenant may still hold it from before the auth-settings update refused
that in cloud mode. A cloud login with that section never asks LDAP: a tenant user identified by email still logs
in through the local provider, an unknown login is refused without provisioning anyone, and a user stored as owned
by LDAP is refused too. On premise the same section hands an unknown login to LDAP, as it always did
"""
import base64
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager, UsersManager
from cmdb.manager.security_manager import SYMMETRIC_KEY_ENV_VAR
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.security.auth.auth_module import PROVIDER_CLASS_NAME_KEY, PROVIDER_CONFIG_KEY, PROVIDERS_KEY, AuthModule
from cmdb.security.auth.base_provider_config import PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

TENANT_USER_ID: int = 93971
DIRECTORY_USER_ID: int = 93972
TENANT_EMAIL: str = 'tenant-user@x.io'
DIRECTORY_EMAIL: str = 'directory-owned@x.io'
UNKNOWN_LOGIN: str = 'nobody-here@x.io'
PASSWORD: str = 'correct-horse'
GROUP_ID: int = 1
ALL_USER_IDS: list[int] = [TENANT_USER_ID, DIRECTORY_USER_ID]
# Hosted cloud mode reads its AES key from the environment
CLOUD_AES_KEY: bytes = b'k' * 32


@pytest.fixture(name='cloud_mode')
def fixture_cloud_mode() -> bool:
    """On premise unless a test class overrides it"""
    return False


@pytest.fixture(name='app')
def fixture_app(rest_api, monkeypatch: pytest.MonkeyPatch, cloud_mode: bool):
    """
    The REST app inside an application context, in the mode under test

    Set before any user is stored: cloud mode keys the password digest with the environment's AES key, so the
    stored digest and the login's must be computed in the same mode
    """
    monkeypatch.setattr(rest_api.application, 'cloud_mode', cloud_mode)

    if cloud_mode:
        monkeypatch.setenv(SYMMETRIC_KEY_ENV_VAR, base64.b64encode(CLOUD_AES_KEY).decode('ascii'))

    with rest_api.application.app_context():
        yield rest_api.application


@pytest.fixture(name='security_manager')
def fixture_security_manager(app, database_manager: MongoDatabaseManager, database_name: str):
    """Stores a local tenant user (email + password digest) and an LDAP-owned one; removes both afterwards"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
    security_manager = SecurityManager(database_manager)
    now: datetime = datetime.now(timezone.utc)
    users.insert_many([
        {
            'public_id': TENANT_USER_ID, 'user_name': 'tenant-user', 'email': TENANT_EMAIL, 'active': True,
            'group_id': GROUP_ID, 'database': database_name, 'registration_time': now,
            'authenticator': LocalAuthenticationProvider.get_name(),
            'password': security_manager.generate_hmac(PASSWORD),
        },
        {
            'public_id': DIRECTORY_USER_ID, 'user_name': DIRECTORY_EMAIL, 'email': DIRECTORY_EMAIL, 'active': True,
            'group_id': GROUP_ID, 'database': database_name, 'registration_time': now,
            'authenticator': LdapAuthenticationProvider.get_name(),
        },
    ])

    yield security_manager

    users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
    users.delete_many({'user_name': UNKNOWN_LOGIN})


@pytest.fixture(name='module')
def fixture_module(security_manager: SecurityManager, database_manager: MongoDatabaseManager,
                   database_name: str):
    """An AuthModule over a stored section that activates LDAP; the section is restored afterwards"""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_ID})
    settings_manager = SettingsManager(database_manager)

    section: dict[str, Any] = dict(AuthModule.__DEFAULT_SETTINGS__)
    section.pop('_id', None)
    section[PROVIDERS_KEY] = [
        {PROVIDER_CLASS_NAME_KEY: LocalAuthenticationProvider.get_name(), PROVIDER_CONFIG_KEY: {}},
        {PROVIDER_CLASS_NAME_KEY: LdapAuthenticationProvider.get_name(),
         PROVIDER_CONFIG_KEY: {PROVIDER_ACTIVE_KEY: True}},
    ]
    settings_manager.write(_id=AUTH_SETTINGS_ID, data=section)
    stored = settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__)

    yield AuthModule(stored, security_manager=security_manager, users_manager=UsersManager(database_manager))

    if before is None:
        collection.delete_one({'_id': AUTH_SETTINGS_ID})
    else:
        collection.replace_one({'_id': AUTH_SETTINGS_ID}, before, upsert=True)


@pytest.fixture(name='ldap_calls')
def fixture_ldap_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every login handed to LDAP; the directory answers with a stand-in user instead of connecting"""
    calls: list[str] = []

    def _authenticate(_self: Any, user_name: str, _password: str) -> CmdbUser:
        calls.append(user_name)
        return CmdbUser(public_id=DIRECTORY_USER_ID, user_name=user_name, active=True)

    monkeypatch.setattr(LdapAuthenticationProvider, 'authenticate', _authenticate)

    return calls


class TestCloudMode:
    """The stored section activates LDAP; the app runs in cloud mode"""

    @pytest.fixture(name='cloud_mode')
    def fixture_cloud_mode(self) -> bool:
        """This class runs in cloud mode"""
        return True

    def test_a_tenant_user_still_logs_in_locally(self, module: AuthModule, ldap_calls: list[str]) -> None:
        """The local provider is untouched by the rule: identified by email, checked by its digest"""
        assert module.login(TENANT_EMAIL, PASSWORD).public_id == TENANT_USER_ID
        assert not ldap_calls

    def test_an_unknown_login_is_refused_without_provisioning(
            self, module: AuthModule, ldap_calls: list[str], database_manager: MongoDatabaseManager,
            database_name: str) -> None:
        """The sweep would have handed it to LDAP; now nobody is asked and nobody is stored"""
        with pytest.raises(AuthenticationError):
            module.login(UNKNOWN_LOGIN, PASSWORD)

        assert not ldap_calls
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        assert users.count_documents({'user_name': UNKNOWN_LOGIN}) == 0

    def test_a_user_owned_by_ldap_is_refused(self, module: AuthModule, ldap_calls: list[str]) -> None:
        """Its own provider is not run, and the local provider refuses a user without a digest"""
        with pytest.raises(AuthenticationError):
            module.login(DIRECTORY_EMAIL, PASSWORD)

        assert not ldap_calls


class TestOnPremise:
    """The same stored section on premise, where LDAP is a supported provider"""

    def test_an_unknown_login_is_handed_to_ldap(self, app, module: AuthModule, ldap_calls: list[str]) -> None:
        """The contrast: the sweep asks LDAP, which answers for the directory user"""
        assert not app.cloud_mode

        assert module.login(UNKNOWN_LOGIN, PASSWORD).public_id == DIRECTORY_USER_ID
        assert ldap_calls == [UNKNOWN_LOGIN]
