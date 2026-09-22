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
Unit tests for ManagerProvider, ManagerType and the MANAGER_CLASSES registry.

Two things are under test here, and they fail for different reasons:

* **Registry integrity.** `ManagerType` and `MANAGER_CLASSES` are two hand-maintained lists that
  must stay in step, and nothing at import time enforces that. A half-registered manager would
  otherwise only surface as a `BaseManagerInitError` from whatever route asked for it first. The
  tests in `TestTheRegistry` cover each other in both directions, pin every value to its class
  `__name__` and bind every registered constructor against both argument shapes.
* **Argument selection.** `get_manager` picks `(dbm,)` or `(dbm, request_user.database)` off
  `current_app.cloud_mode`. The cloud branch had no coverage at all, so the tests below drive both
  modes through a stub class registered into the map rather than constructing a real manager - no
  database is touched.
"""
import inspect
from typing import Any

import pytest

from cmdb.errors.manager import BaseManagerInitError
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.manager.manager_provider_model import MANAGER_CLASSES, ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

TENANT_DATABASE: str = 'tenant-db'
SENTINEL_DBM: object = object()


class RecordingManager:
    """Stands in for a registered manager class and records how the provider constructed it."""

    def __init__(self, dbm: Any, database: str | None = None) -> None:
        """Mirrors the constructor shape every registered manager has to offer."""
        self.dbm = dbm
        self.database = database


@pytest.fixture(name='cloud_app')
def fixture_cloud_app() -> BaseCmdbApp:
    """A REST app flagged for cloud mode, carrying a sentinel database handle."""
    app = BaseCmdbApp(__name__, database_manager=SENTINEL_DBM)
    app.cloud_mode = True

    return app


@pytest.fixture(name='local_app')
def fixture_local_app() -> BaseCmdbApp:
    """A REST app in the default on-premise mode, carrying a sentinel database handle."""
    app = BaseCmdbApp(__name__, database_manager=SENTINEL_DBM)
    app.cloud_mode = False

    return app


@pytest.fixture(name='request_user')
def fixture_request_user() -> CmdbUser:
    """A user whose only relevant property is the tenant database it names."""
    return CmdbUser(public_id=1, user_name='tester', active=True, group_id=1, database=TENANT_DATABASE)


@pytest.fixture(name='registered_stub')
def fixture_registered_stub(monkeypatch) -> ManagerType:
    """Points one ManagerType at RecordingManager so no real manager (and no DB) is constructed."""
    monkeypatch.setitem(MANAGER_CLASSES, ManagerType.OBJECTS, RecordingManager)

    return ManagerType.OBJECTS


class TestTheRegistry:
    """ManagerType and MANAGER_CLASSES are two lists that have to describe the same set."""

    def test_every_manager_type_is_registered(self) -> None:
        """An enum member with no map entry is a route that 500s the first time it is called"""
        assert set(MANAGER_CLASSES) == set(ManagerType)

    def test_the_map_holds_no_orphans(self) -> None:
        """A map key that is not a ManagerType could never be requested"""
        assert all(isinstance(manager_type, ManagerType) for manager_type in MANAGER_CLASSES)

    def test_every_value_is_its_class_name(self) -> None:
        """The enum value doubles as the class name, so a typo in either half has to fail here"""
        mismatched = {
            manager_type.name: (manager_type.value, manager_class.__name__)
            for manager_type, manager_class in MANAGER_CLASSES.items()
            if manager_type.value != manager_class.__name__
        }

        assert mismatched == {}

    def test_no_class_is_registered_twice(self) -> None:
        """Two ManagerTypes resolving to one class means one of them was a copy-paste slip"""
        registered = list(MANAGER_CLASSES.values())

        assert len(set(registered)) == len(registered)

    @pytest.mark.parametrize('manager_type', list(ManagerType), ids=lambda member: member.name)
    def test_every_class_accepts_both_argument_shapes(self, manager_type: ManagerType) -> None:
        """Membership means constructible as Cls(dbm) AND Cls(dbm, database) - cloud mode needs both"""
        signature = inspect.signature(MANAGER_CLASSES[manager_type])

        signature.bind(SENTINEL_DBM)
        signature.bind(SENTINEL_DBM, TENANT_DATABASE)


class TestGetManager:
    """The lookup half of get_manager: resolve the type, or refuse loudly."""

    def test_returns_an_instance_of_the_registered_class(
            self, local_app: BaseCmdbApp, registered_stub: ManagerType, request_user: CmdbUser) -> None:
        """A route gets back a fresh instance of exactly the class registered for its ManagerType"""
        with local_app.app_context():
            manager = ManagerProvider.get_manager(registered_stub, request_user)

        assert isinstance(manager, RecordingManager)

    def test_is_stateless(
            self, local_app: BaseCmdbApp, registered_stub: ManagerType, request_user: CmdbUser) -> None:
        """Nothing is cached between calls - two routes must never share one manager instance"""
        with local_app.app_context():
            first = ManagerProvider.get_manager(registered_stub, request_user)
            second = ManagerProvider.get_manager(registered_stub, request_user)

        assert first is not second

    def test_an_unregistered_manager_type_is_refused(
            self, local_app: BaseCmdbApp, request_user: CmdbUser, monkeypatch) -> None:
        """A ManagerType missing from the map raises BaseManagerInitError instead of returning None"""
        monkeypatch.delitem(MANAGER_CLASSES, ManagerType.OBJECTS)

        with local_app.app_context():
            with pytest.raises(BaseManagerInitError):
                ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    def test_a_non_manager_type_is_refused(self, local_app: BaseCmdbApp, request_user: CmdbUser) -> None:
        """The map lookup must not blow up on an unhashable-looking or foreign key"""
        with local_app.app_context():
            with pytest.raises(BaseManagerInitError):
                ManagerProvider.get_manager('NotAManagerType', request_user)


class TestLocalModeArguments:
    """On-premise: one process, one database, the user does not select it."""

    def test_passes_only_the_database_manager(
            self, local_app: BaseCmdbApp, registered_stub: ManagerType, request_user: CmdbUser) -> None:
        """The tenant database is not appended, so the manager falls back to the process default"""
        with local_app.app_context():
            manager: RecordingManager = ManagerProvider.get_manager(registered_stub, request_user)

        assert manager.dbm is SENTINEL_DBM
        assert manager.database is None

    def test_a_missing_request_user_is_tolerated(
            self, local_app: BaseCmdbApp, registered_stub: ManagerType) -> None:
        """The user is never dereferenced here - SearchPipelineBuilder relies on that (user is optional)"""
        with local_app.app_context():
            manager: RecordingManager = ManagerProvider.get_manager(registered_stub, None)

        assert manager.database is None


class TestCloudModeArguments:
    """Cloud: the requesting user carries the tenant database the manager has to be bound to."""

    def test_appends_the_users_database(
            self, cloud_app: BaseCmdbApp, registered_stub: ManagerType, request_user: CmdbUser) -> None:
        """Binding to the wrong database here would serve one tenant another tenant's data"""
        with cloud_app.app_context():
            manager: RecordingManager = ManagerProvider.get_manager(registered_stub, request_user)

        assert manager.dbm is SENTINEL_DBM
        assert manager.database == TENANT_DATABASE

    def test_follows_the_user_not_the_app(
            self, cloud_app: BaseCmdbApp, registered_stub: ManagerType) -> None:
        """Two users in one process get two different databases from the same provider"""
        first = CmdbUser(public_id=2, user_name='a', active=True, group_id=1, database='tenant-a')
        second = CmdbUser(public_id=3, user_name='b', active=True, group_id=1, database='tenant-b')

        with cloud_app.app_context():
            first_manager: RecordingManager = ManagerProvider.get_manager(registered_stub, first)
            second_manager: RecordingManager = ManagerProvider.get_manager(registered_stub, second)

        assert (first_manager.database, second_manager.database) == ('tenant-a', 'tenant-b')

    def test_a_missing_request_user_is_refused(
            self, cloud_app: BaseCmdbApp, registered_stub: ManagerType) -> None:
        """Without a user there is no tenant database - a domain error, not an AttributeError"""
        with cloud_app.app_context():
            with pytest.raises(BaseManagerInitError):
                ManagerProvider.get_manager(registered_stub, None)

    @pytest.mark.parametrize('database', [None, ''])
    def test_a_falsy_database_is_refused(
            self, cloud_app: BaseCmdbApp, registered_stub: ManagerType, database) -> None:
        """A user carrying no usable tenant name must fail, not fall through to another tenant

        The stored `database` may legitimately be absent - CmdbUser.SCHEMA allows null and
        `from_data` passes a stored null straight through, because `.get(key, default)` only
        defaults a MISSING key. BaseManager then binds to `dbm.db_name` for any falsy db_name, so
        without this guard a cloud user with a null database would silently be served out of the
        process-wide database
        """
        user = CmdbUser(public_id=4, user_name='no-tenant', active=True, group_id=1, database=database)

        with cloud_app.app_context():
            with pytest.raises(BaseManagerInitError):
                ManagerProvider.get_manager(registered_stub, user)
