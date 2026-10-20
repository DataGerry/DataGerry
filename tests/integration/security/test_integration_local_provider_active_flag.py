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
Integration tests for the local provider's `active` flag against a stored auth section

The section is written to MongoDB and read back the way the login route reads it, and the real local
provider checks a real password digest. The user under test names a provider that is not installed, so
the primary attempt fails and only the fallback sweep can log them in - the one place the local config's
flag used to be read. Whatever that flag says (missing, null, false), the sweep must reach local login,
and a wrong password must still be refused
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager, UsersManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.security.auth.auth_module import (
    PROVIDER_CLASS_NAME_KEY,
    PROVIDER_CONFIG_KEY,
    PROVIDERS_KEY,
    AuthModule,
)
from cmdb.security.auth.base_provider_config import PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 93991
USER_NAME: str = 'stranded-local-user'
PASSWORD: str = 'correct-horse'
WRONG_PASSWORD: str = 'wrong-horse'
GONE_PROVIDER: str = 'GoneProvider'
GROUP_ID: int = 1

LOCAL_CONFIGS: list[dict[str, Any]] = [{}, {PROVIDER_ACTIVE_KEY: None}, {PROVIDER_ACTIVE_KEY: False}]
LOCAL_CONFIG_IDS: list[str] = ['missing', 'null', 'false']


@pytest.fixture(name='stored_user')
def fixture_stored_user(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores a local user with a real password digest whose `authenticator` names no installed provider."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})

    with rest_api.application.app_context():
        security_manager = SecurityManager(database_manager)
        users.insert_one({
            'public_id': USER_ID, 'user_name': USER_NAME, 'active': True, 'group_id': GROUP_ID,
            'authenticator': GONE_PROVIDER, 'password': security_manager.generate_hmac(PASSWORD),
            'registration_time': datetime.now(timezone.utc),
        })

        yield security_manager

    users.delete_many({'public_id': USER_ID})


@pytest.fixture(name='settings_manager')
def fixture_settings_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A SettingsManager on the test database; the stored auth section is restored afterwards."""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_ID})

    yield SettingsManager(database_manager)

    if before is None:
        collection.delete_one({'_id': AUTH_SETTINGS_ID})
    else:
        collection.replace_one({'_id': AUTH_SETTINGS_ID}, before, upsert=True)


def _module_over_stored_section(settings_manager: SettingsManager,
                                database_manager: MongoDatabaseManager,
                                security_manager: SecurityManager,
                                local_config: dict[str, Any]) -> AuthModule:
    """Stores an auth section carrying `local_config` for the local provider and reads it back as the route does."""
    section: dict[str, Any] = dict(AuthModule.__DEFAULT_SETTINGS__)
    section.pop('_id', None)
    section[PROVIDERS_KEY] = [
        {PROVIDER_CLASS_NAME_KEY: LocalAuthenticationProvider.get_name(), PROVIDER_CONFIG_KEY: local_config},
    ]
    settings_manager.write(_id=AUTH_SETTINGS_ID, data=section)

    stored = settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__)

    return AuthModule(stored, security_manager=security_manager, users_manager=UsersManager(database_manager))


class TestTheSweepReachesLocalLogin:
    """A local user whose primary attempt fails still logs in with the right password."""

    @pytest.mark.parametrize('local_config', LOCAL_CONFIGS, ids=LOCAL_CONFIG_IDS)
    def test_the_right_password_logs_in(
        self, stored_user: SecurityManager, settings_manager: SettingsManager,
        database_manager: MongoDatabaseManager, local_config: dict[str, Any],
    ) -> None:
        """The stored flag is not a switch that can strand a local account."""
        module = _module_over_stored_section(settings_manager, database_manager, stored_user, local_config)

        user = module.login(USER_NAME, PASSWORD)

        assert user.public_id == USER_ID

    @pytest.mark.parametrize('local_config', LOCAL_CONFIGS, ids=LOCAL_CONFIG_IDS)
    def test_a_wrong_password_is_still_refused(
        self, stored_user: SecurityManager, settings_manager: SettingsManager,
        database_manager: MongoDatabaseManager, local_config: dict[str, Any],
    ) -> None:
        """Being always tried is not being always accepted."""
        module = _module_over_stored_section(settings_manager, database_manager, stored_user, local_config)

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, WRONG_PASSWORD)


class TestTheStoredSectionReadsBack:
    """What the settings read makes of a stored local config."""

    @pytest.mark.parametrize('local_config', [{}, {PROVIDER_ACTIVE_KEY: None}], ids=['missing', 'null'])
    def test_a_missing_flag_is_normalised_to_active(
        self, stored_user: SecurityManager, settings_manager: SettingsManager,
        database_manager: MongoDatabaseManager, local_config: dict[str, Any],
    ) -> None:
        """This is the section `GET /auth/settings` serves and the settings page posts back."""
        module = _module_over_stored_section(settings_manager, database_manager, stored_user, local_config)

        config = module.settings.get_provider_settings(LocalAuthenticationProvider.get_name())

        assert config[PROVIDER_ACTIVE_KEY] is True

    def test_a_stored_false_is_kept(
        self, stored_user: SecurityManager, settings_manager: SettingsManager,
        database_manager: MongoDatabaseManager,
    ) -> None:
        """Only an absent flag is defaulted; the page still shows what was saved."""
        module = _module_over_stored_section(
            settings_manager, database_manager, stored_user, {PROVIDER_ACTIVE_KEY: False},
        )

        config = module.settings.get_provider_settings(LocalAuthenticationProvider.get_name())

        assert config[PROVIDER_ACTIVE_KEY] is False
