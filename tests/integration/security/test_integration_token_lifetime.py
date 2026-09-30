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
Integration tests for where a token's lifetime comes from, against a real MongoDB

In cloud mode every tenant has its own `auth` settings section - the auth-settings routes write it into
the requesting user's database - and `token_lifetime` is one of its values. The generator used to read
the section from the database manager's own database whatever the tenant, so a tenant's setting had no
effect. Pinned here with a second, tenant-like database next to the test database; the signing key stays
the installation's one
"""
from collections.abc import Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID, AuthSettingsKey
from cmdb.security.token.generator import TokenGenerator
# -------------------------------------------------------------------------------------------------------------------- #

SECONDS_PER_MINUTE: int = 60
TENANT_LIFETIME: int = 17
TENANT_SUFFIX: str = '-tenant-token-lifetime'
PAYLOAD: dict[str, dict[str, int]] = {'user': {'public_id': 1}}


def _drop_if_present(database_manager: MongoDatabaseManager, database: str) -> None:
    """Drops a database left behind by an earlier run; dropping a missing one is refused"""
    if database_manager.check_database_exists(database):
        database_manager.drop_database(database)


@pytest.fixture(name='tenant_database')
def fixture_tenant_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """A tenant database whose auth section sets its own token lifetime; dropped afterwards"""
    tenant: str = f'{database_name}{TENANT_SUFFIX}'
    _drop_if_present(database_manager, tenant)
    SettingsManager(database_manager, tenant).write(
        AUTH_SETTINGS_ID, {AuthSettingsKey.TOKEN_LIFETIME.value: TENANT_LIFETIME}
    )

    yield tenant

    _drop_if_present(database_manager, tenant)


def test_a_tenant_token_lives_as_long_as_the_tenant_configured(
        database_manager: MongoDatabaseManager, tenant_database: str) -> None:
    """The lifetime is the tenant's, not the default database's"""
    _, issued, expires = TokenGenerator(database_manager, tenant_database).generate_token_with_times(PAYLOAD)

    assert expires - issued == TENANT_LIFETIME * SECONDS_PER_MINUTE


def test_the_default_database_keeps_its_own_lifetime(
        database_manager: MongoDatabaseManager, tenant_database: str) -> None:
    """A tenant's setting does not leak into tokens for the installation's own database"""
    del tenant_database
    generator = TokenGenerator(database_manager)

    assert generator.token_lifetime != TENANT_LIFETIME
