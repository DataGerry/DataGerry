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
Unit tests for abort_if_external_provider_in_cloud (auth_helper)

External providers are on-premise only. In cloud mode an auth-settings section that activates one is refused
with a 400 naming it; an inactive one, and anything on premise, passes
"""
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.auth_helper import abort_if_external_provider_in_cloud
from cmdb.models.security_models.auth_settings_constants import (
    AUTH_SETTINGS_ID,
    CLOUD_EXTERNAL_PROVIDER_MSG,
    DEFAULT_TOKEN_LIFETIME,
    AuthSettingsKey,
    ProviderEntryKey,
)
from cmdb.security.auth.base_provider_config import PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

LDAP_PROVIDER_NAME: str = LdapAuthenticationProvider.get_name()
LOCAL_PROVIDER_NAME: str = LocalAuthenticationProvider.get_name()


def _section(ldap_active: bool, enable_external: bool = True) -> dict[str, Any]:
    """A whole auth section with the local provider and an LDAP entry in the given state"""
    entry_class: str = ProviderEntryKey.CLASS_NAME.value
    entry_config: str = ProviderEntryKey.CONFIG.value

    return {
        AuthSettingsKey.ID.value: AUTH_SETTINGS_ID,
        AuthSettingsKey.ENABLE_EXTERNAL.value: enable_external,
        AuthSettingsKey.TOKEN_LIFETIME.value: DEFAULT_TOKEN_LIFETIME,
        AuthSettingsKey.PROVIDERS.value: [
            {entry_class: LOCAL_PROVIDER_NAME, entry_config: {PROVIDER_ACTIVE_KEY: True}},
            {entry_class: LDAP_PROVIDER_NAME, entry_config: {PROVIDER_ACTIVE_KEY: ldap_active}},
        ],
    }


def _app(cloud_mode: bool) -> BaseCmdbApp:
    """An app whose cloud flag is the one under test"""
    app = BaseCmdbApp(__name__)
    app.cloud_mode = cloud_mode
    return app


def test_an_active_ldap_entry_is_refused_in_cloud_mode() -> None:
    """400, naming the provider the section activates"""
    with _app(cloud_mode=True).test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            abort_if_external_provider_in_cloud(_section(ldap_active=True))

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == CLOUD_EXTERNAL_PROVIDER_MSG.format(names=LDAP_PROVIDER_NAME)


def test_it_is_refused_with_the_external_switch_off_too() -> None:
    """The section still activates it - storing that would only look like it took effect"""
    with _app(cloud_mode=True).test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            abort_if_external_provider_in_cloud(_section(ldap_active=True, enable_external=False))

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST


def test_an_inactive_ldap_entry_passes_in_cloud_mode() -> None:
    """The rest of the section - the token lifetime among it - stays writable"""
    with _app(cloud_mode=True).test_request_context():
        assert abort_if_external_provider_in_cloud(_section(ldap_active=False)) is None


@pytest.mark.parametrize('ldap_active', [True, False], ids=['active', 'inactive'])
def test_nothing_is_refused_on_premise(ldap_active: bool) -> None:
    """On premise LDAP is a supported provider"""
    with _app(cloud_mode=False).test_request_context():
        assert abort_if_external_provider_in_cloud(_section(ldap_active=ldap_active)) is None
