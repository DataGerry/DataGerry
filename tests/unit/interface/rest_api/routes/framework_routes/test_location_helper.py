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
Unit tests for the CmdbLocation route helpers

``resolve_location_name`` is exercised with ObjectsManager / RenderList / CmdbObject patched at
the helper module path - no Mongo and no rendering pipeline runs, only the name-derivation
branching. ``build_location_forest`` is exercised against the real ``LocationNode`` (pure logic)
to pin the flat-list -> nested-forest assembly the ``/locations/tree`` route delegates to.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    resolve_location_name,
    build_location_forest,
    parse_required_int,
    extract_object_location_parent,
    validate_object_location_change,
    sync_object_location,
    build_location_level,
)
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper'

OBJECT_ID: int = 4242
ROOT_PUBLIC_ID: int = 1

LOCATION_FIELD_TYPE: str = FieldType.LOCATION.value
TEXT_FIELD_TYPE: str = FieldType.TEXT.value
OWN_LOCATION_ID: int = 50
DESCENDANT_LOCATION_ID: int = 51
NEW_PARENT_ID: int = 60
RESOLVED_NAME: str = 'Resolved Location Name'

EXPLICIT_NAME: str = 'Server Room A'
RENDERED_SUMMARY: str = 'Rendered Summary Line'
FALLBACK_NAME: str = f'ObjectID: {OBJECT_ID}'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404

PARENT_ID: int = 10
CHILD_ID: int = 11
GRANDCHILD_ID: int = 12
SECOND_ROOT_ID: int = 20


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app so ``abort`` resolves inside a request context."""
    return Flask(__name__)


def _location(public_id: int, parent: int) -> dict[str, Any]:
    """Builds a minimal CmdbLocation dict accepted by ``LocationNode`` / ``build_location_forest``."""
    return {
        'public_id': public_id,
        'name': f'loc-{public_id}',
        'parent': parent,
        'type_icon': 'fas fa-cube',
        'object_id': public_id + 100,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  parse_required_int                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestParseRequiredInt:
    """``parse_required_int`` coerces a required body field to int or aborts 400."""

    def test_returns_int_for_valid_value(self, flask_app: Flask) -> None:
        """A present, numeric value is coerced to int."""
        with flask_app.test_request_context():
            assert parse_required_int({'object_id': '42'}, 'object_id') == 42

    def test_missing_key_aborts_400(self, flask_app: Flask) -> None:
        """A missing key aborts 400 instead of raising a KeyError."""
        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as excinfo:
                parse_required_int({}, 'object_id')

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_non_integer_value_aborts_400(self, flask_app: Flask) -> None:
        """A non-integer value aborts 400 instead of raising a ValueError."""
        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as excinfo:
                parse_required_int({'object_id': 'not-an-int'}, 'object_id')

        assert excinfo.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                resolve_location_name                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveLocationName:
    """``resolve_location_name`` returns an explicit name or derives one from the linked object."""

    def test_explicit_name_is_returned_without_touching_the_object(self, flask_app: Flask) -> None:
        """A non-empty name short-circuits: the ObjectsManager is never queried."""
        objects_manager = MagicMock(name='objects_manager')

        with flask_app.test_request_context():
            result = resolve_location_name(EXPLICIT_NAME, OBJECT_ID, objects_manager, MagicMock())

        assert result == EXPLICIT_NAME
        objects_manager.get_object.assert_not_called()

    def test_empty_name_derives_from_rendered_summary_line(self, flask_app: Flask) -> None:
        """An empty name is replaced by the linked object's rendered ``summary_line``."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {'public_id': OBJECT_ID}

        with patch(f'{HELPER_PATH}.CmdbObject.from_data'), \
             patch(f'{HELPER_PATH}.RenderList') as render_list_ctor, \
             flask_app.test_request_context():
            render_list_ctor.return_value.render_result_list.return_value = [{'summary_line': RENDERED_SUMMARY}]
            result = resolve_location_name('', OBJECT_ID, objects_manager, MagicMock())

        assert result == RENDERED_SUMMARY

    def test_empty_summary_line_falls_back_to_object_id_template(self, flask_app: Flask) -> None:
        """When the summary line is also empty the ``ObjectID: <id>`` template is used."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = {'public_id': OBJECT_ID}

        with patch(f'{HELPER_PATH}.CmdbObject.from_data'), \
             patch(f'{HELPER_PATH}.RenderList') as render_list_ctor, \
             flask_app.test_request_context():
            render_list_ctor.return_value.render_result_list.return_value = [{'summary_line': ''}]
            result = resolve_location_name(None, OBJECT_ID, objects_manager, MagicMock())

        assert result == FALLBACK_NAME

    def test_missing_object_aborts_404(self, flask_app: Flask) -> None:
        """A name that must be derived from a non-existent object aborts 404."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = None

        with flask_app.test_request_context():
            with pytest.raises(HTTPException) as excinfo:
                resolve_location_name('', OBJECT_ID, objects_manager, MagicMock())

        assert excinfo.value.code == HTTP_NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_location_forest                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildLocationForest:
    """``build_location_forest`` assembles a flat dict list into nested root trees."""

    def test_empty_input_yields_empty_forest(self) -> None:
        """No locations produce no roots."""
        assert build_location_forest([]) == []

    def test_only_root_parented_locations_become_roots(self) -> None:
        """Exactly the locations whose ``parent`` is the root id become forest roots."""
        locations = [
            _location(PARENT_ID, ROOT_PUBLIC_ID),
            _location(SECOND_ROOT_ID, ROOT_PUBLIC_ID),
            _location(CHILD_ID, PARENT_ID),  # not a root - nested below PARENT_ID
        ]

        forest = build_location_forest(locations)

        assert sorted(root['public_id'] for root in forest) == [PARENT_ID, SECOND_ROOT_ID]

    def test_descendants_are_nested_under_their_root(self) -> None:
        """A child and grandchild are nested beneath their root rather than appearing at top level."""
        locations = [
            _location(PARENT_ID, ROOT_PUBLIC_ID),
            _location(CHILD_ID, PARENT_ID),
            _location(GRANDCHILD_ID, CHILD_ID),
        ]

        forest = build_location_forest(locations)

        assert [root['public_id'] for root in forest] == [PARENT_ID]
        assert [child['public_id'] for child in forest[0]['children']] == [CHILD_ID]
        assert [gc['public_id'] for gc in forest[0]['children'][0]['children']] == [GRANDCHILD_ID]

    def test_orphan_without_root_parent_is_dropped(self) -> None:
        """A location whose parent is neither the root nor present is not surfaced as a root."""
        locations = [_location(CHILD_ID, PARENT_ID)]  # PARENT_ID is absent and is not the root id

        assert build_location_forest(locations) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                          extract_object_location_parent                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestExtractObjectLocationParent:
    """extract_object_location_parent reads the parent id from an object's location-typed field."""

    def test_no_location_field_returns_false(self) -> None:
        """A field list without a location field flags has_location_field=False and no parent."""
        fields = [{'name': 'text', 'type': TEXT_FIELD_TYPE, 'value': 'x'}]

        assert extract_object_location_parent(fields) == (False, None)

    def test_positive_value_returns_parent(self) -> None:
        """A positive location value is returned as the parent id."""
        fields = [{'name': 'dg_location', 'type': LOCATION_FIELD_TYPE, 'value': NEW_PARENT_ID}]

        assert extract_object_location_parent(fields) == (True, NEW_PARENT_ID)

    def test_null_value_means_remove(self) -> None:
        """A null location value flags the field present but yields no parent (removal)."""
        fields = [{'name': 'dg_location', 'type': LOCATION_FIELD_TYPE, 'value': None}]

        assert extract_object_location_parent(fields) == (True, None)

    def test_non_positive_value_means_remove(self) -> None:
        """A zero/negative location value flags the field present but yields no parent (removal)."""
        fields = [{'name': 'dg_location', 'type': LOCATION_FIELD_TYPE, 'value': 0}]

        assert extract_object_location_parent(fields) == (True, None)

    def test_non_integer_value_means_remove(self) -> None:
        """A non-integer location value cannot be a parent id, so it is treated as removal."""
        fields = [{'name': 'dg_location', 'type': LOCATION_FIELD_TYPE, 'value': 'not-a-number'}]

        assert extract_object_location_parent(fields) == (True, None)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        validate_object_location_change                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateObjectLocationChange:
    """validate_object_location_change rejects a missing parent, a cycle or an orphaning removal."""

    @staticmethod
    def _manager(existing: dict[str, Any] | None) -> MagicMock:
        """A MagicMock LocationsManager whose get_location_for_object returns the given existing doc."""
        manager = MagicMock(name='locations_manager')
        manager.get_location_for_object.return_value = existing
        return manager

    def test_unchanged_parent_is_a_noop(self, flask_app: Flask) -> None:
        """When the parent equals the current one nothing is validated and no lookups are made."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID})

        with flask_app.test_request_context():
            validate_object_location_change(OBJECT_ID, NEW_PARENT_ID, manager)

        manager.get_location.assert_not_called()
        manager.get_all_descendant_locations.assert_not_called()

    def test_missing_parent_aborts_400(self, flask_app: Flask) -> None:
        """Setting a non-existent, non-root parent is rejected with 400."""
        manager = self._manager(None)
        manager.get_location.return_value = None

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_change(OBJECT_ID, NEW_PARENT_ID, manager)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_root_parent_needs_no_existence_check(self, flask_app: Flask) -> None:
        """The root id is always a valid parent, so its existence is not looked up."""
        manager = self._manager(None)

        with flask_app.test_request_context():
            validate_object_location_change(OBJECT_ID, ROOT_PUBLIC_ID, manager)

        manager.get_location.assert_not_called()

    def test_parent_in_own_subtree_aborts_400(self, flask_app: Flask) -> None:
        """A parent that is a descendant of the object's own location would create a cycle -> 400."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})
        manager.get_location.return_value = {'public_id': DESCENDANT_LOCATION_ID}
        manager.get_all_descendant_locations.return_value = [{'public_id': DESCENDANT_LOCATION_ID}]

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_change(OBJECT_ID, DESCENDANT_LOCATION_ID, manager)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_parent_is_own_location_aborts_400(self, flask_app: Flask) -> None:
        """An object cannot be parented under its own location node (a trivial cycle) -> 400."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})
        manager.get_location.return_value = {'public_id': OWN_LOCATION_ID}
        manager.get_all_descendant_locations.return_value = []

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_change(OBJECT_ID, OWN_LOCATION_ID, manager)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_valid_new_parent_passes(self, flask_app: Flask) -> None:
        """An existing parent outside the object's own subtree is accepted."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})
        manager.get_location.return_value = {'public_id': NEW_PARENT_ID}
        manager.get_all_descendant_locations.return_value = [{'public_id': DESCENDANT_LOCATION_ID}]

        with flask_app.test_request_context():
            validate_object_location_change(OBJECT_ID, NEW_PARENT_ID, manager)

    def test_remove_with_children_aborts_400(self, flask_app: Flask) -> None:
        """Removing the placement while the object's location still has children is rejected -> 400."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID})
        manager.location_has_children.return_value = True

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_change(OBJECT_ID, None, manager)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_remove_without_children_passes(self, flask_app: Flask) -> None:
        """Removing the placement is allowed when the object's location has no children."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID})
        manager.location_has_children.return_value = False

        with flask_app.test_request_context():
            validate_object_location_change(OBJECT_ID, None, manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              sync_object_location                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSyncObjectLocation:
    """sync_object_location creates/updates/deletes the CmdbLocation and swallows write failures."""

    @staticmethod
    def _object_type() -> MagicMock:
        """A MagicMock CmdbType supplying the label/icon/selectable used for a new location node."""
        object_type = MagicMock(name='object_type')
        object_type.public_id = 20
        object_type.label = 'Test Type'
        object_type.get_icon.return_value = 'fa-cube'
        object_type.selectable_as_parent = True
        return object_type

    @staticmethod
    def _manager(existing: dict[str, Any] | None) -> MagicMock:
        """A MagicMock LocationsManager whose get_location_for_object returns the given existing doc."""
        manager = MagicMock(name='locations_manager')
        manager.get_location_for_object.return_value = existing
        return manager

    def _sync(self, manager: MagicMock, parent: int | None, location_name: str | None) -> None:
        """Runs sync_object_location with resolve_location_name patched to a fixed value."""
        with patch(f'{HELPER_PATH}.resolve_location_name', return_value=RESOLVED_NAME):
            sync_object_location(
                OBJECT_ID, parent, location_name, self._object_type(),
                MagicMock(name='request_user'), MagicMock(name='objects_manager'), manager,
            )

    def test_creates_location_when_none_exists(self) -> None:
        """A parent with no existing location inserts a new CmdbLocation carrying that parent + name."""
        manager = self._manager(None)

        self._sync(manager, NEW_PARENT_ID, None)

        manager.insert_location.assert_called_once()
        inserted = manager.insert_location.call_args.args[0]
        assert inserted['parent'] == NEW_PARENT_ID
        assert inserted['object_id'] == OBJECT_ID
        assert inserted['name'] == RESOLVED_NAME
        manager.update_location.assert_not_called()
        manager.delete_location.assert_not_called()

    def test_updates_location_when_parent_changes(self) -> None:
        """A changed parent on an existing location updates it in place."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})

        self._sync(manager, NEW_PARENT_ID, None)

        manager.update_location.assert_called_once_with(OBJECT_ID, {'parent': NEW_PARENT_ID, 'name': RESOLVED_NAME})
        manager.insert_location.assert_not_called()

    def test_deletes_location_when_parent_removed(self) -> None:
        """A removed parent deletes the existing CmdbLocation."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})

        self._sync(manager, None, None)

        manager.delete_location.assert_called_once_with(OWN_LOCATION_ID)
        manager.insert_location.assert_not_called()
        manager.update_location.assert_not_called()

    def test_unchanged_parent_without_name_is_a_noop(self) -> None:
        """An unchanged parent and no explicit name leaves the location untouched."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID})

        self._sync(manager, NEW_PARENT_ID, None)

        manager.insert_location.assert_not_called()
        manager.update_location.assert_not_called()
        manager.delete_location.assert_not_called()

    def test_name_only_change_updates_location(self) -> None:
        """An explicit name updates the location even when the parent is unchanged."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID})

        self._sync(manager, NEW_PARENT_ID, 'Renamed Node')

        manager.update_location.assert_called_once_with(OBJECT_ID, {'parent': NEW_PARENT_ID, 'name': RESOLVED_NAME})

    def test_write_failure_is_swallowed(self) -> None:
        """A failing location write is logged and swallowed so the object save is never lost."""
        manager = self._manager(None)
        manager.insert_location.side_effect = RuntimeError('boom')

        # Must not raise
        self._sync(manager, NEW_PARENT_ID, None)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_location_level                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildLocationLevel:
    """build_location_level flags each node of a tree level with a has_children hint."""

    def test_flags_has_children_per_node(self) -> None:
        """Only the nodes reported by get_parents_with_children are flagged has_children=True."""
        manager = MagicMock(name='locations_manager')
        manager.get_parents_with_children.return_value = {OWN_LOCATION_ID}

        level = build_location_level(
            [{'public_id': OWN_LOCATION_ID, 'name': 'a'}, {'public_id': NEW_PARENT_ID, 'name': 'b'}],
            manager,
        )

        assert level[0]['has_children'] is True
        assert level[1]['has_children'] is False
        manager.get_parents_with_children.assert_called_once_with([OWN_LOCATION_ID, NEW_PARENT_ID])

    def test_empty_level_returns_empty_list(self) -> None:
        """An empty level yields an empty result and no node flags."""
        manager = MagicMock(name='locations_manager')
        manager.get_parents_with_children.return_value = set()

        assert build_location_level([], manager) == []

    def test_preserves_original_node_fields(self) -> None:
        """The original location fields are carried through unchanged alongside has_children."""
        manager = MagicMock(name='locations_manager')
        manager.get_parents_with_children.return_value = set()

        level = build_location_level([{'public_id': NEW_PARENT_ID, 'name': 'node', 'parent': ROOT_PUBLIC_ID}], manager)

        assert level[0]['name'] == 'node'
        assert level[0]['parent'] == ROOT_PUBLIC_ID
        assert level[0]['has_children'] is False

    def test_drops_unused_type_metadata(self) -> None:
        """type_id, type_label and type_selectable are stripped; the other fields are kept."""
        manager = MagicMock(name='locations_manager')
        manager.get_parents_with_children.return_value = set()

        node = build_location_level([{
            'public_id': NEW_PARENT_ID, 'name': 'node', 'parent': ROOT_PUBLIC_ID, 'object_id': 99,
            'type_icon': 'fa-cube', 'type_id': 6, 'type_label': 'Building', 'type_selectable': True,
        }], manager)[0]

        assert 'type_id' not in node
        assert 'type_label' not in node
        assert 'type_selectable' not in node
        assert node['type_icon'] == 'fa-cube'
        assert node['object_id'] == 99
