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
Integration tests: what every location writer really stores satisfies ``CmdbLocation.SCHEMA``

The schema is the stored document's contract and no write runs it, so it is only true if the writers produce what it
says. Each writer is driven for real against MongoDB and its stored document validated:

- ``POST /locations/`` (the route that builds the document from three ids and the object's type)
- the object mirror (``location_helper.sync_object_location``) creating a node, then moving it - a partial ``$set``
  that must not leave the node short of a required key
- the seeded root (``get_root_location_data``), as inserted
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from cerberus import Validator

from cmdb.database import MongoDatabaseManager
from cmdb.database.predefined_data.cmdb_data.cmdb_location_data import get_root_location_data
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import LocationKey, RootLocationDefault
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import sync_object_location
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 89401
ROUTE_OBJECT_ID: int = 89411
MIRROR_OBJECT_ID: int = 89412
OBJECT_IDS: list[int] = [ROUTE_OBJECT_ID, MIRROR_OBJECT_ID]
NAME_FIELD: str = 'loc-name'
LOCATION_FIELD: str = 'loc-placement'


def _type_doc() -> dict[str, Any]:
    """A type its objects may be placed with, and selectable as a parent"""
    return {
        'public_id': TYPE_ID, 'name': 'location-contract', 'label': 'Location Contract', 'author_id': 1,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'selectable_as_parent': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
                   {'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'}],
        'render_meta': {'icon': 'fa-building', 'sections': [
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD, LOCATION_FIELD]},
        ], 'summary': {'fields': [NAME_FIELD]}},
        'acl': {'activated': False, 'groups': {'includes': {}}}, 'version': '1.0.0',
    }


def _object_doc(public_id: int) -> dict[str, Any]:
    """An object of the type, not yet placed - the create route only places an object with a location field"""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc),
            'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': f'site-{public_id}'},
                       {'type': 'location', 'name': LOCATION_FIELD, 'value': None}]}


@pytest.fixture(name='manager_app_context')
def fixture_app_context(rest_api):
    """Pushes the REST API app context so ManagerProvider resolves - only for the tests that call managers directly:
    a request through the test client pushes its own, and a manual one around it pops the wrong context"""
    with rest_api.application.app_context():
        yield


@pytest.fixture(name='locations')
def fixture_locations(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the type and objects; removes them and their locations afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        locations.delete_many({'object_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_many([_object_doc(public_id) for public_id in OBJECT_IDS])
    yield locations
    _purge()


def _admin() -> CmdbUser:
    """The admin request user"""
    return CmdbUser(public_id=1, user_name='admin', active=True, group_id=1)


def _assert_satisfies_the_schema(document: dict[str, Any] | None) -> None:
    """The stored document, as stored, validates - every required key present, every value of its type"""
    assert document is not None
    validator = Validator(CmdbLocation.SCHEMA, allow_unknown=False)
    stored: dict[str, Any] = {key: value for key, value in document.items() if key != '_id'}

    assert validator.validate(stored), validator.errors


class TestEveryWriterSatisfiesTheSchema:
    """The three ways a location document comes to exist."""

    def test_the_create_route(self, rest_api, locations) -> None:
        """POST /locations/ builds the document from three ids and the object's type"""
        response = rest_api.post('/locations/', json={
            LocationKey.OBJECT_ID.value: ROUTE_OBJECT_ID,
            LocationKey.PARENT.value: RootLocationDefault.PUBLIC_ID,
            LocationKey.TYPE_ID.value: TYPE_ID,
        })

        assert response.status_code == 200
        _assert_satisfies_the_schema(locations.find_one({'object_id': ROUTE_OBJECT_ID}))

    @pytest.mark.usefixtures('manager_app_context')
    def test_the_object_mirror_creating_and_moving_a_node(self, locations) -> None:
        """A create, then a move: the partial update leaves a complete node"""
        user: CmdbUser = _admin()
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, user)
        object_type = CmdbType.from_data(_type_doc())

        sync_object_location(MIRROR_OBJECT_ID, RootLocationDefault.PUBLIC_ID, None, object_type, user,
                             objects_manager, locations_manager)
        created: dict[str, Any] | None = locations.find_one({'object_id': MIRROR_OBJECT_ID})
        _assert_satisfies_the_schema(created)

        new_parent: int = locations_manager.insert_location({
            LocationKey.NAME.value: 'contract-parent', LocationKey.PARENT.value: RootLocationDefault.PUBLIC_ID,
            LocationKey.OBJECT_ID.value: ROUTE_OBJECT_ID, LocationKey.TYPE_ID.value: TYPE_ID,
            LocationKey.TYPE_LABEL.value: 'Location Contract',
        })
        sync_object_location(MIRROR_OBJECT_ID, new_parent, 'moved', object_type, user,
                             objects_manager, locations_manager)
        moved: dict[str, Any] | None = locations.find_one({'object_id': MIRROR_OBJECT_ID})

        assert moved[LocationKey.PARENT.value] == new_parent
        _assert_satisfies_the_schema(moved)

    def test_the_seeded_root(self, locations) -> None:
        """The root as the database holds it - inserted from the seed data when this database has none yet"""
        inserted: bool = locations.find_one({'public_id': RootLocationDefault.PUBLIC_ID}) is None

        if inserted:
            locations.insert_one(dict(get_root_location_data()))

        try:
            _assert_satisfies_the_schema(locations.find_one({'public_id': RootLocationDefault.PUBLIC_ID}))
        finally:
            if inserted:
                locations.delete_one({'public_id': RootLocationDefault.PUBLIC_ID})
