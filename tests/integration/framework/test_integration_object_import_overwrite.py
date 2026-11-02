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
Integration tests for the object import's overwrite write (cmdb.framework.importer.helper.object_import_writer)

Pins, against a real MongoDB: ``replace_stored_object`` replaces the stored document in place - the ``_id`` is
kept, a key the imported row lacks is gone, the object count does not move - and answers False, writing nothing,
when no object carries the public_id; a refused replace leaves the stored document as it was; and
``plan_overwrite`` + the replace together store an edit of the object (stored authorship, bumped version,
the importer as editor)
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.framework.importer.helper.object_import_writer import plan_overwrite, replace_stored_object
from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42601
OTHER_TYPE_ID: int = 42602
OVERWRITTEN_ID: int = 42611
MISSING_ID: int = 42612
STORED_AUTHOR_ID: int = 42621
IMPORTER_ID: int = 42622
STORED_VERSION: str = '1.4.2'
BUMPED_VERSION: str = '1.4.3'
STORED_ONLY_KEY: str = 'stored_only_key'
STORED_CREATION_TIME: datetime = datetime(2024, 3, 4, tzinfo=timezone.utc)
UNIQUE_KEY_INDEX: str = 'import_overwrite_unique_key'


def _object_doc(public_id: int, value: str, type_id: int = TYPE_ID) -> dict[str, Any]:
    """A complete CmdbObject document (deserialisable via CmdbObject.from_data)"""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': IMPORTER_ID,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': 'name', 'value': value}],
        'multi_data_sections': [],
    }


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """An ObjectsManager wired to the test database"""
    return ObjectsManager(database_manager)


@pytest.fixture(name='stored_object')
def fixture_stored_object(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the object the import overwrites - with a key the imported row lacks - and removes it afterwards"""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    document: dict[str, Any] = _object_doc(OVERWRITTEN_ID, 'stored')
    document.update(author_id=STORED_AUTHOR_ID, creation_time=STORED_CREATION_TIME, version=STORED_VERSION)
    document[STORED_ONLY_KEY] = 'only in the stored document'
    collection.insert_one(document)

    yield collection.find_one({'public_id': OVERWRITTEN_ID})

    collection.delete_many({'public_id': {'$in': [OVERWRITTEN_ID, MISSING_ID]}})


class TestReplaceStoredObject:
    """One atomic replace of the stored document."""

    def test_the_document_is_replaced_in_place(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
            stored_object: dict[str, Any]) -> None:
        """The _id survives, the stored-only key is gone, the row's values and type are stored"""
        assert replace_stored_object(objects_manager, _object_doc(OVERWRITTEN_ID, 'imported', OTHER_TYPE_ID))

        written: dict[str, Any] = database_manager.get_collection(
            CmdbObject.COLLECTION, database_name).find_one({'public_id': OVERWRITTEN_ID})
        assert written['_id'] == stored_object['_id']
        assert STORED_ONLY_KEY not in written
        assert (written['type_id'], written['fields'][0]['value']) == (OTHER_TYPE_ID, 'imported')

    def test_the_object_count_does_not_move(
            self, objects_manager: ObjectsManager, stored_object: dict[str, Any]) -> None:
        """Nothing is deleted or added"""
        before: int = objects_manager.count_documents()

        replace_stored_object(objects_manager, _object_doc(stored_object['public_id'], 'imported'))

        assert objects_manager.count_documents() == before

    def test_nothing_matched_writes_nothing(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager,
            database_name: str) -> None:
        """No object under the id: False, and no object is created by the replace"""
        assert replace_stored_object(objects_manager, _object_doc(MISSING_ID, 'imported')) is False

        collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        assert collection.find_one({'public_id': MISSING_ID}) is None

    def test_a_refused_replace_leaves_the_stored_document(
            self, objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
            stored_object: dict[str, Any]) -> None:
        """A unique-index clash refuses the write; the stored object is exactly as it was"""
        collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        collection.insert_one({'public_id': MISSING_ID, 'type_id': TYPE_ID, 'fields': [],
                               UNIQUE_KEY_INDEX: 'taken'})
        collection.create_index(UNIQUE_KEY_INDEX, name=UNIQUE_KEY_INDEX, unique=True, sparse=True)
        clashing: dict[str, Any] = _object_doc(OVERWRITTEN_ID, 'imported')

        try:
            with pytest.raises(ObjectsManagerUpdateError):
                replace_stored_object(_ClashingManager(objects_manager), clashing)
        finally:
            collection.drop_index(UNIQUE_KEY_INDEX)

        assert collection.find_one({'public_id': OVERWRITTEN_ID}) == stored_object


class _ClashingManager:
    """Forwards the replace with a value that clashes with a unique index, so the database refuses it"""

    def __init__(self, objects_manager: ObjectsManager) -> None:
        self.objects_manager = objects_manager

    def replace(self, public_id: int, document: dict[str, Any]) -> Any:
        """The real replace, of a document that duplicates the unique key"""
        return self.objects_manager.replace(public_id, {**document, UNIQUE_KEY_INDEX: 'taken'})


class TestPlannedOverwrite:
    """The planned document, stored: an edit of the object."""

    def test_the_stored_object_records_an_edit(
            self, objects_manager: ObjectsManager, stored_object: dict[str, Any]) -> None:
        """Stored author + creation time kept, version bumped from the stored one, importer as editor"""
        importer = CmdbUser(public_id=IMPORTER_ID, user_name='importer', active=True)
        replacement, changes = plan_overwrite(stored_object, _object_doc(OVERWRITTEN_ID, 'imported'), importer)

        replace_stored_object(objects_manager, replacement)

        written: dict[str, Any] = objects_manager.get_one(OVERWRITTEN_ID)
        assert written['author_id'] == STORED_AUTHOR_ID
        assert written['creation_time'].replace(tzinfo=timezone.utc) == STORED_CREATION_TIME
        assert (written['version'], written['editor_id']) == (BUMPED_VERSION, IMPORTER_ID)
        assert changes['new'] == [{'type': 'text', 'name': 'name', 'value': 'imported'}]
