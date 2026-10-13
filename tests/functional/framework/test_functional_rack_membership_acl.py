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
The object ACL on the Rack routes - end to end, for a rack editor the ACL does not grant everything

The editor holds the rack rights and the object view right. Pinned for every rack route:

* a membership write - mount, a cross-rack move, re-place, unmount - asks READ and UPDATE on the Rack and on the
  member: a 403 naming the object it fails on, and nothing written (no mount row, no location node)
* a rack read - overview, mounts, height conflicts, picker, dry run, mount of an object - asks READ on the Rack
* the dry run reports the same reasons the write refuses with, and a missing object stays a 400 apart from a hidden
  one's 403
* the administrator, and the editor on what the ACL grants it, keep every route
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_DENIED_MSG,
    LINKED_OBJECT_UPDATE_DENIED_MSG,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackAccessError
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils import rack_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

RACKS_URL: str = '/racks'
UNASSIGNED: str = 'UNASSIGNED'
FRONT: str = 'FRONT'


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Rack View is gated behind the IPAM feature"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The racks, the members and the editor; removed by id after"""
    seed.seed(database_manager, database_name)
    yield
    seed.purge(database_manager, database_name)


def _editor() -> dict[str, Any]:
    """The request kwargs that send it as the rack editor"""
    return {'user': seed.editor()}


def _mount(rest_api, rack_id: int, object_id: int, **kwargs: Any):
    """POST a mount"""
    return rest_api.post(f'{RACKS_URL}/{rack_id}/mounts/', json={'object_id': object_id}, **kwargs)


def _message(response) -> str:
    """The error message of a refusal"""
    return response.get_json()['message']


class TestMounting:
    """POST /racks/<id>/mounts/ - the Rack and the member are both written to."""

    def test_an_open_member_into_an_open_rack(self, rest_api, database_manager, database_name) -> None:
        """What the ACL grants: 201"""
        assert _mount(rest_api, seed.RACK_ID, seed.OPEN_ID, **_editor()).status_code == HTTPStatus.CREATED

    @pytest.mark.parametrize('object_id,message', [
        (seed.HIDDEN_ID, LINKED_OBJECT_DENIED_MSG.format(object_id=seed.HIDDEN_ID)),
        (seed.READ_ONLY_ID, LINKED_OBJECT_UPDATE_DENIED_MSG.format(object_id=seed.READ_ONLY_ID)),
        (seed.DEACTIVATED_ID, None),
    ], ids=['hidden', 'read-only', 'deactivated'])
    def test_a_member_the_editor_may_not_move_is_403_and_nothing_is_written(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
            object_id: int, message: str | None) -> None:
        """No mount row, no location node - refused before anything is written"""
        response = _mount(rest_api, seed.RACK_ID, object_id, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        if message:
            assert _message(response) == message
        assert seed.mount_of(database_manager, database_name, object_id) is None
        assert database_manager.get_collection(CmdbLocation.COLLECTION, database_name).find_one(
            {'object_id': object_id}) is None

    @pytest.mark.parametrize('rack_id,message', [
        (seed.HIDDEN_RACK_ID, RackAccessError.RACK_READ_DENIED.format(object_id=seed.HIDDEN_RACK_ID)),
        (seed.READ_ONLY_RACK_ID, RackAccessError.RACK_UPDATE_DENIED.format(object_id=seed.READ_ONLY_RACK_ID)),
    ], ids=['hidden-rack', 'read-only-rack'])
    def test_a_rack_the_editor_may_not_change_is_403(
            self, rest_api, database_manager, database_name, rack_id: int, message: str) -> None:
        """Naming the Rack"""
        response = _mount(rest_api, rack_id, seed.OPEN_ID, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _message(response) == message
        assert seed.mount_of(database_manager, database_name, seed.OPEN_ID) is None

    def test_a_hidden_id_is_403_and_a_missing_one_stays_a_400(self, rest_api) -> None:
        """A refusal says it exists - like GET /objects/<id> - and says nothing more"""
        assert _mount(rest_api, seed.RACK_ID, seed.HIDDEN_ID, **_editor()).status_code == HTTPStatus.FORBIDDEN
        assert _mount(rest_api, seed.RACK_ID, seed.MISSING_ID, **_editor()).status_code == HTTPStatus.BAD_REQUEST

    def test_the_administrator_mounts_every_member(self, rest_api) -> None:
        """The ACL grants the administrators everything here"""
        for object_id in (seed.HIDDEN_ID, seed.READ_ONLY_ID):
            assert _mount(rest_api, seed.HIDDEN_RACK_ID, object_id).status_code == HTTPStatus.CREATED


class TestACrossRackMove:
    """Mounting an object another Rack holds takes it out of that Rack - a write on that Rack too."""

    def test_out_of_a_rack_the_editor_may_not_change_is_403(self, rest_api, database_manager, database_name) -> None:
        """The object stays where it was"""
        assert _mount(rest_api, seed.HIDDEN_RACK_ID, seed.OPEN_ID).status_code == HTTPStatus.CREATED

        response = _mount(rest_api, seed.RACK_ID, seed.OPEN_ID, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _message(response) == RackAccessError.RACK_READ_DENIED.format(object_id=seed.HIDDEN_RACK_ID)
        assert seed.mount_of(database_manager, database_name, seed.OPEN_ID)['rack_id'] == seed.HIDDEN_RACK_ID

    def test_between_two_racks_the_editor_may_change(self, rest_api, database_manager, database_name) -> None:
        """Allowed: the object moves"""
        assert _mount(rest_api, seed.OTHER_RACK_ID, seed.OPEN_ID).status_code == HTTPStatus.CREATED

        assert _mount(rest_api, seed.RACK_ID, seed.OPEN_ID, **_editor()).status_code == HTTPStatus.CREATED
        assert seed.mount_of(database_manager, database_name, seed.OPEN_ID)['rack_id'] == seed.RACK_ID


class TestReplacingAndUnmounting:
    """PATCH and DELETE on a mount ask the same of the member as joining did."""

    @pytest.fixture(name='hidden_mount')
    def fixture_hidden_mount(self, rest_api, database_manager, database_name) -> dict[str, Any]:
        """The hidden member, mounted by the administrator"""
        assert _mount(rest_api, seed.RACK_ID, seed.HIDDEN_ID).status_code == HTTPStatus.CREATED

        return seed.mount_of(database_manager, database_name, seed.HIDDEN_ID)

    def test_placing_a_hidden_member_is_403(self, rest_api, hidden_mount, database_manager, database_name) -> None:
        """Its slot is where it physically is - the placement is unchanged"""
        response = rest_api.patch(f'{RACKS_URL}/{seed.RACK_ID}/mounts/{hidden_mount["public_id"]}',
                                  json={'area': FRONT, 'start_slot': 1, 'height': 1}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert seed.mount_of(database_manager, database_name, seed.HIDDEN_ID)['area'] == UNASSIGNED

    def test_unmounting_a_hidden_member_is_403(self, rest_api, hidden_mount, database_manager, database_name) -> None:
        """The membership stays"""
        response = rest_api.delete(f'{RACKS_URL}/{seed.RACK_ID}/mounts/{hidden_mount["public_id"]}', **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert seed.mount_of(database_manager, database_name, seed.HIDDEN_ID) is not None

    def test_an_open_member_is_placed_and_unmounted(self, rest_api, database_manager, database_name) -> None:
        """What the ACL grants"""
        assert _mount(rest_api, seed.RACK_ID, seed.OPEN_ID, **_editor()).status_code == HTTPStatus.CREATED
        mount_id: int = seed.mount_of(database_manager, database_name, seed.OPEN_ID)['public_id']

        assert rest_api.patch(f'{RACKS_URL}/{seed.RACK_ID}/mounts/{mount_id}',
                              json={'area': FRONT, 'start_slot': 1, 'height': 1}, **_editor()).status_code == 202
        assert rest_api.delete(f'{RACKS_URL}/{seed.RACK_ID}/mounts/{mount_id}', **_editor()).status_code == 202


class TestReadingARack:
    """Every rack read asks READ on the Rack."""

    @pytest.mark.parametrize('path', ['overview', 'mounts/', 'height_conflicts?height=10', 'assignable_objects/'])
    def test_a_hidden_rack_is_403(self, rest_api, path: str) -> None:
        """Nothing of it - not its name, its height or its members"""
        response = rest_api.get(f'{RACKS_URL}/{seed.HIDDEN_RACK_ID}/{path}', **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize('path', ['overview', 'mounts/', 'height_conflicts?height=10', 'assignable_objects/'])
    def test_a_read_only_rack_is_readable(self, rest_api, path: str) -> None:
        """READ is enough to read"""
        assert rest_api.get(f'{RACKS_URL}/{seed.READ_ONLY_RACK_ID}/{path}', **_editor()).status_code == 200


class TestTheDryRun:
    """POST /racks/<id>/mounts/validate reports what the write would refuse."""

    def _validate(self, rest_api, rack_id: int, object_id: int) -> dict[str, Any]:
        response = rest_api.post(f'{RACKS_URL}/{rack_id}/mounts/validate', json={'object_id': object_id},
                                 **_editor())
        assert response.status_code == HTTPStatus.OK

        return response.get_json()

    def test_a_hidden_member(self, rest_api) -> None:
        """Invalid, with the write's reason"""
        answer = self._validate(rest_api, seed.RACK_ID, seed.HIDDEN_ID)

        assert answer['valid'] is False
        assert answer['errors'][0]['message'] == LINKED_OBJECT_DENIED_MSG.format(object_id=seed.HIDDEN_ID)

    def test_a_rack_the_editor_may_read_but_not_change(self, rest_api) -> None:
        """Readable, so it answers - invalid, naming the Rack"""
        answer = self._validate(rest_api, seed.READ_ONLY_RACK_ID, seed.OPEN_ID)

        assert answer['valid'] is False
        assert answer['errors'][0]['message'] == \
            RackAccessError.RACK_UPDATE_DENIED.format(object_id=seed.READ_ONLY_RACK_ID)

    def test_what_the_acl_grants_is_valid(self, rest_api) -> None:
        """An open member into an open rack"""
        assert self._validate(rest_api, seed.RACK_ID, seed.OPEN_ID)['valid'] is True

    def test_a_hidden_rack_is_403(self, rest_api) -> None:
        """Not even the dry run reads it"""
        response = rest_api.post(f'{RACKS_URL}/{seed.HIDDEN_RACK_ID}/mounts/validate',
                                 json={'object_id': seed.OPEN_ID}, **_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestTheMountOfAnObject:
    """GET /racks/mounts/object/<id> - a fact about the object and the Rack it names."""

    def test_a_hidden_object_is_403(self, rest_api) -> None:
        """Even when it is in no rack"""
        assert rest_api.get(f'{RACKS_URL}/mounts/object/{seed.HIDDEN_ID}', **_editor()).status_code == 403

    def test_an_open_object_in_a_hidden_rack_is_403(self, rest_api) -> None:
        """The answer would name the Rack"""
        assert _mount(rest_api, seed.HIDDEN_RACK_ID, seed.OPEN_ID).status_code == HTTPStatus.CREATED

        assert rest_api.get(f'{RACKS_URL}/mounts/object/{seed.OPEN_ID}', **_editor()).status_code == 403

    def test_an_open_object_in_an_open_rack(self, rest_api) -> None:
        """Its mount"""
        assert _mount(rest_api, seed.RACK_ID, seed.OPEN_ID).status_code == HTTPStatus.CREATED

        response = rest_api.get(f'{RACKS_URL}/mounts/object/{seed.OPEN_ID}', **_editor())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['rack_id'] == seed.RACK_ID
