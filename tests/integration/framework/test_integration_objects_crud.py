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
Integration tests for the CmdbObject CRUD surface of ObjectsManager

Pins the manager-layer behavior against a real MongoDB instance: insert returns the
new public_id and persists the doc, get_object resolves both as-dict and as-instance
shapes, update writes the new payload, and delete reports whether the doc existed
and removes it from storage. The setup seeds one active CmdbType so that the
``get_object_type`` lookups inside the manager succeed
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType

from cmdb.errors.manager.objects_manager import ObjectsManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

SEED_TYPE_ID: int = 9201
SEED_TYPE_NAME: str = 'test-crud-type'
NAME_FIELD: str = 'name-field'
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'
OBJECT_ID_FOR_GET: int = 9211
OBJECT_ID_FOR_UPDATE: int = 9212
OBJECT_ID_FOR_DELETE: int = 9213
OBJECT_ID_FOR_INSERT: int = 9214
MISSING_OBJECT_ID: int = 9299

UNKNOWN_TYPE_ID: int = 9999

ORIGINAL_VALUE: str = 'before'
UPDATED_VALUE: str = 'after'

SEED_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_UPDATE,
    OBJECT_ID_FOR_DELETE,
]


def _type_doc() -> dict[str, Any]:
    """Builds a minimal active CmdbType doc the ObjectsManager type-lookups will accept."""
    return {
        'public_id': SEED_TYPE_ID,
        'name': SEED_TYPE_NAME,
        'label': 'CRUD Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _object_data(public_id: int, value: str) -> dict[str, Any]:
    """Builds a CmdbObject payload acceptable to ``ObjectsManager.insert_object``."""
    return {
        'public_id': public_id,
        'type_id': SEED_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value}],
    }


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Inserts the seed CmdbType used by every test and removes the type + any leftover objects after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(_type_doc())
    yield
    types.delete_one({'public_id': SEED_TYPE_ID})
    objects.delete_many({'public_id': {'$in': SEED_OBJECT_IDS + [OBJECT_ID_FOR_INSERT]}})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


def _delete_object_by_id(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one CmdbObject doc directly via the collection, used for per-test cleanup."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertObject:
    """``ObjectsManager.insert_object`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        objects_manager: ObjectsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id of the new doc and a follow-up get sees the persisted row."""
        try:
            returned_id = objects_manager.insert_object(_object_data(OBJECT_ID_FOR_INSERT, ORIGINAL_VALUE))

            assert returned_id == OBJECT_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
                .find_one({'public_id': OBJECT_ID_FOR_INSERT})
            assert stored is not None
            assert stored['type_id'] == SEED_TYPE_ID
            assert stored['fields'][0]['value'] == ORIGINAL_VALUE
        finally:
            _delete_object_by_id(database_manager, database_name, OBJECT_ID_FOR_INSERT)

    def test_unknown_type_id_raises(self, objects_manager: ObjectsManager) -> None:
        """Inserting an object whose type_id has no matching CmdbType raises an insert error."""
        payload = _object_data(OBJECT_ID_FOR_INSERT, ORIGINAL_VALUE)
        payload['type_id'] = UNKNOWN_TYPE_ID

        with pytest.raises(ObjectsManagerInsertError):
            objects_manager.insert_object(payload)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        GET                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetObject:
    """``ObjectsManager.get_object`` returns the doc by id and respects ``as_dict``."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        objects_manager: ObjectsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single object before each test in this class and removes it after."""
        objects_manager.insert_object(_object_data(OBJECT_ID_FOR_GET, ORIGINAL_VALUE))
        yield
        _delete_object_by_id(database_manager, database_name, OBJECT_ID_FOR_GET)

    def test_returns_dict_by_default(self, objects_manager: ObjectsManager) -> None:
        """Default ``as_dict=True`` returns the doc as a JSON-shaped dict."""
        result = objects_manager.get_object(OBJECT_ID_FOR_GET)

        assert isinstance(result, dict)
        assert result['public_id'] == OBJECT_ID_FOR_GET

    def test_returns_cmdb_object_when_as_dict_false(self, objects_manager: ObjectsManager) -> None:
        """``as_dict=False`` returns a ``CmdbObject`` instance instead of a raw dict."""
        result = objects_manager.get_object(OBJECT_ID_FOR_GET, as_dict=False)

        assert isinstance(result, CmdbObject)
        assert result.public_id == OBJECT_ID_FOR_GET

    def test_returns_none_for_missing_id(self, objects_manager: ObjectsManager) -> None:
        """A missing id returns None rather than raising."""
        assert objects_manager.get_object(MISSING_OBJECT_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateObject:
    """``ObjectsManager.update_object`` writes the new payload over the existing doc."""

    def test_persists_new_field_value(
        self,
        objects_manager: ObjectsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Updating an existing object replaces the stored field value."""
        try:
            objects_manager.insert_object(_object_data(OBJECT_ID_FOR_UPDATE, ORIGINAL_VALUE))

            updated_payload = _object_data(OBJECT_ID_FOR_UPDATE, UPDATED_VALUE)
            objects_manager.update_object(OBJECT_ID_FOR_UPDATE, updated_payload)

            stored = objects_manager.get_object(OBJECT_ID_FOR_UPDATE)
            assert stored is not None
            assert stored['fields'][0]['value'] == UPDATED_VALUE
        finally:
            _delete_object_by_id(database_manager, database_name, OBJECT_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteObject:
    """``ObjectsManager.delete_object`` reports success and removes the doc."""

    def test_returns_true_and_removes_doc(
        self,
        objects_manager: ObjectsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing object returns True and the doc no longer resolves via get_object."""
        objects_manager.insert_object(_object_data(OBJECT_ID_FOR_DELETE, ORIGINAL_VALUE))

        deleted = objects_manager.delete_object(OBJECT_ID_FOR_DELETE)

        assert deleted is True
        assert objects_manager.get_object(OBJECT_ID_FOR_DELETE) is None
        # belt-and-braces cleanup in case delete_object semantics ever change
        _delete_object_by_id(database_manager, database_name, OBJECT_ID_FOR_DELETE)

    def test_returns_false_for_missing_id(self, objects_manager: ObjectsManager) -> None:
        """Deleting a non-existent id returns False without raising."""
        assert objects_manager.delete_object(MISSING_OBJECT_ID) is False
