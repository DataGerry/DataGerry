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
Integration tests for the placement ACL against a real MongoDB and the real type ACLs

A placement write needs READ and UPDATE on its object's type and an active type. The batch move decides that
once per type - one type read and one decision whatever the number of objects - and before anything else
about the placement
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations import location_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_DENIED_MSG,
    LINKED_OBJECT_UPDATE_DENIED_MSG,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    read_placeable_object,
    validate_object_location_moves,
)
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_FORBIDDEN: int = 403


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the location-write fixture and pushes the request context ManagerProvider resolves through."""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)

    with rest_api.application.test_request_context():
        yield

    seed.purge(database_manager, database_name)


def _managers(user: CmdbUser) -> tuple[ObjectsManager, LocationsManager]:
    """The objects and locations managers for `user`."""
    return (ManagerProvider.get_manager(ManagerType.OBJECTS, user),
            ManagerProvider.get_manager(ManagerType.LOCATIONS, user))


class TestTheSingleObject:
    """read_placeable_object against the stored type ACLs."""

    def test_a_changeable_object_is_answered_with_its_type(self) -> None:
        """VISIBLE: no ACL, active"""
        objects_manager, _ = _managers(seed.location_editor())

        target = read_placeable_object(seed.VISIBLE_ID, objects_manager, seed.location_editor())

        assert target.cmdb_object.public_id == seed.VISIBLE_ID
        assert target.object_type.public_id == seed.VISIBLE_TYPE_ID

    @pytest.mark.parametrize('object_id, message', [
        (seed.HIDDEN_ID, LINKED_OBJECT_DENIED_MSG),
        (seed.READ_ONLY_ID, LINKED_OBJECT_UPDATE_DENIED_MSG),
    ], ids=['not-readable', 'read-only'])
    def test_the_stored_acl_decides(self, object_id: int, message: str) -> None:
        """The editor's group: no READ on HIDDEN, READ without UPDATE on READ_ONLY"""
        objects_manager, _ = _managers(seed.location_editor())

        with pytest.raises(HTTPException) as raised:
            read_placeable_object(object_id, objects_manager, seed.location_editor())

        assert raised.value.code == HTTP_FORBIDDEN
        assert raised.value.description == message.format(object_id=object_id)

    def test_the_admin_may_change_the_read_only_type(self, full_access_user: CmdbUser) -> None:
        """READ_ONLY is read-only for the editor's group, not for everyone"""
        objects_manager, _ = _managers(full_access_user)

        assert read_placeable_object(seed.READ_ONLY_ID, objects_manager, full_access_user).cmdb_object.public_id \
            == seed.READ_ONLY_ID

    def test_a_deactivated_type_is_refused_to_the_admin(self, full_access_user: CmdbUser) -> None:
        """No ACL lets an inactive type's objects be changed"""
        objects_manager, _ = _managers(full_access_user)

        with pytest.raises(HTTPException) as raised:
            read_placeable_object(seed.DEACTIVATED_ID, objects_manager, full_access_user)

        assert raised.value.code == HTTP_FORBIDDEN
        assert 'deactivated' in raised.value.description


class TestTheBatch:
    """validate_object_location_moves against the stored type ACLs."""

    @pytest.fixture(name='decisions')
    def fixture_decisions(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        """Records the object each ACL decision was made for"""
        decided: list[int] = []
        original = location_helper.authorize_object_placement

        def _spy(cmdb_object: Any, *args: Any) -> None:
            decided.append(cmdb_object.public_id)
            original(cmdb_object, *args)

        monkeypatch.setattr(location_helper, 'authorize_object_placement', _spy)

        return decided

    def test_one_decision_per_type(self, decisions: list[int]) -> None:
        """VISIBLE twice is still one decision; SUMMARY_REF is its own type"""
        objects_manager, locations_manager = _managers(seed.location_editor())

        targets = validate_object_location_moves([seed.VISIBLE_ID, seed.SUMMARY_REF_ID, seed.VISIBLE_ID],
                                                 seed.PARENT_NODE_ID, objects_manager, locations_manager,
                                                 seed.location_editor())

        assert decisions == [seed.VISIBLE_ID, seed.SUMMARY_REF_ID]
        assert set(targets) == {seed.VISIBLE_ID, seed.SUMMARY_REF_ID}

    def test_one_denied_object_refuses_the_batch(self, decisions: list[int]) -> None:
        """The decision for READ_ONLY ends it - nothing is answered for VISIBLE"""
        objects_manager, locations_manager = _managers(seed.location_editor())

        with pytest.raises(HTTPException) as raised:
            validate_object_location_moves([seed.VISIBLE_ID, seed.READ_ONLY_ID], seed.PARENT_NODE_ID,
                                           objects_manager, locations_manager, seed.location_editor())

        assert raised.value.code == HTTP_FORBIDDEN
        assert decisions == [seed.VISIBLE_ID, seed.READ_ONLY_ID]
