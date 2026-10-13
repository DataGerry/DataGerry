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
Functional coverage of PUT /auth/settings refusing a provider config its config class cannot build

A provider flag or the LDAP group-mapping flag that is no boolean, a value the class cannot convert and a config
that is no object are each refused with one 400 naming the provider and why, and nothing is written - the read
would otherwise take the provider's defaults, switching LDAP off behind a 200. Booleans are stored. And the section
is stored as sent in both modes: in cloud mode the external-provider check no longer rewrites it on the way
"""
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID, PROVIDER_CONFIG_UNUSABLE_MSG
from cmdb.security.auth.auth_module import (
    PROVIDER_CONFIG_NOT_AN_OBJECT_MSG,
    PROVIDER_CONFIG_PROBLEM_MSG,
    AuthModule,
)
from cmdb.security.auth.base_provider_config import FLAG_NOT_BOOLEAN_MSG, PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.ldap_auth_config import GROUPS_ACTIVE_FLAG, LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

SETTINGS_URL: str = '/auth/settings'
LDAP: str = LdapAuthenticationProvider.get_name()
LOCAL: str = LocalAuthenticationProvider.get_name()
ADMIN_USER_ID: int = 93982
ADMIN_EMAIL: str = 'cloud-flag-admin@x.io'
UNDECLARED_KEY: str = 'retired_option'


@pytest.fixture(name='settings_collection')
def fixture_settings_collection(database_manager: MongoDatabaseManager, database_name: str):
    """The settings collection holding a known section; the stored auth section is restored afterwards"""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_ID})
    collection.replace_one({'_id': AUTH_SETTINGS_ID}, {'_id': AUTH_SETTINGS_ID, **_section()}, upsert=True)

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
        'public_id': ADMIN_USER_ID, 'user_name': 'cloud-flag-admin', 'email': ADMIN_EMAIL, 'active': True,
        'group_id': 1, 'database': database_name, 'api_level': 3,
        'registration_time': datetime.now(timezone.utc),
    })

    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)

    yield cloud_auth_header(rest_api, ADMIN_USER_ID, database_name)

    users.delete_many({'public_id': ADMIN_USER_ID})


def _section(ldap_active: Any = False, local_active: Any = True, **ldap_config: Any) -> dict[str, Any]:
    """A whole auth section: the local provider and LDAP with its defaults, the given keys replaced"""
    return {'enable_external': True, 'token_lifetime': 60, 'providers': [
        {'class_name': LOCAL, 'config': {'active': local_active}},
        {'class_name': LDAP, 'config': {**deepcopy(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES),
                                        'active': ldap_active, **ldap_config}},
    ]}


def _flag_problem(provider: str, key: str, value: Any) -> str:
    """One provider's problem with a flag that is no boolean"""
    return PROVIDER_CONFIG_PROBLEM_MSG.format(
        provider=provider, reason=FLAG_NOT_BOOLEAN_MSG.format(key=key, kind=type(value).__name__),
    )


def _refusal(*problems: str) -> str:
    """The 400's message"""
    return PROVIDER_CONFIG_UNUSABLE_MSG.format(problems='; '.join(problems))


def _stored(settings_collection) -> dict[str, Any]:
    """The stored section, without its address"""
    stored = settings_collection.find_one({'_id': AUTH_SETTINGS_ID})
    stored.pop('_id')

    return stored


class TestRefused:
    """PUT /auth/settings with a provider config that does not build - 400, nothing written"""

    @pytest.mark.parametrize('value', ['false', 'true', 1, 0])
    def test_an_ldap_flag_that_is_no_boolean(self, rest_api, settings_collection, value: Any) -> None:
        """'false' among them - a truthy string, whatever it spells"""
        response = rest_api.put(SETTINGS_URL, json=_section(ldap_active=value))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _refusal(_flag_problem(LDAP, PROVIDER_ACTIVE_KEY, value))
        assert _stored(settings_collection) == _section()

    def test_a_group_mapping_flag_that_is_no_boolean(self, rest_api, settings_collection) -> None:
        """The flag inside 'groups'"""
        groups = {**LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['groups'], 'active': 'false'}

        response = rest_api.put(SETTINGS_URL, json=_section(groups=groups))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _refusal(_flag_problem(LDAP, GROUPS_ACTIVE_FLAG, 'false'))
        assert _stored(settings_collection) == _section()

    def test_a_value_the_class_cannot_convert(self, rest_api, settings_collection) -> None:
        """A default group that is no number - stored, the read would switch LDAP off"""
        response = rest_api.put(SETTINGS_URL, json=_section(default_group='abc'))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'].startswith(_refusal(f'{LDAP}: ')[:-1])
        assert _stored(settings_collection) == _section()

    def test_a_config_that_is_no_object(self, rest_api, settings_collection) -> None:
        """Nothing to build from"""
        section = _section()
        section['providers'][1]['config'] = 'off'

        response = rest_api.put(SETTINGS_URL, json=section)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _refusal(PROVIDER_CONFIG_NOT_AN_OBJECT_MSG.format(provider=LDAP))

    def test_every_refused_provider_is_named(self, rest_api, settings_collection) -> None:
        """One answer, in installation order"""
        response = rest_api.put(SETTINGS_URL, json=_section(ldap_active='false', local_active='true'))

        assert response.get_json()['message'] == _refusal(_flag_problem(LOCAL, PROVIDER_ACTIVE_KEY, 'true'),
                                                          _flag_problem(LDAP, PROVIDER_ACTIVE_KEY, 'false'))


class TestStored:
    """Configs that build are stored as sent"""

    @pytest.mark.parametrize('ldap_active', [True, False])
    def test_boolean_flags_are_stored(self, rest_api, settings_collection, ldap_active: bool) -> None:
        """And read back as stored"""
        response = rest_api.put(SETTINGS_URL, json=_section(ldap_active=ldap_active))

        assert response.status_code == HTTPStatus.OK
        assert _stored(settings_collection) == _section(ldap_active=ldap_active)
        stored = settings_collection.find_one({'_id': AUTH_SETTINGS_ID})
        assert AuthModule(stored).build_provider_config(LdapAuthenticationProvider).is_active() is ldap_active

    def test_on_premise_the_section_is_stored_as_sent(self, rest_api, settings_collection) -> None:
        """An undeclared key kept"""
        section = _section(**{UNDECLARED_KEY: 1})

        assert rest_api.put(SETTINGS_URL, json=section).status_code == HTTPStatus.OK
        assert _stored(settings_collection) == section

    def test_in_cloud_mode_the_section_is_stored_as_sent_too(self, rest_api, cloud_admin, settings_collection) -> None:
        """The external-provider check judges a copy: no key dropped, no entry appended"""
        section = _section(**{UNDECLARED_KEY: 1})
        del section['providers'][0]

        response = rest_api.put(SETTINGS_URL, json=section, environ_overrides=cloud_admin)

        assert response.status_code == HTTPStatus.OK
        assert _stored(settings_collection) == section
