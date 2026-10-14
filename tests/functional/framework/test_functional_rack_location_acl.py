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
Functional tests for the Rack rule of a location write: joining a Rack through its node, or leaving one, needs READ and
UPDATE on that Rack - on every write that can do it

Seeded with ``tests/utils/rack_acl_seed`` (RACK and OTHER_RACK the editor may change, READ_ONLY_RACK it may only read,
HIDDEN_RACK it may not read) plus a location node for every Rack; the editor also holds the location edit and the
object add / edit rights. Memberships a test starts from are made by the administrator through the same routes.
Pinned, for the editor:

  - the single move, the batch move, the object update and the object create onto a Rack it may not change are a 403
    naming that Rack, nothing is written and no membership exists
  - leaving such a Rack (dragged elsewhere, or the location cleared) is a 403 and the membership stays; a move between
    two Racks needs both
  - a batch with one such object is refused whole
  - onto a Rack it may change, every write joins it as before
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import LocationRight
from cmdb.interface.rest_api.routes.rack_routes import rack_object_hooks
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackAccessError
from tests.utils import rack_acl_seed as seed
from tests.utils.rack_acl_seed import mount_of
# -------------------------------------------------------------------------------------------------------------------- #

LOCATIONS_URL: str = '/locations'
OBJECTS_URL: str = '/objects'
ROOT_NODE_ID: int = 1
NAME_FIELD: str = 'member-name'

# One location node per Rack, numbered after the seed's ids
RACK_NODES: dict[int, int] = {
    seed.RACK_ID: 98761, seed.OTHER_RACK_ID: 98762, seed.READ_ONLY_RACK_ID: 98763, seed.HIDDEN_RACK_ID: 98764,
}
UNCHANGEABLE_RACKS: list[int] = [seed.READ_ONLY_RACK_ID, seed.HIDDEN_RACK_ID]
CREATED_OBJECT_ID: int = 98781
EXTRA_RIGHTS: list[str] = [LocationRight.EDIT.value, ObjectRightName.EDIT.value, ObjectRightName.ADD.value]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Rack surface is licensed behind IPAM"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The rack ACL seed, a node for every Rack, the editor's extra rights"""
    seed.seed(database_manager, database_name)
    locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    locations.delete_many({'public_id': {'$in': list(RACK_NODES.values())}})
    locations.insert_many([{
        'public_id': node_id, 'name': f'rack-{rack_id}', 'parent': ROOT_NODE_ID, 'object_id': rack_id,
        'type_id': objects.find_one({'public_id': rack_id})['type_id'], 'type_label': 'Rack', 'type_icon': 'fa-cube',
        'type_selectable': True,
    } for rack_id, node_id in RACK_NODES.items()])
    # The seed's members carry no location field value; a move needs the entry to write to
    objects.update_many({'public_id': {'$in': [seed.OPEN_ID, seed.SECOND_OPEN_ID]}}, {'$push': {'fields': {
        'type': 'location', 'name': RackField.LOCATION.value, 'value': None,
    }}})
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': {'$each': EXTRA_RIGHTS}}},
    )

    yield

    locations.delete_many({'public_id': {'$in': list(RACK_NODES.values())}})
    objects.delete_many({'public_id': CREATED_OBJECT_ID})
    locations.delete_many({'object_id': CREATED_OBJECT_ID})
    seed.purge(database_manager, database_name)


def _editor() -> dict[str, Any]:
    """The request kwargs that send the seed's editor"""
    return {'user': seed.editor()}


def _move(rest_api, object_id: int, rack_id: int | None, **kwargs: Any) -> Any:
    """PATCH one object onto a Rack's node, or out of the tree with None"""
    parent: int | None = RACK_NODES[rack_id] if rack_id is not None else None

    return rest_api.patch(f'{LOCATIONS_URL}/{object_id}/parent', json={'parent': parent}, **kwargs)


def _rack_of(database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> int | None:
    """The Rack an object is a member of, if any"""
    mount: dict[str, Any] | None = mount_of(database_manager, database_name, object_id)

    return mount['rack_id'] if mount else None


def _object_payload(object_id: int, rack_id: int) -> dict[str, Any]:
    """An OPEN-type object whose location field points at a Rack's node"""
    return {
        'public_id': object_id, 'type_id': seed.OPEN_TYPE_ID, 'active': True, 'version': '1.0.0',
        'author_id': seed.EDITOR_ID,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': f'member-{object_id}'},
                   {'type': 'location', 'name': RackField.LOCATION.value, 'value': RACK_NODES[rack_id]}],
    }


def _denied(rack_id: int) -> str:
    """The 403 message for a Rack the editor may not change - read-only - or not read - hidden"""
    if rack_id == seed.HIDDEN_RACK_ID:
        return RackAccessError.RACK_READ_DENIED.format(object_id=rack_id)

    return RackAccessError.RACK_UPDATE_DENIED.format(object_id=rack_id)


class TestJoining:
    """Every write that can make an object a member asks the Rack"""

    @pytest.mark.parametrize('rack_id', UNCHANGEABLE_RACKS, ids=['read-only', 'hidden'])
    def test_a_drop_onto_an_unchangeable_rack_is_a_403(self, rest_api, database_manager, database_name: str,
                                                       rack_id: int) -> None:
        """The single move"""
        response = _move(rest_api, seed.OPEN_ID, rack_id, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _denied(rack_id)
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) is None

    @pytest.mark.parametrize('rack_id', UNCHANGEABLE_RACKS, ids=['read-only', 'hidden'])
    def test_a_batch_drop_is_refused_whole(self, rest_api, database_manager, database_name: str,
                                           rack_id: int) -> None:
        """Nothing of the batch moves"""
        response = rest_api.patch(f'{LOCATIONS_URL}/parents', json={
            'object_ids': [seed.OPEN_ID, seed.SECOND_OPEN_ID], 'parent': RACK_NODES[rack_id],
        }, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _denied(rack_id)
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) is None
        assert _rack_of(database_manager, database_name, seed.SECOND_OPEN_ID) is None

    def test_an_object_update_onto_an_unchangeable_rack_is_a_403(self, rest_api, database_manager,
                                                                 database_name: str) -> None:
        """The object form"""
        response = rest_api.put(f'{OBJECTS_URL}/{seed.OPEN_ID}',
                                json=_object_payload(seed.OPEN_ID, seed.READ_ONLY_RACK_ID), **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) is None

    def test_an_object_create_onto_an_unchangeable_rack_is_a_403(self, rest_api, database_manager,
                                                                 database_name: str) -> None:
        """Nothing is created"""
        response = rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(CREATED_OBJECT_ID, seed.READ_ONLY_RACK_ID),
                                 **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert database_manager.get_collection(CmdbObject.COLLECTION, database_name).count_documents(
            {'public_id': CREATED_OBJECT_ID}) == 0
        assert _rack_of(database_manager, database_name, CREATED_OBJECT_ID) is None

    def test_every_write_joins_a_changeable_rack(self, rest_api, database_manager, database_name: str) -> None:
        """The rule does not get in the way of an allowed write"""
        assert _move(rest_api, seed.OPEN_ID, seed.RACK_ID, **_editor()).status_code == HTTPStatus.OK
        assert rest_api.put(f'{OBJECTS_URL}/{seed.SECOND_OPEN_ID}',
                            json=_object_payload(seed.SECOND_OPEN_ID, seed.OTHER_RACK_ID),
                            **_editor()).status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.post(f'{OBJECTS_URL}/', json=_object_payload(CREATED_OBJECT_ID, seed.RACK_ID),
                             **_editor()).status_code == HTTPStatus.OK

        assert _rack_of(database_manager, database_name, seed.OPEN_ID) == seed.RACK_ID
        assert _rack_of(database_manager, database_name, seed.SECOND_OPEN_ID) == seed.OTHER_RACK_ID
        assert _rack_of(database_manager, database_name, CREATED_OBJECT_ID) == seed.RACK_ID


def test_a_batch_resolves_the_shared_parent_once(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager,
                                                database_name: str) -> None:
    """One Rack lookup for the whole batch, for the checks and the reconciles alike"""
    calls: list[Any] = []
    original = rack_object_hooks.find_rack_of_location_node

    def _counting(*args: Any) -> Any:
        calls.append(args)

        return original(*args)

    monkeypatch.setattr(rack_object_hooks, 'find_rack_of_location_node', _counting)

    response = rest_api.patch(f'{LOCATIONS_URL}/parents', json={
        'object_ids': [seed.OPEN_ID, seed.SECOND_OPEN_ID], 'parent': RACK_NODES[seed.RACK_ID],
    }, **_editor())

    assert response.status_code == HTTPStatus.OK
    assert len(calls) == 1
    assert _rack_of(database_manager, database_name, seed.SECOND_OPEN_ID) == seed.RACK_ID


class TestLeaving:
    """Leaving a Rack is a membership write on it too"""

    @pytest.mark.parametrize('rack_id', UNCHANGEABLE_RACKS, ids=['read-only', 'hidden'])
    @pytest.mark.parametrize('destination', [seed.RACK_ID, None], ids=['to-another-rack', 'cleared'])
    def test_leaving_an_unchangeable_rack_is_a_403(self, rest_api, database_manager, database_name: str,
                                                   rack_id: int, destination: int | None) -> None:
        """The membership the administrator made stays"""
        assert _move(rest_api, seed.OPEN_ID, rack_id).status_code == HTTPStatus.OK

        response = _move(rest_api, seed.OPEN_ID, destination, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == _denied(rack_id)
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) == rack_id

    def test_moving_between_two_changeable_racks_passes(self, rest_api, database_manager,
                                                        database_name: str) -> None:
        """Both judged, both allowed"""
        assert _move(rest_api, seed.OPEN_ID, seed.RACK_ID).status_code == HTTPStatus.OK

        response = _move(rest_api, seed.OPEN_ID, seed.OTHER_RACK_ID, **_editor())

        assert response.status_code == HTTPStatus.OK
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) == seed.OTHER_RACK_ID

    def test_an_object_update_clearing_the_location_of_a_member_is_a_403(self, rest_api, database_manager,
                                                                         database_name: str) -> None:
        """The object form, out of a Rack the editor may only read"""
        assert _move(rest_api, seed.OPEN_ID, seed.READ_ONLY_RACK_ID).status_code == HTTPStatus.OK
        payload: dict[str, Any] = _object_payload(seed.OPEN_ID, seed.READ_ONLY_RACK_ID)
        payload['fields'][1]['value'] = None

        response = rest_api.put(f'{OBJECTS_URL}/{seed.OPEN_ID}', json=payload, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) == seed.READ_ONLY_RACK_ID

    def test_staying_in_an_unchangeable_rack_is_no_membership_write(self, rest_api, database_manager,
                                                                    database_name: str) -> None:
        """An ordinary edit of a member sends its location back unchanged - no Rack is asked"""
        assert _move(rest_api, seed.OPEN_ID, seed.READ_ONLY_RACK_ID).status_code == HTTPStatus.OK

        response = rest_api.put(f'{OBJECTS_URL}/{seed.OPEN_ID}',
                                json=_object_payload(seed.OPEN_ID, seed.READ_ONLY_RACK_ID), **_editor())

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _rack_of(database_manager, database_name, seed.OPEN_ID) == seed.READ_ONLY_RACK_ID
