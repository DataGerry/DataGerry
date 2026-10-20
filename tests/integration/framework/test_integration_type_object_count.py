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
Integration tests: `types_helper.count_objects_of_type` against a real MongoDB

The one count the Type delete guard and its pre-check route share: every object of the Type, active or not, and
nothing of another Type.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import count_objects_of_type
# -------------------------------------------------------------------------------------------------------------------- #

COUNTED_TYPE_ID: int = 89701
OTHER_TYPE_ID: int = 89702
EMPTY_TYPE_ID: int = 89703

ACTIVE_OBJECT_ID: int = 89711
INACTIVE_OBJECT_ID: int = 89712
OTHER_TYPE_OBJECT_ID: int = 89713
OBJECT_IDS: list[int] = [ACTIVE_OBJECT_ID, INACTIVE_OBJECT_ID, OTHER_TYPE_OBJECT_ID]
COUNTED_TYPE_OBJECTS: int = 2


def _object_doc(public_id: int, type_id: int, active: bool) -> dict[str, Any]:
    """An object of the given Type, written straight into the collection."""
    return {'public_id': public_id, 'type_id': type_id, 'active': active, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': []}


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager, database_name: str):
    """An ObjectsManager over one active and one inactive object of the counted Type, and one of another Type."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
    objects.insert_many([
        _object_doc(ACTIVE_OBJECT_ID, COUNTED_TYPE_ID, True),
        _object_doc(INACTIVE_OBJECT_ID, COUNTED_TYPE_ID, False),
        _object_doc(OTHER_TYPE_OBJECT_ID, OTHER_TYPE_ID, True),
    ])
    yield ObjectsManager(database_manager)
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})


class TestCountObjectsOfType:
    """The shared count, as stored."""

    def test_active_and_inactive_objects_are_counted(self, objects_manager: ObjectsManager) -> None:
        """Both of the counted Type's objects, the other Type's left out"""
        assert count_objects_of_type(objects_manager, COUNTED_TYPE_ID) == COUNTED_TYPE_OBJECTS

    def test_a_type_without_objects_counts_zero(self, objects_manager: ObjectsManager) -> None:
        """Nothing to block a delete"""
        assert count_objects_of_type(objects_manager, EMPTY_TYPE_ID) == 0
