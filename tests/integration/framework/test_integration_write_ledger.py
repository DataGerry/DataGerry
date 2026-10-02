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
Integration tests for the WriteLedger against a real MongoDB

The unit tests pin the undo's order and its residue reports against mocks; these pin what the database actually
holds afterwards - that an undone update drops the keys the update ADDED (a replace, not a $set), that a deleted
document comes back under its old public_id and _id, and that an undo run twice changes nothing more.
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.base_manager import BaseManager
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.writeLedgerScratch'
PARENT_ID: int = 40
KEPT: dict = {'public_id': 1, 'name': 'kept', 'parent': 0}
CHANGED: dict = {'public_id': 2, 'name': 'before', 'parent': 0}
REMOVED: dict = {'public_id': 3, 'name': 'removed', 'parent': 0}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A BaseManager over an empty scratch collection holding three documents."""
    collection = database_manager.get_collection(COLLECTION, database_name)
    counters = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name)
    collection.delete_many({})
    counters.delete_many({'_id': COLLECTION})
    collection.create_index('public_id', unique=True, name='public_id')
    collection.insert_many([dict(KEPT), dict(CHANGED), dict(REMOVED)])

    yield BaseManager(COLLECTION, database_manager, database_name)

    collection.drop()
    counters.delete_many({'_id': COLLECTION})


def _stored(manager: BaseManager) -> list[dict]:
    """Every stored document, ids included, in public_id order."""
    return sorted(manager.find(criteria={}), key=lambda document: document['public_id'])


def _a_failed_request(manager: BaseManager) -> WriteLedger:
    """
    Writes what a multi-document request would - one insert, a batch, an update that ADDS a key, a delete - and
    answers the ledger it recorded them in
    """
    ledger = WriteLedger()

    ledger.inserted(manager, manager.insert({'public_id': 10, 'name': 'new', 'parent': 0}))

    ledger.inserted_where(manager, {'parent': PARENT_ID})
    manager.insert_many([{'public_id': 11, 'parent': PARENT_ID}, {'public_id': 12, 'parent': PARENT_ID}],
                        skip_public=True)

    ledger.updated(manager, CHANGED['public_id'], manager.get_one_by({'public_id': CHANGED['public_id']}))
    manager.update({'public_id': CHANGED['public_id']}, {'name': 'after', 'added': True})

    ledger.deleted(manager, REMOVED['public_id'], manager.get_one_by({'public_id': REMOVED['public_id']}))
    manager.delete({'public_id': REMOVED['public_id']})

    return ledger


def test_the_undo_puts_the_collection_back_exactly(manager: BaseManager) -> None:
    """Same documents, same values, same _ids - and the key the update added is gone."""
    before = _stored(manager)

    residue = _a_failed_request(manager).undo()

    assert not residue
    assert _stored(manager) == before


def test_running_the_undo_twice_changes_nothing_more(manager: BaseManager) -> None:
    """Re-run safe: the second pass finds everything already undone and reports no residue."""
    before = _stored(manager)
    ledger = _a_failed_request(manager)
    ledger.undo()

    assert not ledger.undo()
    assert _stored(manager) == before


def test_writes_that_never_happened_are_undone_harmlessly(manager: BaseManager) -> None:
    """An update or delete is recorded before it runs; undoing one that did not run changes nothing."""
    before = _stored(manager)
    ledger = WriteLedger()
    ledger.updated(manager, CHANGED['public_id'], manager.get_one_by({'public_id': CHANGED['public_id']}))
    ledger.deleted(manager, REMOVED['public_id'], manager.get_one_by({'public_id': REMOVED['public_id']}))

    assert not ledger.undo()
    assert _stored(manager) == before
