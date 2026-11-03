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
Unit tests for read_auth_module (auth_helper)

The three auth read routes build the stored configuration's AuthModule through it: the `auth` section read with the
module's defaults, and a failing read left to raise as itself - the routes' `handle_route_errors` hands a temporary
database failure to the app's handlers
"""
from unittest.mock import MagicMock

import pytest

from cmdb.errors.database import DocumentNetworkError
from cmdb.interface.rest_api.routes.auth_helper import read_auth_module
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #


def _settings_manager(section: dict | None = None) -> MagicMock:
    """A settings manager answering `section` - the module's defaults when None"""
    manager = MagicMock()
    manager.get_all_values_from_section.return_value = (
        AuthModule.__DEFAULT_SETTINGS__ if section is None else section
    )

    return manager


def test_the_auth_section_is_read_with_the_modules_defaults() -> None:
    """One read of the `auth` section, the defaults where nothing is stored"""
    manager = _settings_manager()

    read_auth_module(manager)

    manager.get_all_values_from_section.assert_called_once_with(
        AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__,
    )


def test_the_module_is_built_over_what_was_read() -> None:
    """The defaults install the local provider"""
    auth_module = read_auth_module(_settings_manager())

    assert isinstance(auth_module, AuthModule)
    assert LocalAuthenticationProvider.get_name() in [provider.get_name() for provider in auth_module.providers]


def test_a_failing_read_raises_as_itself() -> None:
    """Not wrapped - the route's decorator decides how it is answered"""
    manager = MagicMock()
    failure = DocumentNetworkError('database unavailable')
    manager.get_all_values_from_section.side_effect = failure

    with pytest.raises(DocumentNetworkError) as raised:
        read_auth_module(manager)

    assert raised.value is failure
