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
Integration tests for the cloud startup update across real tenant databases

One tenant is broken the way a real one can be - its stored updater version is unreadable, so its update
raises - and listed FIRST. The startup loop must report it and still bring the tenant behind it up to date:
here that tenant does not exist yet, so being created and stamped at the current version proves the loop
reached it. With only broken tenants listed, startup refuses to go on. The service portal's list is the
only thing patched; the databases, the validator and the updater are real
"""
import os
from typing import Iterator
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services import DatabaseUpdater
from cmdb.errors.updater import TenantUpdatesFailedError
from cmdb.interface.rest_api.init_rest_api import bring_database_up_to_date, execute_update_checks
# -------------------------------------------------------------------------------------------------------------------- #

BROKEN_TENANT: str = f'itest_tenant_broken_{os.getpid()}'
HEALTHY_TENANT: str = f'itest_tenant_healthy_{os.getpid()}'
UNREADABLE_VERSION: str = 'not-a-version'

PORTAL_LOOKUP: str = 'cmdb.interface.rest_api.init_rest_api.get_db_names_from_service_portal'


@pytest.fixture(name='broken_tenant')
def fixture_broken_tenant(database_manager: MongoDatabaseManager) -> Iterator[str]:
    """A tenant database at the current schema whose stored updater version cannot be compared."""
    bring_database_up_to_date(database_manager, BROKEN_TENANT)
    DatabaseUpdater(database_manager, BROKEN_TENANT).set_update_version(UNREADABLE_VERSION)

    yield BROKEN_TENANT

    database_manager.connector.client.drop_database(BROKEN_TENANT)


@pytest.fixture(name='healthy_tenant')
def fixture_healthy_tenant(database_manager: MongoDatabaseManager) -> Iterator[str]:
    """A tenant the portal lists but that does not exist yet - the startup loop has to create it."""
    database_manager.connector.client.drop_database(HEALTHY_TENANT)

    yield HEALTHY_TENANT

    database_manager.connector.client.drop_database(HEALTHY_TENANT)


def test_a_broken_tenant_is_reported_and_the_next_one_is_still_brought_up_to_date(
    database_manager: MongoDatabaseManager, broken_tenant: str, healthy_tenant: str,
) -> None:
    """The broken tenant comes back as failed; the one behind it is created and stamped at the current version"""
    with patch(PORTAL_LOOKUP, return_value=[broken_tenant, healthy_tenant]):
        failed = execute_update_checks(database_manager)

    healthy_updater = DatabaseUpdater(database_manager, healthy_tenant)

    assert failed == frozenset({broken_tenant})
    assert database_manager.check_database_exists(healthy_tenant)
    assert healthy_updater.get_current_update_version() == healthy_updater.get_highest_update_version()


def test_only_broken_tenants_stop_the_startup(database_manager: MongoDatabaseManager, broken_tenant: str) -> None:
    """With nothing that could be served, the loop raises instead of fencing every tenant off"""
    with patch(PORTAL_LOOKUP, return_value=[broken_tenant]):
        with pytest.raises(TenantUpdatesFailedError):
            execute_update_checks(database_manager)
