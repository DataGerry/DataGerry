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
Integration tests for ``ObjectsManager.iterate_documents`` against a real MongoDB

The pickers' read: raw documents and the total, narrowed by an already-resolved type denial, and a refused read
raised as the manager's own iteration error - the error the two picker routes catch for their 400
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.object_model import CmdbObject
from cmdb.utils import find_cause

from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

READABLE_TYPE_ID: int = 97301
DENIED_TYPE_ID: int = 97302
READABLE_OBJECT_IDS: list[int] = [97311, 97312]
DENIED_OBJECT_ID: int = 97313
ALL_OBJECT_IDS: list[int] = [*READABLE_OBJECT_IDS, DENIED_OBJECT_ID]

# A query operator MongoDB does not know - it refuses the read itself
UNKNOWN_OPERATOR_CRITERIA: dict[str, Any] = {'public_id': {'$no_such_operator': 1}}


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A minimal stored CmdbObject document"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': []}


@pytest.fixture(name='objects_manager')
def _objects_manager(database_manager: MongoDatabaseManager, database_name: str):
    """Two readable objects and one of a denied type; removed again afterwards"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    objects.insert_many([
        *(_object(public_id, READABLE_TYPE_ID) for public_id in READABLE_OBJECT_IDS),
        _object(DENIED_OBJECT_ID, DENIED_TYPE_ID),
    ])

    yield ObjectsManager(database_manager, database_name)

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


def _own_objects() -> BuilderParameters:
    """A read scoped to this module's objects, so other seeds cannot interfere"""
    return BuilderParameters(criteria={'public_id': {'$in': ALL_OBJECT_IDS}})


def test_the_rows_are_the_raw_documents_with_their_total(objects_manager: ObjectsManager) -> None:
    """Every matching document, as a dict, and the count of all of them"""
    rows, total = objects_manager.iterate_documents(_own_objects())

    assert total == len(ALL_OBJECT_IDS)
    assert sorted(row['public_id'] for row in rows) == ALL_OBJECT_IDS
    assert all(isinstance(row, dict) for row in rows)


def test_the_denied_types_narrow_the_rows_and_the_total_alike(objects_manager: ObjectsManager) -> None:
    """A denied type's object is in neither, so a pager never counts a row it cannot show"""
    rows, total = objects_manager.iterate_documents(_own_objects(), [DENIED_TYPE_ID])

    assert total == len(READABLE_OBJECT_IDS)
    assert sorted(row['public_id'] for row in rows) == READABLE_OBJECT_IDS


def test_a_refused_read_is_the_managers_iteration_error(objects_manager: ObjectsManager) -> None:
    """MongoDB's own refusal arrives as ObjectsManagerIterationError, the class the picker routes catch"""
    with pytest.raises(ObjectsManagerIterationError) as caught:
        objects_manager.iterate_documents(BuilderParameters(criteria=UNKNOWN_OPERATOR_CRITERIA))

    assert find_cause(caught.value, BaseManagerIterationError) is not None
