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
Integration tests for the access history manager against the test MongoDB

Pinned: entries written in one batch get consecutive ids and are read back as written; the retention creates the TTL
index on ``time``, changes its expiry in place, drops it for 0 and is re-run safe
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import AccessHistoryManager
from cmdb.models.access_model import HISTORY_TTL_INDEX_NAME, CmdbAccessHistory
# -------------------------------------------------------------------------------------------------------------------- #

NOW: datetime = datetime(2026, 11, 26, tzinfo=timezone.utc)
SECONDS_PER_DAY: int = 86400
FIRST_DAYS, SECOND_DAYS = 30, 90


def _entry(document_id: int) -> dict[str, Any]:
    """One entry without its id"""
    return {'time': NOW, 'user_id': 1, 'user_name': 'admin', 'action': 'create', 'kind': 'scope_role',
            'document_id': document_id, 'before': None, 'after': {'name': 'r'}, 'changed': ['name'],
            'comment': None, 'group_ids': [], 'source': 'route'}


@pytest.fixture(name='collection', autouse=True)
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """An empty history, its TTL index removed after"""
    collection: Any = database_manager.get_collection(CmdbAccessHistory.COLLECTION, database_name)
    collection.delete_many({})

    yield collection

    collection.delete_many({})

    if HISTORY_TTL_INDEX_NAME in collection.index_information():
        collection.drop_index(HISTORY_TTL_INDEX_NAME)


@pytest.fixture(name='history')
def fixture_history(database_manager: MongoDatabaseManager) -> AccessHistoryManager:
    """The manager on the test database"""
    return AccessHistoryManager(database_manager)


def test_a_batch_is_written_as_given(history: AccessHistoryManager, collection: Any) -> None:
    """Consecutive ids, in order, the entries read back as written"""
    public_ids: list[int] = history.insert_entries([_entry(1), _entry(2)])

    assert public_ids[1] == public_ids[0] + 1
    stored = list(collection.find({}, {'_id': 0}).sort('public_id', 1))
    assert [(entry['public_id'], entry['document_id']) for entry in stored] == list(zip(public_ids, [1, 2]))
    assert history.insert_entries([]) == []


def test_the_retention_index(history: AccessHistoryManager, collection: Any) -> None:
    """Created, changed in place, dropped; each twice without harm"""
    def expiry() -> Any:
        return collection.index_information().get(HISTORY_TTL_INDEX_NAME, {}).get('expireAfterSeconds')

    for _ in range(2):
        history.apply_retention(FIRST_DAYS)
    assert expiry() == FIRST_DAYS * SECONDS_PER_DAY

    history.apply_retention(SECOND_DAYS)
    assert expiry() == SECOND_DAYS * SECONDS_PER_DAY

    for _ in range(2):
        history.apply_retention(0)
    assert HISTORY_TTL_INDEX_NAME not in collection.index_information()
