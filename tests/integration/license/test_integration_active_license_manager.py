# DATAGERRY - OpenSource Enterprise CMDB
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
Integration tests for ActiveLicenseManager against a real MongoDB

Covers the single-document store: set/get round-trip, that a second set OVERWRITES the first
(leaving exactly one document, never appends), get on an empty store, and clear semantics
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import (
    ActiveLicenseManager,
    ACTIVE_LICENSE_ID,
    LICENSE_BLOB_KEY,
    ACTIVATED_AT_KEY,
)
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> ActiveLicenseManager:
    """Provides an ActiveLicenseManager bound to the test database"""
    return ActiveLicenseManager(database_manager, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the active-license collection after each test"""
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


def test_set_and_get_round_trip(manager: ActiveLicenseManager) -> None:
    """A stored blob is returned unchanged"""
    manager.set_active_license('blob-1')

    assert manager.get_active_license_blob() == 'blob-1'


def test_set_overwrites_previous_blob(
    manager: ActiveLicenseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """A second set replaces the first and leaves exactly one document (no append)"""
    manager.set_active_license('first-blob')
    manager.set_active_license('second-blob')

    assert manager.get_active_license_blob() == 'second-blob'
    assert database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).count_documents({}) == 1


def test_get_returns_none_when_empty(manager: ActiveLicenseManager) -> None:
    """An empty store yields None"""
    assert manager.get_active_license_blob() is None


def test_clear_removes_and_reports(manager: ActiveLicenseManager) -> None:
    """clear removes a stored blob and reports whether one was present"""
    manager.set_active_license('blob-1')

    assert manager.clear_active_license() is True
    assert manager.get_active_license_blob() is None
    assert manager.clear_active_license() is False


def test_set_writes_fixed_id_and_activation_timestamp(
    manager: ActiveLicenseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """The upsert stores the singleton under the fixed _id and records an integer activated_at"""
    manager.set_active_license('blob-1')

    stored = database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).find_one({})

    assert stored['_id'] == ACTIVE_LICENSE_ID
    assert stored[LICENSE_BLOB_KEY] == 'blob-1'
    assert isinstance(stored[ACTIVATED_AT_KEY], int)


def test_overwrite_keeps_fixed_id_and_refreshes_timestamp(
    manager: ActiveLicenseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """A second set keeps the same _id and never lets activated_at go backwards"""
    collection = database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name)

    manager.set_active_license('first-blob')
    first_activated_at = collection.find_one({})[ACTIVATED_AT_KEY]

    manager.set_active_license('second-blob')
    second = collection.find_one({})

    assert second['_id'] == ACTIVE_LICENSE_ID
    assert second[LICENSE_BLOB_KEY] == 'second-blob'
    assert second[ACTIVATED_AT_KEY] >= first_activated_at
