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
Integration tests for cmdb.database.updater.versions.updater_20261118 against a real MongoDB

Seeds a Supernet type and a plain type with objects holding a missing, a null, a wrong and the right marker, plus an
object whose type is gone, runs the migration, and asserts every object holds its type's marker, the orphan is left
as it was, and a second run changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261118 import Update20261118
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

SUPERNET_TYPE: int = 48701
PLAIN_TYPE: int = 48702
GONE_TYPE: int = 48703
TYPE_IDS: list[int] = [SUPERNET_TYPE, PLAIN_TYPE]

# object id -> (type, stored marker, or the absent key)
ABSENT: object = object()
SEEDED: dict[int, tuple[int, Any]] = {
    48711: (SUPERNET_TYPE, ABSENT), 48712: (SUPERNET_TYPE, None), 48713: (SUPERNET_TYPE, 'SUBNET'),
    48714: (SUPERNET_TYPE, 'SUPERNET'), 48715: (PLAIN_TYPE, 'SUBNET'), 48716: (PLAIN_TYPE, None),
    48717: (GONE_TYPE, 'RACK'),
}
EXPECTED: dict[int, Any] = {48711: 'SUPERNET', 48712: 'SUPERNET', 48713: 'SUPERNET', 48714: 'SUPERNET',
                            48715: None, 48716: None, 48717: 'RACK'}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded types and objects, removed again after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': list(SEEDED)}})

    _purge()
    types.insert_many([{'public_id': SUPERNET_TYPE, 'name': 'marker-supernet', 'special_type': 'SUPERNET'},
                       {'public_id': PLAIN_TYPE, 'name': 'marker-plain', 'special_type': None}])
    objects.insert_many([
        {'public_id': public_id, 'type_id': type_id, **({} if marker is ABSENT else {'special_type': marker})}
        for public_id, (type_id, marker) in SEEDED.items()
    ])
    yield objects
    _purge()


def _markers(objects: Any) -> dict[int, Any]:
    """The stored marker of every seeded object"""
    return {document['public_id']: document.get('special_type', ABSENT)
            for document in objects.find({'public_id': {'$in': list(SEEDED)}})}


def test_every_object_gets_its_types_marker(database_manager: MongoDatabaseManager, database_name: str,
                                            objects: Any) -> None:
    """Missing, null and wrong alike; the orphan is left as it was"""
    Update20261118(database_manager, database_name).start_update()

    assert _markers(objects) == EXPECTED


def test_a_second_run_changes_nothing(database_manager: MongoDatabaseManager, database_name: str,
                                      objects: Any) -> None:
    """Every statement selects only the objects holding another marker"""
    Update20261118(database_manager, database_name).start_update()
    seen = list(objects.find({'public_id': {'$in': list(SEEDED)}}))

    Update20261118(database_manager, database_name).start_update()

    assert list(objects.find({'public_id': {'$in': list(SEEDED)}})) == seen
