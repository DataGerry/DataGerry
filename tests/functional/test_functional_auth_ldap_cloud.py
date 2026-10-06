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
Functional coverage of the rule that external providers (LDAP) are on-premise only

In hosted cloud mode the auth-settings update refuses a section that activates LDAP and still stores the rest
of it; on premise the same section is accepted. A cloud Basic-auth request never hands the login to LDAP, even
with LDAP active in the tenant's stored section, so no directory user is provisioned. And a cloud token that
names no tenant database is refused before any user is read
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings_constants import (
    AUTH_SETTINGS_ID,
    CLOUD_EXTERNAL_PROVIDER_MSG,
    AuthSettingsKey,
    ProviderEntryKey,
)
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.base_provider_config import PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.interface import route_utils
from tests.utils.cloud_mode import AUTHORIZATION_ENVIRON_KEY, cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

SETTINGS_URL: str = '/auth/settings'
PROTECTED_URL: str = '/types/?limit=1'

ADMIN_USER_ID: int = 93981
ADMIN_EMAIL: str = 'cloud-ldap-admin@x.io'
# The Basic login no tenant user carries, so only the fallback sweep could answer it
UNKNOWN_EMAIL: str = 'directory-only@x.io'
PASSWORD: str = 'portal-password'
CHANGED_TOKEN_LIFETIME: int = 90

LDAP_PROVIDER_NAME: str = LdapAuthenticationProvider.get_name()
NO_TENANT_TOKEN_MSG: str = 'The token names no tenant database!'


@pytest.fixture(name='settings_collection')
def fixture_settings_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The settings collection; the stored auth section is restored afterwards"""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_ID})

    yield collection

    if before is None:
        collection.delete_one({'_id': AUTH_SETTINGS_ID})
    else:
        collection.replace_one({'_id': AUTH_SETTINGS_ID}, before, upsert=True)


@pytest.fixture(name='cloud_admin')
def fixture_cloud_admin(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                        database_name: str, settings_collection):
    """A hosted-cloud app and a tenant administrator; yields the admin's request environ"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': ADMIN_USER_ID})
    users.insert_one({
        'public_id': ADMIN_USER_ID, 'user_name': 'cloud-ldap-admin', 'email': ADMIN_EMAIL, 'active': True,
        'group_id': 1, 'database': database_name, 'api_level': 3,
        'registration_time': datetime.now(timezone.utc),
    })

    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)

    yield cloud_auth_header(rest_api, ADMIN_USER_ID, database_name)

    users.delete_many({'public_id': ADMIN_USER_ID})


def _section(ldap_active: bool, token_lifetime: int | None = None) -> dict[str, Any]:
    """The whole stored auth section, with LDAP in the given state and optionally a new lifetime"""
    section: dict[str, Any] = dict(AuthModule.__DEFAULT_SETTINGS__)
    section[AuthSettingsKey.PROVIDERS.value] = [
        {
            ProviderEntryKey.CLASS_NAME.value: entry[ProviderEntryKey.CLASS_NAME.value],
            ProviderEntryKey.CONFIG.value: {
                **entry[ProviderEntryKey.CONFIG.value],
                **({PROVIDER_ACTIVE_KEY: ldap_active}
                   if entry[ProviderEntryKey.CLASS_NAME.value] == LDAP_PROVIDER_NAME else {}),
            },
        }
        for entry in AuthModule.__DEFAULT_SETTINGS__[AuthSettingsKey.PROVIDERS.value]
    ]

    if token_lifetime is not None:
        section[AuthSettingsKey.TOKEN_LIFETIME.value] = token_lifetime

    return section


def _stored_ldap_active(settings_collection) -> bool:
    """Whether the stored section activates LDAP"""
    stored = settings_collection.find_one({'_id': AUTH_SETTINGS_ID}) or {}

    return any(
        entry.get(ProviderEntryKey.CLASS_NAME.value) == LDAP_PROVIDER_NAME
        and entry.get(ProviderEntryKey.CONFIG.value, {}).get(PROVIDER_ACTIVE_KEY) is True
        for entry in stored.get(AuthSettingsKey.PROVIDERS.value, [])
    )


class TestAuthSettingsInCloudMode:
    """PUT /auth/settings in hosted cloud mode"""

    def test_activating_ldap_is_refused(self, rest_api, cloud_admin, settings_collection) -> None:
        """400 naming LDAP, and nothing is written"""
        settings_collection.delete_one({'_id': AUTH_SETTINGS_ID})

        response = rest_api.put(SETTINGS_URL, json=_section(ldap_active=True), environ_overrides=cloud_admin)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CLOUD_EXTERNAL_PROVIDER_MSG.format(names=LDAP_PROVIDER_NAME)
        assert settings_collection.find_one({'_id': AUTH_SETTINGS_ID}) is None

    def test_the_rest_of_the_section_stays_writable(self, rest_api, cloud_admin, settings_collection) -> None:
        """With LDAP off the token lifetime - which the tenant's tokens are issued with - is stored"""
        response = rest_api.put(
            SETTINGS_URL,
            json=_section(ldap_active=False, token_lifetime=CHANGED_TOKEN_LIFETIME),
            environ_overrides=cloud_admin,
        )

        assert response.status_code == HTTPStatus.OK
        stored = settings_collection.find_one({'_id': AUTH_SETTINGS_ID})
        assert stored[AuthSettingsKey.TOKEN_LIFETIME.value] == CHANGED_TOKEN_LIFETIME
        assert not _stored_ldap_active(settings_collection)


class TestAuthSettingsOnPremise:
    """The same section on premise, where LDAP is a supported provider"""

    def test_activating_ldap_is_accepted(self, rest_api, settings_collection) -> None:
        """200, and the stored section activates LDAP"""
        response = rest_api.put(SETTINGS_URL, json=_section(ldap_active=True))

        assert response.status_code == HTTPStatus.OK
        assert _stored_ldap_active(settings_collection)


class TestCloudLoginsNeverRunLdap:
    """A cloud Basic-auth request with LDAP active in the tenant's stored section"""

    def test_an_unknown_login_is_not_handed_to_ldap(
        self,
        rest_api,
        monkeypatch: pytest.MonkeyPatch,
        cloud_admin,
        settings_collection,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The portal accepts it, no tenant user carries it - and LDAP is never asked, so nobody is provisioned"""
        # Stored directly: the route refuses this section in cloud mode, an older tenant may still hold it
        settings_collection.replace_one({'_id': AUTH_SETTINGS_ID}, _section(ldap_active=True), upsert=True)
        portal_user: dict[str, Any] = {
            'email': UNKNOWN_EMAIL, 'database': database_name,
            'subscriptions': [{'id': 1, 'name': 'sub', 'database': database_name}],
        }
        monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal_user)
        ldap_calls: list[str] = []
        monkeypatch.setattr(LdapAuthenticationProvider, 'authenticate',
                            lambda _self, user_name, _password: ldap_calls.append(user_name))
        credentials: str = base64.b64encode(f'{UNKNOWN_EMAIL}:{PASSWORD}'.encode()).decode('ascii')

        response = rest_api.get(PROTECTED_URL, environ_overrides={AUTHORIZATION_ENVIRON_KEY: f'Basic {credentials}'})

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert not ldap_calls
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        assert users.count_documents({'user_name': UNKNOWN_EMAIL}) == 0


class TestCloudTokenWithoutTenant:
    """A cloud token whose database claim names no tenant"""

    @pytest.mark.parametrize('database', [None, ''], ids=['null', 'empty'])
    def test_it_is_refused(self, rest_api, cloud_admin, database: Any) -> None:
        """401 with its own message, for the administrator's id too"""
        response = rest_api.get(PROTECTED_URL, environ_overrides=cloud_auth_header(rest_api, ADMIN_USER_ID, database))

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.get_json()['message'] == NO_TENANT_TOKEN_MSG

    def test_the_same_user_with_its_tenant_is_served(self, rest_api, cloud_admin) -> None:
        """The contrast: the token naming the tenant reaches the route"""
        assert rest_api.get(PROTECTED_URL, environ_overrides=cloud_admin).status_code == HTTPStatus.OK
