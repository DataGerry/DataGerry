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
Integration tests for how a CmdbLocation node is named, against a real MongoDB and the real renderer

The name is the object's summary line, rendered without reference expansion - the same line a
reference-resolving render answers, at a fraction of the reads. An object the render skips falls back to
``ObjectID: <id>``. The object is read through the caller's READ ACL. A move hands the object it validated
on to the mirror, placed at its new parent, so a summary naming the location field shows the new placement
without the object being read again
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LocationsManager, ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.framework.rendering.render_list import RenderList
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import OBJECT_ID_NAME_TEMPLATE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    derive_location_name,
    move_object_location,
    read_linked_object,
    sync_object_location,
)
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_FORBIDDEN: int = 403
HTTP_NOT_FOUND: int = 404
EXPLICIT_NAME: str = 'an-explicit-node-name'


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the location-write fixture and pushes the app context ManagerProvider resolves through."""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)

    with rest_api.application.test_request_context():
        yield

    seed.purge(database_manager, database_name)


def _managers(user: CmdbUser) -> tuple[ObjectsManager, LocationsManager]:
    """The objects and locations managers for `user`."""
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, user)

    return objects_manager, locations_manager


@pytest.fixture(name='object_reads')
def fixture_object_reads(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Records the id of every single object read."""
    reads: list[Any] = []
    original = ObjectsManager.get_object

    def _spy(manager: ObjectsManager, public_id: Any, *args: Any, **kwargs: Any) -> Any:
        reads.append(public_id)
        return original(manager, public_id, *args, **kwargs)

    monkeypatch.setattr(ObjectsManager, 'get_object', _spy)

    return reads


class TestTheDerivedName:
    """derive_location_name against the real renderer."""

    def test_it_is_the_summary_line(self, full_access_user, database_manager, database_name) -> None:
        """The object's summary line, as the renderer builds it"""
        visible = seed.load(database_manager, database_name, seed.VISIBLE_ID)

        assert derive_location_name(visible, full_access_user) == seed.VISIBLE_VALUE

    def test_it_matches_a_reference_resolving_render(self, full_access_user, database_manager, database_name) -> None:
        """A summary naming a reference field reads the same with and without reference expansion"""
        summary_ref = seed.load(database_manager, database_name, seed.SUMMARY_REF_ID)
        expanded: dict[str, Any] = RenderList([summary_ref], full_access_user, True).render_result_list(raw=True)[0]

        assert derive_location_name(summary_ref, full_access_user) == expanded['summary_line']

    def test_it_loads_nothing_the_object_references(self, full_access_user, database_manager, database_name,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
        """No reference expansion: the referenced object is never loaded"""
        lookups: list[Any] = []
        original = ObjectsManager.get_objects_lookup

        def _spy(manager: ObjectsManager, public_ids: list[int], *args: Any) -> Any:
            lookups.append(public_ids)
            return original(manager, public_ids, *args)

        monkeypatch.setattr(ObjectsManager, 'get_objects_lookup', _spy)

        derive_location_name(seed.load(database_manager, database_name, seed.SUMMARY_REF_ID), full_access_user)

        assert not lookups

    def test_an_object_without_a_type_takes_the_fallback(self, full_access_user, database_manager,
                                                         database_name) -> None:
        """The render skips an object whose type is gone; the name is ObjectID: <id>, not an error"""
        orphan = seed.load(database_manager, database_name, seed.ORPHAN_ID)

        assert derive_location_name(orphan, full_access_user) \
            == OBJECT_ID_NAME_TEMPLATE.format(object_id=seed.ORPHAN_ID)


class TestTheObjectRead:
    """read_linked_object through the real ACL."""

    def test_a_reader_gets_the_object(self, full_access_user) -> None:
        """The admin group may read the hidden type"""
        objects_manager, _ = _managers(full_access_user)

        assert read_linked_object(seed.HIDDEN_ID, objects_manager, full_access_user).public_id == seed.HIDDEN_ID

    def test_the_editor_is_refused(self) -> None:
        """The location editor's group may not read the hidden type"""
        editor: CmdbUser = seed.location_editor()
        objects_manager, _ = _managers(editor)

        with pytest.raises(HTTPException) as excinfo:
            read_linked_object(seed.HIDDEN_ID, objects_manager, editor)

        assert excinfo.value.code == HTTP_FORBIDDEN

    def test_without_a_user_nothing_is_refused(self) -> None:
        """The object write path's read: its own write authorized the object"""
        objects_manager, _ = _managers(seed.location_editor())

        assert read_linked_object(seed.HIDDEN_ID, objects_manager, None).public_id == seed.HIDDEN_ID

    def test_a_missing_object_is_a_404(self, full_access_user) -> None:
        """No object with the id"""
        objects_manager, _ = _managers(full_access_user)

        with pytest.raises(HTTPException) as excinfo:
            read_linked_object(seed.MISSING_OBJECT_ID, objects_manager, full_access_user)

        assert excinfo.value.code == HTTP_NOT_FOUND


class TestAMove:
    """move_object_location hands the validated object on to the mirror."""

    def test_the_object_is_read_once(self, full_access_user, database_manager, database_name,
                                     object_reads: list[Any]) -> None:
        """The validation's read serves the name too"""
        objects_manager, locations_manager = _managers(full_access_user)

        move_object_location(seed.VISIBLE_ID, seed.PARENT_NODE_ID, full_access_user, objects_manager,
                             locations_manager)

        assert object_reads.count(seed.VISIBLE_ID) == 1
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)['name'] == seed.VISIBLE_VALUE

    def test_the_name_shows_the_new_placement(self, full_access_user, database_manager, database_name) -> None:
        """A summary naming the location field is derived from the object as placed, not as read"""
        objects_manager, locations_manager = _managers(full_access_user)

        move_object_location(seed.SUMMARY_REF_ID, seed.PARENT_NODE_ID, full_access_user, objects_manager,
                             locations_manager)

        stored = seed.load(database_manager, database_name, seed.SUMMARY_REF_ID)
        assert seed.stored_node(database_manager, database_name, seed.SUMMARY_REF_ID)['name'] \
            == derive_location_name(stored, full_access_user)
        name: str = seed.stored_node(database_manager, database_name, seed.SUMMARY_REF_ID)['name']
        assert str(seed.PARENT_NODE_ID) in name


class TestTheObjectWriteMirror:
    """sync_object_location as the object write path calls it."""

    def test_an_explicit_name_reads_no_object(self, full_access_user, database_manager, database_name,
                                              object_reads: list[Any]) -> None:
        """The name is given; nothing is derived"""
        objects_manager, locations_manager = _managers(full_access_user)
        visible = seed.load(database_manager, database_name, seed.VISIBLE_ID)
        visible_type = objects_manager.get_object_type(visible.get_type_id())

        sync_object_location(seed.VISIBLE_ID, seed.PARENT_NODE_ID, EXPLICIT_NAME, visible_type, full_access_user,
                             objects_manager, locations_manager)

        assert not object_reads
        assert seed.stored_node(database_manager, database_name, seed.VISIBLE_ID)['name'] == EXPLICIT_NAME

    def test_a_derived_name_reads_the_stored_object(self, database_manager, database_name,
                                                    object_reads: list[Any]) -> None:
        """Unscoped: the editor's own write would have authorized it, so the hidden type does not refuse it"""
        editor: CmdbUser = seed.location_editor()
        objects_manager, locations_manager = _managers(editor)
        hidden_type = objects_manager.get_object_type(seed.HIDDEN_TYPE_ID)

        sync_object_location(seed.HIDDEN_ID, seed.PARENT_NODE_ID, None, hidden_type, editor,
                             objects_manager, locations_manager)

        assert object_reads == [seed.HIDDEN_ID]
        assert seed.stored_node(database_manager, database_name, seed.HIDDEN_ID)['name'] == seed.HIDDEN_VALUE
