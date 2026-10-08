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
Functional tests: a CmdbLocation delete is all-or-nothing

Deleting a node is three writes - its children promoted onto its parent, the node removed, the child objects'
mirrored location fields re-pointed - and MongoDB transactions need a replica set DataGerry does not run on. The
delete path records each write in a WriteLedger, so a failure part-way puts everything back. These tests break
each later write in turn over `DELETE /objects/<public_id>` - deleting an object removes its node first, and a
failure there refuses the object delete - and compare the stored nodes and objects with the snapshot taken before
the request.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LOCATION_DELETE_UNDO_INCOMPLETE_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'
ROOT_PARENT_ID: int = 1

TOP_NODE_ID: int = 9941          # stays; the promotion target
DOOMED_NODE_ID: int = 9942       # the node being deleted
# The top node's object - only its node is seeded; object_id is unique, and 0 is the root's
TOP_OBJECT_ID: int = 9951
DOOMED_OBJECT_ID: int = 9952
CHILD_NODE_ID: int = 9943        # hangs under the doomed node
CHILD_OBJECT_ID: int = 9953      # owns the child node; its location field points at the doomed node

ALL_NODE_IDS: list[int] = [TOP_NODE_ID, DOOMED_NODE_ID, CHILD_NODE_ID]
ALL_OBJECT_IDS: list[int] = [DOOMED_OBJECT_ID, CHILD_OBJECT_ID]
TYPE_ID: int = 9960
LOCATION_FIELD: str = 'dg_location'


def _node(public_id: int, object_id: int, parent: int) -> dict[str, Any]:
    """A CmdbLocation document."""
    return {'public_id': public_id, 'name': f'node-{public_id}', 'parent': parent, 'object_id': object_id,
            'type_id': TYPE_ID, 'type_label': 'T', 'type_icon': 'fas fa-cube', 'type_selectable': True}


def _type() -> dict[str, Any]:
    """The CmdbType of both objects: one location field, no ACL."""
    return {'public_id': TYPE_ID, 'name': f'atomicity-type-{TYPE_ID}', 'label': 'T', 'author_id': 1,
            'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
            'fields': [{'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'}],
            'render_meta': {'icon': 'fa-cube', 'summary': {'fields': [LOCATION_FIELD]},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                          'fields': [LOCATION_FIELD]}]},
            'acl': {'activated': False, 'groups': {'includes': None}}}


def _object(public_id: int, location: int) -> dict[str, Any]:
    """A CmdbObject with a location field."""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc),
            'fields': [{'type': 'location', 'name': LOCATION_FIELD, 'value': location}]}


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Top node > doomed node > child node, with the child's object pointing at the doomed node."""
    nodes = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        nodes.delete_many({'public_id': {'$in': ALL_NODE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        types.delete_one({'public_id': TYPE_ID})

    _purge()
    types.insert_one(_type())
    nodes.insert_many([
        _node(TOP_NODE_ID, TOP_OBJECT_ID, ROOT_PARENT_ID),
        _node(DOOMED_NODE_ID, DOOMED_OBJECT_ID, TOP_NODE_ID),
        _node(CHILD_NODE_ID, CHILD_OBJECT_ID, DOOMED_NODE_ID),
    ])
    objects.insert_many([_object(DOOMED_OBJECT_ID, TOP_NODE_ID), _object(CHILD_OBJECT_ID, DOOMED_NODE_ID)])
    yield nodes, objects
    _purge()


def _snapshot(collections) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every test node and object as stored, without Mongo's _id."""
    nodes, objects = collections

    def _clean(collection, ids: list[int]) -> list[dict[str, Any]]:
        return sorted(({k: v for k, v in doc.items() if k != '_id'} for doc in collection.find({'public_id': {
            '$in': ids}})), key=lambda doc: doc['public_id'])

    return _clean(nodes, ALL_NODE_IDS), _clean(objects, ALL_OBJECT_IDS)


def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


def _delete(rest_api):
    """DELETE the doomed node's owning object, which removes the node first."""
    return rest_api.delete(f'{OBJECTS_URL}/{DOOMED_OBJECT_ID}')


class TestTheDeleteIsAllOrNothing:
    """Each later write broken in turn: the tree and the object fields stay exactly as they were."""

    def test_the_ordinary_delete_still_promotes_node_and_field(self, rest_api, collections) -> None:
        """The baseline: the child moves up to the top node, as a node and as an object field."""
        nodes, objects = collections

        response = _delete(rest_api)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT)
        assert nodes.find_one({'public_id': DOOMED_NODE_ID}) is None
        assert nodes.find_one({'public_id': CHILD_NODE_ID})['parent'] == TOP_NODE_ID
        assert objects.find_one({'public_id': CHILD_OBJECT_ID})['fields'][0]['value'] == TOP_NODE_ID

    def test_a_failed_node_delete_puts_the_promoted_children_back(
            self, rest_api, monkeypatch, collections) -> None:
        """The children were promoted, then the node would not go: they are back under it."""
        before = _snapshot(collections)
        monkeypatch.setattr(LocationsManager, 'delete', _raiser(RuntimeError('delete failed')))

        response = _delete(rest_api)

        assert response.status_code >= HTTPStatus.BAD_REQUEST
        assert _snapshot(collections) == before

    def test_a_failed_field_write_puts_the_node_and_the_children_back(
            self, rest_api, monkeypatch, collections) -> None:
        """
        The node was already deleted when the object fields failed: it is back under its old id, the children
        under it, and the fields still point at it - nothing dangles
        """
        before = _snapshot(collections)
        real_set = ObjectsManager.set_location_field_for_objects
        calls: dict[str, int] = {'count': 0}

        def _fail_first(self, object_ids, parent_id):
            calls['count'] += 1
            if calls['count'] == 1:
                raise RuntimeError('field write failed')
            return real_set(self, object_ids, parent_id)

        monkeypatch.setattr(ObjectsManager, 'set_location_field_for_objects', _fail_first)

        response = _delete(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_field_write_that_applied_but_reported_failure_is_undone(
            self, rest_api, monkeypatch, collections) -> None:
        """
        A partial update_many or a lost acknowledgement: the fields WERE re-pointed when the error came. The
        recorded inverse points them back at the node, so the object fields match the restored tree again
        """
        before = _snapshot(collections)
        real_set = ObjectsManager.set_location_field_for_objects
        calls: dict[str, int] = {'count': 0}

        def _apply_then_fail(self, object_ids, parent_id):
            calls['count'] += 1
            real_set(self, object_ids, parent_id)
            if calls['count'] == 1:
                raise RuntimeError('acknowledgement lost')

        monkeypatch.setattr(ObjectsManager, 'set_location_field_for_objects', _apply_then_fail)

        response = _delete(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_failed_field_write_whose_inverse_also_fails_is_still_clean(
            self, rest_api, monkeypatch, collections) -> None:
        """
        The field write failed before changing anything, so its inverse failing too leaves nothing to report:
        the verification finds the fields where they were, and the request fails with its own error
        """
        before = _snapshot(collections)
        monkeypatch.setattr(ObjectsManager, 'set_location_field_for_objects', _raiser(RuntimeError('down')))

        response = _delete(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_an_undo_that_cannot_finish_names_what_is_left(self, rest_api, monkeypatch) -> None:
        """The field write fails AND the deleted node cannot be re-inserted: the 500 names the node."""
        monkeypatch.setattr(ObjectsManager, 'set_location_field_for_objects', _raiser(RuntimeError('down')))
        monkeypatch.setattr(LocationsManager, 'insert', _raiser(RuntimeError('re-insert failed')))

        response = _delete(rest_api)
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(LOCATION_DELETE_UNDO_INCOMPLETE_MSG.split('{', maxsplit=1)[0])
        assert CmdbLocation.COLLECTION in message
        assert f"'public_id': {DOOMED_NODE_ID}" in message

    def test_an_applied_field_write_whose_inverse_fails_is_named(self, rest_api, monkeypatch) -> None:
        """
        The fields were re-pointed and the error came; re-pointing them back fails too. The verification finds
        them still at the top node, so the 500 names the object fields - the one write left in effect
        """
        real_set = ObjectsManager.set_location_field_for_objects
        calls: dict[str, int] = {'count': 0}

        def _apply_then_fail_then_refuse(self, object_ids, parent_id):
            calls['count'] += 1
            if calls['count'] == 1:
                real_set(self, object_ids, parent_id)
            raise RuntimeError('field write failed')

        monkeypatch.setattr(ObjectsManager, 'set_location_field_for_objects', _apply_then_fail_then_refuse)

        response = _delete(rest_api)
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(LOCATION_DELETE_UNDO_INCOMPLETE_MSG.split('{', maxsplit=1)[0])
        assert CmdbObject.COLLECTION in message
        assert str(CHILD_OBJECT_ID) in message
