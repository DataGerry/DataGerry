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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Integration tests of the sync's keys on a CmdbObject, against a real MongoDB

Pins: the declared ``system_ref`` index refuses a second object for the same user, lets a user and a user group with
the same id each have one, and leaves every object without a link out; ``ObjectsManager.update_object`` with a
model that carries no link keeps the stored link and fingerprint; and the import's overwrite (``plan_overwrite`` +
``replace_stored_object``) stores the stored link and fingerprint, not the file's.

The session's test database carries no production indexes, so the index is built here from the model's declaration
and dropped afterwards
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectSyncKey, SystemRefKind
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.importer.helper.object_import_writer import plan_overwrite, replace_stored_object
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42701
TYPE_NAME: str = 'system-ref-type'
SYNCED_ID: int = 42711
SECOND_SYNCED_ID: int = 42712
GROUP_SYNCED_ID: int = 42713
PLAIN_ID: int = 42714
SECOND_PLAIN_ID: int = 42715
SEEDED_IDS: list[int] = [SYNCED_ID, SECOND_SYNCED_ID, GROUP_SYNCED_ID, PLAIN_ID, SECOND_PLAIN_ID]
AUTHOR_ID: int = 42721
IMPORTER_ID: int = 42722
LINKED_RECORD_ID: int = 42731
FILE_RECORD_ID: int = 42732
STORED_SYNC_HASH: str = 'stored-fingerprint'
FILE_SYNC_HASH: str = 'file-fingerprint'
SYSTEM_REF_INDEX: str = 'system_ref_kind_id'

SYSTEM_REF: str = CmdbObjectKey.SYSTEM_REF.value
SYNC_HASH: str = CmdbObjectSyncKey.SYNC_HASH.value


def _link(kind: SystemRefKind, record_id: int = LINKED_RECORD_ID) -> dict[str, Any]:
    """The link of an object mirroring the record ``record_id`` of the given kind"""
    return {'kind': kind.value, 'id': record_id}


def _object_doc(public_id: int, value: str, **extra: Any) -> dict[str, Any]:
    """A complete CmdbObject document (deserialisable via CmdbObject.from_data)"""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': 'name', 'value': value}],
        'multi_data_sections': [],
        **extra,
    }


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str):
    """The objects collection with the model's link index built; the seeded objects and the index go afterwards"""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    declared = next(index for index in CmdbObject.get_index_keys() if index.document['name'] == SYSTEM_REF_INDEX)
    collection.create_indexes([declared])

    yield collection

    collection.delete_many({'public_id': {'$in': SEEDED_IDS}})
    collection.drop_index(SYSTEM_REF_INDEX)


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager, database_name: str):
    """An ObjectsManager wired to the test database, with the objects' Type seeded for its write guard"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_one(make_type_doc(TYPE_ID, TYPE_NAME))

    yield ObjectsManager(database_manager)

    types.delete_one({'public_id': TYPE_ID})


class TestTheLinkIndex:
    """One object per user and per user group; ordinary objects are not indexed."""

    def test_a_second_object_for_the_same_user_is_refused(self, objects: Any) -> None:
        """The database itself keeps the link one-to-one"""
        objects.insert_one(_object_doc(SYNCED_ID, 'first', **{SYSTEM_REF: _link(SystemRefKind.USER)}))

        with pytest.raises(DuplicateKeyError):
            objects.insert_one(_object_doc(SECOND_SYNCED_ID, 'second', **{SYSTEM_REF: _link(SystemRefKind.USER)}))

    def test_a_user_and_a_user_group_with_the_same_id_do_not_collide(self, objects: Any) -> None:
        """The kind is part of the key: the two id sequences overlap"""
        objects.insert_one(_object_doc(SYNCED_ID, 'person', **{SYSTEM_REF: _link(SystemRefKind.USER)}))
        objects.insert_one(_object_doc(GROUP_SYNCED_ID, 'group', **{SYSTEM_REF: _link(SystemRefKind.USER_GROUP)}))

        assert objects.count_documents({'public_id': {'$in': [SYNCED_ID, GROUP_SYNCED_ID]}}) == 2

    def test_objects_without_a_link_are_left_out(self, objects: Any) -> None:
        """Every ordinary object lacks the key - the partial filter keeps them from colliding"""
        objects.insert_one(_object_doc(PLAIN_ID, 'plain'))
        objects.insert_one(_object_doc(SECOND_PLAIN_ID, 'plain too'))

        assert objects.count_documents({'public_id': {'$in': [PLAIN_ID, SECOND_PLAIN_ID]}}) == 2


class TestUpdatesKeepTheLink:
    """A write built from the model never clears the stored sync keys."""

    def test_an_update_without_a_link_keeps_the_stored_one(
            self, objects: Any, objects_manager: ObjectsManager) -> None:
        """The model leaves a None link out, so the $set does not touch the stored link or fingerprint"""
        objects.insert_one(_object_doc(SYNCED_ID, 'stored',
                                       **{SYSTEM_REF: _link(SystemRefKind.USER), SYNC_HASH: STORED_SYNC_HASH}))

        objects_manager.update_object(SYNCED_ID, CmdbObject.from_data(_object_doc(SYNCED_ID, 'edited')))

        stored = objects.find_one({'public_id': SYNCED_ID})
        assert stored['fields'][0]['value'] == 'edited'
        assert (stored[SYSTEM_REF], stored[SYNC_HASH]) == (_link(SystemRefKind.USER), STORED_SYNC_HASH)

    def test_an_import_overwrite_stores_the_stored_sync_keys(
            self, objects: Any, objects_manager: ObjectsManager) -> None:
        """The whole-document replace keeps the stored link and fingerprint, not the file's"""
        objects.insert_one(_object_doc(SYNCED_ID, 'stored',
                                       **{SYSTEM_REF: _link(SystemRefKind.USER), SYNC_HASH: STORED_SYNC_HASH}))
        stored = objects.find_one({'public_id': SYNCED_ID})
        imported = _object_doc(SYNCED_ID, 'imported', author_id=IMPORTER_ID,
                               **{SYSTEM_REF: _link(SystemRefKind.USER, FILE_RECORD_ID), SYNC_HASH: FILE_SYNC_HASH})
        importer = CmdbUser(public_id=IMPORTER_ID, user_name='importer', active=True)

        replacement, _changes = plan_overwrite(stored, imported, importer)
        assert replace_stored_object(objects_manager, replacement)

        written = objects.find_one({'public_id': SYNCED_ID})
        assert written['fields'][0]['value'] == 'imported'
        assert (written[SYSTEM_REF], written[SYNC_HASH]) == (_link(SystemRefKind.USER), STORED_SYNC_HASH)
