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
Integration tests for the ConfigItem limit against a real MongoDB

Two halves of the rule that only a real database can show:

- **what a stored limit reads back as.** A user document holding `null` reads as the default, one
  holding `0` reads as `0` - through `UsersManager`, so the stored BSON and `from_data` are both real
- **the importer's count.** An import reads the object count from the collection once and keeps it
  current with its own writes, so a limit one above the stored count admits exactly one new object,
  and the collection afterwards holds exactly that one

The importer is driven through its real per-object write over a real ObjectsManager; only the app's
cloud-mode flag is replaced, because the limit is a cloud-mode rule
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.class_schema.user_model.cmdb_user_schema import DEFAULT_CONFIG_ITEMS_LIMIT
from cmdb.framework.importer.importers.object_importer import ObjectImporter

from cmdb.errors.manager.objects_manager import ObjectsManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

IMPORTER_PATH: str = 'cmdb.framework.importer.importers.object_importer'

NULL_LIMIT_USER_ID: int = 9811
ZERO_LIMIT_USER_ID: int = 9812
LIMIT_USER_IDS: list[int] = [NULL_LIMIT_USER_ID, ZERO_LIMIT_USER_ID]

TYPE_ID: int = 9813
AUTHOR_ID: int = 1
VERSION: str = '1.0.0'


def _user_document(public_id: int, limit: Any) -> dict[str, Any]:
    """A stored user document whose config_items_limit holds exactly the given value."""
    return {
        'public_id': public_id,
        'user_name': f'limit-user-{public_id}',
        'active': True,
        'group_id': 1,
        'registration_time': datetime.now(timezone.utc),
        'config_items_limit': limit,
    }


def _type_document() -> dict[str, Any]:
    """An active, field-less CmdbType the imported objects are written into."""
    return {
        'public_id': TYPE_ID,
        'name': 'config-item-limit-import-type',
        'label': 'Config Item Limit Import Type',
        'author_id': AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [],
        'render_meta': {'icon': 'fa-cube', 'sections': [], 'summary': {'fields': []}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': VERSION,
    }


def _import_object() -> dict[str, Any]:
    """A normalized import row without a public_id, so the importer assigns a fresh one."""
    return {
        'type_id': TYPE_ID,
        'author_id': AUTHOR_ID,
        'active': True,
        'version': VERSION,
        'creation_time': datetime.now(timezone.utc),
        'fields': [],
    }


@pytest.fixture(name='users_manager')
def fixture_users_manager(database_manager: MongoDatabaseManager) -> UsersManager:
    """A UsersManager wired to the test database."""
    return UsersManager(database_manager)


@pytest.fixture(name='stored_limit_users')
def fixture_stored_limit_users(database_manager: MongoDatabaseManager, database_name: str):
    """Stores one user with a null limit and one with a limit of 0, removed afterwards."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': {'$in': LIMIT_USER_IDS}})
    users.insert_many([
        _user_document(NULL_LIMIT_USER_ID, None),
        _user_document(ZERO_LIMIT_USER_ID, 0),
    ])
    yield
    users.delete_many({'public_id': {'$in': LIMIT_USER_IDS}})


@pytest.fixture(name='import_type')
def fixture_import_type(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the target CmdbType and removes it and every object written into it afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    types.insert_one(_type_document())
    yield
    types.delete_many({'public_id': TYPE_ID})
    objects.delete_many({'type_id': TYPE_ID})


def _importer(database_manager: MongoDatabaseManager, limit: int) -> ObjectImporter:
    """A real ObjectImporter over a real ObjectsManager, built without a file or a parser."""
    importer: ObjectImporter = ObjectImporter.__new__(ObjectImporter)
    importer.objects_manager = ObjectsManager(database_manager)
    importer.request_user = CmdbUser(public_id=AUTHOR_ID, user_name='importer', active=True,
                                     config_items_limit=limit)
    importer._object_count = None  # pylint: disable=protected-access

    return importer


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the stored limit, read back                                              #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.usefixtures('stored_limit_users')
class TestStoredLimitReadsBack:
    """What a user document's limit means once UsersManager has read it"""

    def test_a_stored_null_reads_as_the_default(self, users_manager: UsersManager) -> None:
        """null is "not configured" and becomes the default on the way out of the database"""
        assert users_manager.get_user(NULL_LIMIT_USER_ID).config_items_limit == DEFAULT_CONFIG_ITEMS_LIMIT

    def test_a_stored_zero_reads_as_zero_and_refuses(self, users_manager: UsersManager) -> None:
        """0 survives the read and is a real limit - even an empty tenant may not create an object"""
        user: CmdbUser = users_manager.get_user(ZERO_LIMIT_USER_ID)

        assert user.config_items_limit == 0
        assert user.is_config_item_limit_reached(0) is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the importer's single count                                              #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.usefixtures('import_type')
class TestImportCountsOnce:
    """A limit one above the stored count admits exactly one imported object"""

    def test_one_free_slot_admits_one_row_and_refuses_the_next(
            self, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The second row is refused although nothing re-read the collection in between"""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        importer = _importer(database_manager, limit=objects.count_documents({}) + 1)

        with patch(f'{IMPORTER_PATH}.current_app', SimpleNamespace(cloud_mode=True)), \
             patch.object(importer.objects_manager, 'count_documents',
                          wraps=importer.objects_manager.count_documents) as counted:
            importer._import_single_object(_import_object())  # pylint: disable=protected-access

            with pytest.raises(ObjectsManagerInsertError):
                importer._import_single_object(_import_object())  # pylint: disable=protected-access

        assert objects.count_documents({'type_id': TYPE_ID}) == 1
        counted.assert_called_once_with()
