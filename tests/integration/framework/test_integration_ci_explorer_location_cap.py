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
Integration tests for the CI Explorer's location-children cap, against a real MongoDB

`collect_location_children_objects` reads the objects under one location node through the real managers. The
children are written in DESCENDING id order, so MongoDB's natural order is the reverse of the public_id order:
the cap must still keep the lowest ids, the same ones on every read, and an uncapped read returns them all in
id order
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.ci_explorer.locations import collect_location_children_objects
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

PARENT_NODE_ID: int = 89701
# The parent node's object - only its node is seeded; object_id is unique, and 0 is the root's
PARENT_OBJECT_ID: int = 89700
CHILD_NODE_BASE: int = 89710
TYPE_ID: int = 89790
CHILD_OBJECT_IDS: list[int] = [89751, 89752, 89753, 89754, 89755]
CAP: int = 3


def _node(public_id: int, object_id: int, parent: int) -> dict[str, Any]:
    """A CmdbLocation document"""
    return {'public_id': public_id, 'name': f'node-{public_id}', 'parent': parent, 'object_id': object_id,
            'type_id': TYPE_ID, 'type_label': 'Cap', 'type_icon': 'fa-cube', 'type_selectable': True}


def _object(public_id: int) -> dict[str, Any]:
    """A CmdbObject"""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': []}


@pytest.fixture(name='managers')
def fixture_managers(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A parent node with five children, written highest id first; the request context the managers resolve in"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)

    def _purge() -> None:
        objects.delete_many({'public_id': {'$in': CHILD_OBJECT_IDS}})
        locations.delete_many({'$or': [{'public_id': PARENT_NODE_ID}, {'object_id': {'$in': CHILD_OBJECT_IDS}}]})

    _purge()
    locations.insert_one(_node(PARENT_NODE_ID, PARENT_OBJECT_ID, 1))
    for offset, object_id in enumerate(reversed(CHILD_OBJECT_IDS)):
        objects.insert_one(_object(object_id))
        locations.insert_one(_node(CHILD_NODE_BASE + offset, object_id, PARENT_NODE_ID))

    with rest_api.application.test_request_context():
        yield LocationsManager(database_manager), ObjectsManager(database_manager)

    _purge()


def _children(managers: tuple[LocationsManager, ObjectsManager], remaining: int, capped: bool) -> list[int]:
    """The ids the collector returns for the parent node"""
    locations_manager, objects_manager = managers
    found = collect_location_children_objects(
        {'public_id': PARENT_NODE_ID, 'parent': 1, 'object_id': PARENT_OBJECT_ID}, frozenset(), remaining, capped,
        locations_manager, objects_manager,
    )

    return [child['public_id'] for child in found]


def test_natural_order_is_not_the_id_order(database_manager: MongoDatabaseManager, database_name: str,
                                           managers) -> None:
    """The precondition: without a sort the children would come back highest id first"""
    del managers
    natural = [doc['public_id'] for doc in database_manager.get_collection(CmdbObject.COLLECTION, database_name)
               .find({'public_id': {'$in': CHILD_OBJECT_IDS}})]

    assert natural != CHILD_OBJECT_IDS


def test_the_cap_keeps_the_lowest_ids(managers) -> None:
    """Sorted before the slice"""
    assert _children(managers, CAP, capped=True) == CHILD_OBJECT_IDS[:CAP]


def test_the_same_children_on_every_read(managers) -> None:
    """Re-run safe: the read is deterministic"""
    assert _children(managers, CAP, capped=True) == _children(managers, CAP, capped=True)


def test_an_uncapped_read_returns_every_child_in_id_order(managers) -> None:
    """No cap, no truncation"""
    assert _children(managers, 0, capped=False) == CHILD_OBJECT_IDS
