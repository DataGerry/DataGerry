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
Unit tests for abort_if_provider_config_unusable (auth_helper)

An auth-settings section whose provider config cannot be built through its config class is refused with one 400
naming every refused provider and why; a section whose configs all build passes. The rule itself is
AuthModule.provider_config_problems - this module pins how the route helper answers it
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.auth_helper import abort_if_provider_config_unusable
from cmdb.models.security_models.auth_settings_constants import (
    PROVIDER_CONFIG_UNUSABLE_MSG,
    AuthSettingsKey,
    ProviderEntryKey,
)
from cmdb.security.auth.auth_module import PROVIDER_CONFIG_PROBLEM_MSG, AuthModule
from cmdb.security.auth.base_provider_config import FLAG_NOT_BOOLEAN_MSG, PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

LDAP_PROVIDER_NAME: str = LdapAuthenticationProvider.get_name()
LOCAL_PROVIDER_NAME: str = LocalAuthenticationProvider.get_name()
FIRST_PROBLEM: str = 'first'
SECOND_PROBLEM: str = 'second'


def _section(local_active: Any, ldap_active: Any) -> dict[str, Any]:
    """A section with both providers' flags as given"""
    return {AuthSettingsKey.PROVIDERS.value: [
        {ProviderEntryKey.CLASS_NAME.value: LOCAL_PROVIDER_NAME,
         ProviderEntryKey.CONFIG.value: {PROVIDER_ACTIVE_KEY: local_active}},
        {ProviderEntryKey.CLASS_NAME.value: LDAP_PROVIDER_NAME,
         ProviderEntryKey.CONFIG.value: {PROVIDER_ACTIVE_KEY: ldap_active}},
    ]}


@pytest.fixture(name='request_context', autouse=True)
def fixture_request_context():
    """A request context, as the route runs in"""
    with BaseCmdbApp(__name__).test_request_context():
        yield


def test_configs_that_build_pass() -> None:
    """Booleans throughout"""
    assert abort_if_provider_config_unusable(_section(True, False)) is None


def test_a_string_flag_is_refused_naming_provider_and_flag() -> None:
    """The 400 carries the problem as the rule words it"""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_provider_config_unusable(_section(True, 'false'))

    problem = PROVIDER_CONFIG_PROBLEM_MSG.format(
        provider=LDAP_PROVIDER_NAME, reason=FLAG_NOT_BOOLEAN_MSG.format(key=PROVIDER_ACTIVE_KEY, kind='str'),
    )
    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == PROVIDER_CONFIG_UNUSABLE_MSG.format(problems=problem)


def test_every_problem_is_listed_in_one_answer() -> None:
    """Joined with '; ', in the order the rule found them"""
    with patch.object(AuthModule, 'provider_config_problems', return_value=[FIRST_PROBLEM, SECOND_PROBLEM]):
        with pytest.raises(HTTPException) as exc_info:
            abort_if_provider_config_unusable({})

    assert exc_info.value.description == PROVIDER_CONFIG_UNUSABLE_MSG.format(
        problems=f'{FIRST_PROBLEM}; {SECOND_PROBLEM}',
    )
