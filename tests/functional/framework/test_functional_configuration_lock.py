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
Functional tests: one configuration import or reset at a time, through the real REST app

``POST /configuration_transfer/import`` and ``POST /configuration_transfer/reset`` run inside the configuration lock,
a settings section of the tenant database. Pinned over HTTP, with the lock seeded as another running request leaves
it: while it is held, an import and a reset are each refused with 400 naming the reason and write nothing; a lock
older than its TTL is taken over and the request runs; and the lock is released after a success, after a refusal
inside it (a target that is not reset) and after a failed write that was undone. The best-practice apply, which runs
the same import, is pinned in ``test_functional_start_assistant_models_route.py``
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_LOCKED_MESSAGE,
)
from tests.functional.framework.test_functional_configuration_import_route import (  # pylint: disable=unused-import
    _export,
    _message,
    _stored,
    _upload,
    fixture_databases,
)
from tests.functional.framework.test_functional_configuration_reset_route import (  # pylint: disable=unused-import
    CONFIRMED,
    LEFT_OVER_ID,
    RESET_URL,
    fixture_scratch,
)
from tests.utils.configuration_lock_seed import (
    EXPIRED_AGE,
    OTHER_HOLDER,
    hold_configuration_lock,
    stored_configuration_lock,
)
# -------------------------------------------------------------------------------------------------------------------- #

#: A type stored in the import target, so the target is no longer reset
STRAY_TYPE_ID: int = 93101


@pytest.mark.usefixtures('databases')
class TestTheImportTakesTheLock:
    """POST /configuration_transfer/import"""

    def test_a_held_lock_refuses_the_import_and_nothing_is_written(
            self, rest_api, database_manager: MongoDatabaseManager, databases: tuple[str, str]) -> None:
        """400 naming the running import or reset; the target stays empty and the lock stays the other's"""
        source, target = databases
        hold_configuration_lock(database_manager, target)

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _message(response) == CONFIGURATION_LOCKED_MESSAGE
        assert not _stored(database_manager, target, CmdbType.COLLECTION)
        assert stored_configuration_lock(database_manager, target)['holder'] == OTHER_HOLDER

    def test_an_expired_lock_is_taken_over(self, rest_api, database_manager: MongoDatabaseManager,
                                           databases: tuple[str, str]) -> None:
        """Its holder can no longer be running: the import runs and releases the lock it took over"""
        source, target = databases
        hold_configuration_lock(database_manager, target, EXPIRED_AGE)

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.OK
        assert _stored(database_manager, target, CmdbType.COLLECTION)
        assert stored_configuration_lock(database_manager, target) is None

    def test_the_lock_is_released_after_an_import(self, rest_api, database_manager: MongoDatabaseManager,
                                                  databases: tuple[str, str]) -> None:
        """A second request may run straight after"""
        source, target = databases

        assert _upload(rest_api, _export(database_manager, source)).status_code == HTTPStatus.OK
        assert stored_configuration_lock(database_manager, target) is None

    def test_the_lock_is_released_after_a_refusal_inside_it(self, rest_api, database_manager: MongoDatabaseManager,
                                                            databases: tuple[str, str]) -> None:
        """A target that is not reset is refused inside the lock - and the lock goes with the refusal"""
        source, target = databases
        database_manager.get_collection(CmdbType.COLLECTION, target).insert_one({'public_id': STRAY_TYPE_ID})

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'not reset' in _message(response)
        assert stored_configuration_lock(database_manager, target) is None

    def test_the_lock_is_released_after_a_failed_write(self, rest_api, database_manager: MongoDatabaseManager,
                                                       databases: tuple[str, str],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        """The relations fail and the import is undone: 500, and the lock is free again"""
        source, target = databases
        original = BaseManager.insert_many

        def _failing_on_relations(self, data: list[dict[str, Any]], skip_public: bool = False) -> list[int]:
            if self.collection == CmdbRelation.COLLECTION:
                raise RuntimeError('relations unavailable')

            return original(self, data, skip_public)

        monkeypatch.setattr(BaseManager, 'insert_many', _failing_on_relations)

        response = _upload(rest_api, _export(database_manager, source))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert stored_configuration_lock(database_manager, target) is None


@pytest.mark.usefixtures('scratch')
class TestTheResetTakesTheLock:
    """POST /configuration_transfer/reset"""

    def test_a_held_lock_refuses_the_reset_and_nothing_is_deleted(
            self, rest_api, database_manager: MongoDatabaseManager, scratch: str) -> None:
        """400 naming the running import or reset; the left-overs are all still there"""
        hold_configuration_lock(database_manager, scratch)

        response = rest_api.post(RESET_URL, json=CONFIRMED)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _message(response) == CONFIGURATION_LOCKED_MESSAGE
        assert database_manager.get_collection(CmdbType.COLLECTION, scratch).count_documents(
            {'public_id': LEFT_OVER_ID}) == 1
        assert database_manager.get_collection(CmdbLocation.COLLECTION, scratch).count_documents(
            {'public_id': RootLocationDefault.PUBLIC_ID}) == 1

    def test_an_expired_lock_is_taken_over(self, rest_api, database_manager: MongoDatabaseManager,
                                           scratch: str) -> None:
        """The reset runs and the lock is free afterwards"""
        hold_configuration_lock(database_manager, scratch, EXPIRED_AGE)

        response = rest_api.post(RESET_URL, json=CONFIRMED)

        assert response.status_code == HTTPStatus.OK
        assert database_manager.get_collection(CmdbType.COLLECTION, scratch).count_documents({}) == 0
        assert stored_configuration_lock(database_manager, scratch) is None

    def test_the_lock_is_released_after_a_reset(self, rest_api, database_manager: MongoDatabaseManager,
                                                scratch: str) -> None:
        """A second reset runs straight after"""
        assert rest_api.post(RESET_URL, json=CONFIRMED).status_code == HTTPStatus.OK
        assert stored_configuration_lock(database_manager, scratch) is None
        assert rest_api.post(RESET_URL, json=CONFIRMED).status_code == HTTPStatus.OK
