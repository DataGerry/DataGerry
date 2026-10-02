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
Integration tests: the CmdbLocation delete path's undo against a real MongoDB, and a retry after it

`delete_location_with_reparenting` runs its three writes under a WriteLedger. With the real managers on a real
database: a failure in the last write leaves the nodes and object fields exactly as they were, and the SAME delete
retried afterwards succeeds - the undo leaves nothing behind that would trip a second run.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    delete_location_with_reparenting,
)
# -------------------------------------------------------------------------------------------------------------------- #

TOP_NODE_ID: int = 9971
DOOMED_NODE_ID: int = 9972
CHILD_NODE_ID: int = 9973
DOOMED_OBJECT_ID: int = 9982
CHILD_OBJECT_ID: int = 9983
TYPE_ID: int = 9990
ROOT_PARENT_ID: int = 1


def _node(public_id: int, object_id: int, parent: int) -> dict[str, Any]:
    """A CmdbLocation document."""
    return {'public_id': public_id, 'name': f'node-{public_id}', 'parent': parent, 'object_id': object_id,
            'type_id': TYPE_ID, 'type_label': 'T', 'type_icon': 'fas fa-cube', 'type_selectable': True}


def _object(public_id: int, location: int) -> dict[str, Any]:
    """A CmdbObject with a location field."""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc),
            'fields': [{'type': 'location', 'name': 'dg_location', 'value': location}]}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Top > doomed > child, the child's object pointing at the doomed node; the two real managers."""
    nodes = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    node_ids, object_ids = [TOP_NODE_ID, DOOMED_NODE_ID, CHILD_NODE_ID], [DOOMED_OBJECT_ID, CHILD_OBJECT_ID]

    def _purge() -> None:
        nodes.delete_many({'public_id': {'$in': node_ids}})
        objects.delete_many({'public_id': {'$in': object_ids}})

    _purge()
    nodes.insert_many([_node(TOP_NODE_ID, 0, ROOT_PARENT_ID), _node(DOOMED_NODE_ID, DOOMED_OBJECT_ID, TOP_NODE_ID),
                       _node(CHILD_NODE_ID, CHILD_OBJECT_ID, DOOMED_NODE_ID)])
    objects.insert_many([_object(DOOMED_OBJECT_ID, TOP_NODE_ID), _object(CHILD_OBJECT_ID, DOOMED_NODE_ID)])

    yield (LocationsManager(database_manager, database_name), ObjectsManager(database_manager, database_name),
           nodes, objects)
    _purge()


def _state(nodes, objects) -> tuple[list, list]:
    """The test's nodes and objects as stored, without _id."""
    def _clean(collection, ids):
        stored = collection.find({'public_id': {'$in': ids}})

        return sorted(({k: v for k, v in d.items() if k != '_id'} for d in stored), key=lambda d: d['public_id'])

    return (_clean(nodes, [TOP_NODE_ID, DOOMED_NODE_ID, CHILD_NODE_ID]),
            _clean(objects, [DOOMED_OBJECT_ID, CHILD_OBJECT_ID]))


def test_a_failed_field_write_is_undone_and_the_retry_succeeds(seeded, monkeypatch) -> None:
    """The undo restores everything; the second attempt then deletes cleanly, promoting node and field."""
    locations_manager, objects_manager, nodes, objects = seeded
    before = _state(nodes, objects)
    doomed: dict[str, Any] = nodes.find_one({'public_id': DOOMED_NODE_ID})
    real_set = ObjectsManager.set_location_field_for_objects
    calls: dict[str, int] = {'count': 0}

    def _fail_first(self, object_ids, parent_id):
        calls['count'] += 1
        if calls['count'] == 1:
            raise RuntimeError('field write failed')
        return real_set(self, object_ids, parent_id)

    monkeypatch.setattr(ObjectsManager, 'set_location_field_for_objects', _fail_first)

    with pytest.raises(RuntimeError):
        delete_location_with_reparenting(doomed, locations_manager, objects_manager)

    assert _state(nodes, objects) == before

    assert delete_location_with_reparenting(doomed, locations_manager, objects_manager) is True
    assert nodes.find_one({'public_id': DOOMED_NODE_ID}) is None
    assert nodes.find_one({'public_id': CHILD_NODE_ID})['parent'] == TOP_NODE_ID
    assert objects.find_one({'public_id': CHILD_OBJECT_ID})['fields'][0]['value'] == TOP_NODE_ID
