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
Integration tests for the CmdbType CRUD surface of TypesManager

Pins the manager-layer behavior against a real MongoDB instance: insert returns the
new public_id and persists the doc, get_type resolves both as-dict and as-instance
shapes, update overwrites the existing payload, and delete removes the doc. The
manager methods do not enforce uniqueness or schema validation themselves — those
are route-layer concerns covered in the functional suite
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.types_manager import TypesManager
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

NAME_FIELD: str = 'type-field'
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

TYPE_ID_FOR_GET: int = 9501
TYPE_ID_FOR_UPDATE: int = 9502
TYPE_ID_FOR_DELETE: int = 9503
TYPE_ID_FOR_INSERT: int = 9504
MISSING_TYPE_ID: int = 9599

ORIGINAL_LABEL: str = 'Original Label'
UPDATED_LABEL: str = 'Updated Label'

SEED_TYPE_IDS: list[int] = [
    TYPE_ID_FOR_GET,
    TYPE_ID_FOR_UPDATE,
    TYPE_ID_FOR_DELETE,
    TYPE_ID_FOR_INSERT,
]


def _type_data(public_id: int, label: str) -> dict[str, Any]:
    """Builds a minimal CmdbType payload acceptable to ``TypesManager.insert_type``."""
    return {
        'public_id': public_id,
        'name': f'type-{public_id}',
        'label': label,
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded_types(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seed CmdbType docs after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbType.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': SEED_TYPE_IDS}})


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """Provides a TypesManager wired to the test database."""
    return TypesManager(database_manager)


def _delete_type_by_id(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one CmdbType doc directly via the collection, used for per-test cleanup."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertType:
    """``TypesManager.insert_type`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        types_manager: TypesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id of the new doc and a follow-up find sees the persisted row."""
        try:
            returned_id = types_manager.insert_type(_type_data(TYPE_ID_FOR_INSERT, ORIGINAL_LABEL))

            assert returned_id == TYPE_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
                .find_one({'public_id': TYPE_ID_FOR_INSERT})
            assert stored is not None
            assert stored['label'] == ORIGINAL_LABEL
        finally:
            _delete_type_by_id(database_manager, database_name, TYPE_ID_FOR_INSERT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        GET                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetType:
    """``TypesManager.get_type`` returns the doc by id and respects ``as_dict``."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        types_manager: TypesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single type before each test in this class and removes it after."""
        types_manager.insert_type(_type_data(TYPE_ID_FOR_GET, ORIGINAL_LABEL))
        yield
        _delete_type_by_id(database_manager, database_name, TYPE_ID_FOR_GET)

    def test_returns_dict_by_default(self, types_manager: TypesManager) -> None:
        """Default ``as_dict=True`` returns the doc as a dict."""
        result = types_manager.get_type(TYPE_ID_FOR_GET)

        assert isinstance(result, dict)
        assert result['public_id'] == TYPE_ID_FOR_GET

    def test_returns_cmdb_type_when_as_dict_false(self, types_manager: TypesManager) -> None:
        """``as_dict=False`` returns a ``CmdbType`` instance instead of a raw dict."""
        result = types_manager.get_type(TYPE_ID_FOR_GET, as_dict=False)

        assert isinstance(result, CmdbType)
        assert result.public_id == TYPE_ID_FOR_GET

    def test_returns_none_for_missing_id(self, types_manager: TypesManager) -> None:
        """A missing id returns None rather than raising."""
        assert types_manager.get_type(MISSING_TYPE_ID) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateType:
    """``TypesManager.update_type`` writes the new payload over the existing doc."""

    def test_persists_new_label(
        self,
        types_manager: TypesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Updating an existing type replaces the stored label."""
        try:
            types_manager.insert_type(_type_data(TYPE_ID_FOR_UPDATE, ORIGINAL_LABEL))

            updated_payload = _type_data(TYPE_ID_FOR_UPDATE, UPDATED_LABEL)
            types_manager.update_type(TYPE_ID_FOR_UPDATE, updated_payload)

            stored = types_manager.get_type(TYPE_ID_FOR_UPDATE)
            assert stored is not None
            assert stored['label'] == UPDATED_LABEL
        finally:
            _delete_type_by_id(database_manager, database_name, TYPE_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteType:
    """``TypesManager.delete_type`` removes the doc; a follow-up get returns None."""

    def test_removes_doc(
        self,
        types_manager: TypesManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing type makes it unretrievable; the manager returns no value."""
        types_manager.insert_type(_type_data(TYPE_ID_FOR_DELETE, ORIGINAL_LABEL))

        types_manager.delete_type(TYPE_ID_FOR_DELETE)

        assert types_manager.get_type(TYPE_ID_FOR_DELETE) is None
        # belt-and-braces cleanup in case delete_type semantics ever change
        _delete_type_by_id(database_manager, database_name, TYPE_ID_FOR_DELETE)
