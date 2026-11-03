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
Integration tests: the configuration lock against a real MongoDB

Two things only a real database shows. **The race the lock closes:** import B starting while import A is writing -
before the lock, B passed the reset check, clashed on A's ids and its undo deleted A's types; now B is refused with
400 and A's configuration is whole. **The lock's atomicity:** threads taking the lock at the same time over a real
SettingsManager - exactly one runs, every other is refused, and the lock is free afterwards
"""
import copy
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType
from cmdb.framework.configuration_transfer.best_practice_catalogue import load_model
from cmdb.interface.rest_api.routes.configuration_transfer_routes import configuration_import_runner as runner
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper import (
    configuration_lock,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_LOCKED_MESSAGE,
)
from tests.utils.configuration_lock_seed import stored_configuration_lock
# -------------------------------------------------------------------------------------------------------------------- #

RUNNER: str = 'cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner'
HELPER: str = 'cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper'
MODEL: Path = Path('cmdb/framework/configuration_transfer/best_practice_models/example/example_contacts.json')
IMPORTED_COLLECTIONS: tuple[str, ...] = ('framework.types', 'framework.categories', 'framework.relations')
RACERS: int = 6
HOLD_SECONDS: float = 5.0
POLL_SECONDS: float = 0.01


def _administrator() -> CmdbUser:
    """The importing user"""
    return CmdbUser(public_id=1, user_name='admin', active=True, group_id=1)


@pytest.fixture(name='imported_configuration_removed')
def fixture_imported_configuration_removed(database_manager: MongoDatabaseManager, database_name: str):
    """Removes what the imports wrote and any lock they left, before and after"""
    def _purge() -> None:
        for collection in IMPORTED_COLLECTIONS:
            database_manager.get_collection(collection, database_name).delete_many({})
        database_manager.get_collection(SettingsManager.COLLECTION, database_name).delete_many(
            {'_id': 'configuration_transfer_lock'})

    _purge()
    yield
    _purge()


@pytest.mark.usefixtures('rest_api_app_context', 'imported_configuration_removed')
def test_an_import_during_another_is_refused_and_the_first_stays_whole(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """B starts while A writes: refused with the lock's 400, and A's types survive - B's undo never ran"""
    document: dict[str, Any] = load_model(MODEL).document
    outcomes: list[str] = []
    real_import = runner.import_configuration

    def _a_writing(*args: Any) -> dict[str, int]:
        imported: dict[str, int] = real_import(*args)
        try:
            runner.import_transfer_document(copy.deepcopy(document), _administrator())
            outcomes.append('B imported')
        except HTTPException as err:
            outcomes.append(f'{err.code} {err.description}')
        return imported

    # The session database is no reset system and records no version; the race, not those checks, is under test
    with patch(f'{RUNNER}.find_import_blockers', return_value=[]), \
            patch(f'{RUNNER}.read_target_version', return_value=document['db_version']), \
            patch(f'{RUNNER}.import_configuration', side_effect=_a_writing):
        imported: dict[str, int] = runner.import_transfer_document(copy.deepcopy(document), _administrator())

    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    assert outcomes == [f'400 {CONFIGURATION_LOCKED_MESSAGE}']
    assert imported['types'] == types.count_documents({}) == len(document['components']['types']['items'])
    assert stored_configuration_lock(database_manager, database_name) is None


@pytest.mark.usefixtures('imported_configuration_removed')
def test_exactly_one_of_concurrent_requests_holds_the_lock(database_manager: MongoDatabaseManager,
                                                           database_name: str) -> None:
    """Every other request is refused while it runs; the lock is free once it finished"""
    settings_manager = SettingsManager(database_manager, database_name)
    held, refused, release = [], [], threading.Event()
    lock = threading.Lock()

    def _request(racer: int) -> None:
        try:
            with configuration_lock(CmdbUser(public_id=racer, user_name=f'racer-{racer}', active=True)):
                with lock:
                    held.append(racer)
                release.wait(HOLD_SECONDS)
        except HTTPException:
            with lock:
                refused.append(racer)

    with patch(f'{HELPER}.ManagerProvider.get_manager', return_value=settings_manager):
        threads = [threading.Thread(target=_request, args=(racer,)) for racer in range(RACERS)]
        for thread in threads:
            thread.start()
        # Every request has tried once the holder is in and all others are refused; the holder waits for the release
        deadline: float = time.monotonic() + HOLD_SECONDS
        while len(held) + len(refused) < RACERS and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
        counted: tuple[int, int] = (len(held), len(refused))
        release.set()
        for thread in threads:
            thread.join()

    assert counted == (1, RACERS - 1)
    assert stored_configuration_lock(database_manager, database_name) is None
