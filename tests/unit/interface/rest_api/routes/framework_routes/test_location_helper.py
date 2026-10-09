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

The name helpers (``read_linked_object``, ``derive_location_name``, ``is_explicit_location_name``) run with
ObjectsManager / RenderList patched at the helper module path - no Mongo and no rendering pipeline,
only the read, ACL and derivation branching. ``build_location_forest`` is exercised against the real
``LocationNode`` (pure logic) to pin the flat-list -> nested-forest assembly the tree search and tree
path routes delegate to.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    build_location_forest,
    extract_object_location_parent,
    validate_object_location_change,
    sync_object_location,
    build_location_level,
    delete_location_with_reparenting,
    location_fields_point_at,
    normalize_parent_id,
    validate_object_location_move,
    validate_object_location_moves,
    validate_shared_move_parent,
    move_object_location,
    derive_location_name,
    is_explicit_location_name,
    read_linked_object,
    read_placeable_object,
    resolve_placed_object_type,
    authorize_object_placement,
    abort_if_not_placeable,
    with_location_parent,
    PlacementTarget,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_DENIED_MSG,
    LINKED_OBJECT_NOT_FOUND_MSG,
    LINKED_OBJECT_UPDATE_DENIED_MSG,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.models.object_model.object_constants import ObjectWriteVerb
from cmdb.models.object_model import CmdbObject
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.errors.security import AccessDeniedError
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.location_model.location_constants import RootLocationDefault
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper'
# The caller of a validation whose ACL decision is patched out
REQUEST_USER: MagicMock = MagicMock(name='request_user')

OBJECT_ID: int = 4242
ROOT_PUBLIC_ID: int = 1

LOCATION_FIELD_TYPE: str = FieldType.LOCATION.value
TEXT_FIELD_TYPE: str = FieldType.TEXT.value
OWN_LOCATION_ID: int = 50
DESCENDANT_LOCATION_ID: int = 51
NEW_PARENT_ID: int = 60
RESOLVED_NAME: str = 'Resolved Location Name'
NAME_FIELD: str = 'name'
LOCATION_FIELD: str = 'placement'
NAME_VALUE: str = 'srv-01'

EXPLICIT_NAME: str = 'Server Room A'
RENDERED_SUMMARY: str = 'Rendered Summary Line'
FALLBACK_NAME: str = f'ObjectID: {OBJECT_ID}'

HTTP_BAD_REQUEST: int = 400
HTTP_FORBIDDEN: int = 403
HTTP_NOT_FOUND: int = 404
HTTP_INTERNAL_SERVER_ERROR: int = 500
TYPE_ID: int = 77

PARENT_ID: int = 10
CHILD_ID: int = 11
GRANDCHILD_ID: int = 12
SECOND_ROOT_ID: int = 20


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app so ``abort`` resolves inside a request context."""
    return Flask(__name__)


def _real_object() -> CmdbObject:
    """A CmdbObject with a text field and a location field placed under OWN_LOCATION_ID."""
    return CmdbObject.from_data({
        'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'fields': [
            {'type': TEXT_FIELD_TYPE, 'name': NAME_FIELD, 'value': NAME_VALUE},
            {'type': LOCATION_FIELD_TYPE, 'name': LOCATION_FIELD, 'value': OWN_LOCATION_ID},
        ],
    })


def _location(public_id: int, parent: int) -> dict[str, Any]:
    """Builds a minimal CmdbLocation dict accepted by ``LocationNode`` / ``build_location_forest``."""
    return {
        'public_id': public_id,
        'name': f'loc-{public_id}',
        'parent': parent,
        'type_icon': 'fas fa-cube',
        'object_id': public_id + 100,
    }


class TestIsExplicitLocationName:
    """``is_explicit_location_name`` separates a given name from one left to be derived."""

    @pytest.mark.parametrize('raw_name, expected', [(EXPLICIT_NAME, True), (' ', True), ('', False), (None, False)],
                             ids=['name', 'blank-is-a-name', 'empty', 'none'])
    def test_answers(self, raw_name: str | None, expected: bool) -> None:
        """Only the empty string and None leave the name to be derived."""
        assert is_explicit_location_name(raw_name) is expected


class TestDeriveLocationName:
    """``derive_location_name`` renders the object's summary line, without reference expansion."""

    @staticmethod
    def _derive(rendered: list[dict[str, Any]]) -> tuple[str, MagicMock]:
        """Derives with RenderList patched to answer `rendered`; answers the name and the constructor mock."""
        with patch(f'{HELPER_PATH}.RenderList') as render_list_ctor:
            render_list_ctor.return_value.render_result_list.return_value = rendered
            return derive_location_name(_real_object(), REQUEST_USER), render_list_ctor

    def test_the_summary_line_is_the_name(self) -> None:
        """The rendered summary line is used as it is."""
        assert self._derive([{'summary_line': RENDERED_SUMMARY}])[0] == RENDERED_SUMMARY

    def test_the_render_resolves_no_references(self) -> None:
        """The summary line reads the object's own values, so nothing it references is loaded."""
        render_list_ctor = self._derive([{'summary_line': RENDERED_SUMMARY}])[1]

        assert len(render_list_ctor.call_args.args) == 2
        assert not render_list_ctor.call_args.kwargs

    @pytest.mark.parametrize('summary_line', ['', None], ids=['empty', 'none'])
    def test_an_empty_summary_line_falls_back_to_the_object_id(self, summary_line: str | None) -> None:
        """When the summary line is empty the ``ObjectID: <id>`` template is used."""
        assert self._derive([{'summary_line': summary_line}])[0] == FALLBACK_NAME

    def test_an_object_the_render_skips_falls_back_to_the_object_id(self) -> None:
        """An object whose type cannot be read renders nothing - the fallback name, not an IndexError."""
        assert self._derive([])[0] == FALLBACK_NAME


class TestReadLinkedObject:
    """``read_linked_object`` reads the object a node is written for through the caller's READ ACL."""

    def test_the_read_asks_for_read(self) -> None:
        """The caller and READ are handed to the manager; the object comes back as a CmdbObject."""
        objects_manager, request_user = MagicMock(name='objects_manager'), MagicMock(name='request_user')

        assert read_linked_object(OBJECT_ID, objects_manager, request_user) is objects_manager.get_object.return_value
        objects_manager.get_object.assert_called_once_with(
            OBJECT_ID, request_user, AccessControlPermission.READ, as_dict=False,
        )

    def test_a_denial_is_a_403(self, flask_app: Flask) -> None:
        """An object the caller may not read is a 403 naming it - not the 500 a raw AccessDeniedError becomes."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.side_effect = AccessDeniedError('denied')

        with flask_app.test_request_context(), pytest.raises(HTTPException) as excinfo:
            read_linked_object(OBJECT_ID, objects_manager, MagicMock())

        assert excinfo.value.code == HTTP_FORBIDDEN
        assert excinfo.value.description == LINKED_OBJECT_DENIED_MSG.format(object_id=OBJECT_ID)

    def test_a_missing_object_is_a_404(self, flask_app: Flask) -> None:
        """No object with the id is a 404 naming it."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = None

        with flask_app.test_request_context(), pytest.raises(HTTPException) as excinfo:
            read_linked_object(OBJECT_ID, objects_manager, MagicMock())

        assert excinfo.value.code == HTTP_NOT_FOUND
        assert excinfo.value.description == LINKED_OBJECT_NOT_FOUND_MSG.format(object_id=OBJECT_ID)

    def test_without_a_user_the_read_is_unscoped(self) -> None:
        """None is handed on - the manager's convention for a read the caller already authorized."""
        objects_manager = MagicMock(name='objects_manager')

        read_linked_object(OBJECT_ID, objects_manager, None)

        assert objects_manager.get_object.call_args.args[1] is None


class TestWithLocationParent:
    """``with_location_parent`` is the in-memory twin of the location-field write."""

    def test_the_location_field_takes_the_parent(self) -> None:
        """Every field of the location kind holds the new parent; the rest is unchanged."""
        placed = with_location_parent(_real_object(), NEW_PARENT_ID)

        assert {field['name']: field['value'] for field in placed.fields} == {
            NAME_FIELD: NAME_VALUE, LOCATION_FIELD: NEW_PARENT_ID,
        }

    def test_the_original_is_left_untouched(self) -> None:
        """A copy is answered - the caller's object keeps its old placement."""
        original = _real_object()

        with_location_parent(original, NEW_PARENT_ID)

        assert next(field for field in original.fields if field['name'] == LOCATION_FIELD)['value'] == OWN_LOCATION_ID


class TestAbortIfNotPlaceable:
    """``abort_if_not_placeable`` refuses an object that cannot sit in the location tree."""

    def test_an_object_with_a_location_field_passes(self, flask_app: Flask) -> None:
        """Nothing is raised"""
        with flask_app.test_request_context():
            assert abort_if_not_placeable(_real_object()) is None

    def test_an_object_without_a_location_field_is_a_400(self, flask_app: Flask) -> None:
        """Only an object with a location field can sit in the tree; the message names it"""
        unplaceable = _real_object()
        unplaceable.fields = [field for field in unplaceable.fields if field['name'] != LOCATION_FIELD]

        with flask_app.test_request_context(), pytest.raises(HTTPException) as excinfo:
            abort_if_not_placeable(unplaceable)

        assert excinfo.value.code == HTTP_BAD_REQUEST
        assert f'ID:{OBJECT_ID}' in excinfo.value.description


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

    def test_no_has_children_flag_without_the_set(self) -> None:
        """Without a parents_with_children set the nodes carry no has_children flag (old /tree shape)."""
        forest = build_location_forest([_location(PARENT_ID, ROOT_PUBLIC_ID)])

        assert 'has_children' not in forest[0]

    def test_annotates_has_children_from_the_supplied_set(self) -> None:
        """With the set, every node (nested too) is flagged from real-tree children, not the prune."""
        locations = [
            _location(PARENT_ID, ROOT_PUBLIC_ID),
            _location(CHILD_ID, PARENT_ID),
            _location(GRANDCHILD_ID, CHILD_ID),
        ]

        forest = build_location_forest(locations, {PARENT_ID, CHILD_ID})

        root = forest[0]
        child = root['children'][0]
        grandchild = child['children'][0]
        assert root['has_children'] is True         # PARENT_ID is in the set
        assert child['has_children'] is True        # CHILD_ID is in the set
        assert grandchild['has_children'] is False  # GRANDCHILD_ID is not (a leaf in the full tree)


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

    def test_parent_not_selectable_as_parent_aborts_400(self, flask_app: Flask) -> None:
        """A parent whose type is not selectable-as-parent (type_selectable False) is rejected -> 400."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})
        manager.get_location.return_value = {'public_id': NEW_PARENT_ID, 'type_selectable': False}

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_change(OBJECT_ID, NEW_PARENT_ID, manager)

        assert exc_info.value.code == HTTP_BAD_REQUEST
        # rejected on selectability before the cycle lookup
        manager.get_all_descendant_locations.assert_not_called()

    def test_valid_new_parent_passes(self, flask_app: Flask) -> None:
        """An existing, selectable parent outside the object's own subtree is accepted."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID})
        manager.get_location.return_value = {'public_id': NEW_PARENT_ID, 'type_selectable': True}
        manager.get_all_descendant_locations.return_value = [{'public_id': DESCENDANT_LOCATION_ID}]

        with flask_app.test_request_context():
            validate_object_location_change(OBJECT_ID, NEW_PARENT_ID, manager)

    def test_remove_is_always_allowed_without_any_children_lookup(self, flask_app: Flask) -> None:
        """Removing the placement is always allowed - the node's children are promoted, not orphaned."""
        manager = self._manager({'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID})

        with flask_app.test_request_context():
            validate_object_location_change(OBJECT_ID, None, manager)

        # no child lookup of any kind is consulted before allowing the removal
        manager.get_parents_with_children.assert_not_called()
        manager.get_all_descendant_locations.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                normalize_parent_id                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestNormalizeParentId:
    """normalize_parent_id keeps positive ids and maps null / non-positive / non-int to None."""

    def test_positive_id_is_kept(self) -> None:
        """A positive parent id is returned unchanged."""
        assert normalize_parent_id(NEW_PARENT_ID) == NEW_PARENT_ID

    def test_root_id_is_kept(self) -> None:
        """The root id (1) is a valid positive parent and is kept."""
        assert normalize_parent_id(ROOT_PUBLIC_ID) == ROOT_PUBLIC_ID

    def test_zero_becomes_none(self) -> None:
        """Zero (the no-parent sentinel) maps to None (remove placement)."""
        assert normalize_parent_id(0) is None

    def test_none_becomes_none(self) -> None:
        """A null parent maps to None."""
        assert normalize_parent_id(None) is None

    def test_numeric_string_is_coerced(self) -> None:
        """A numeric string is coerced to its int value."""
        assert normalize_parent_id(str(NEW_PARENT_ID)) == NEW_PARENT_ID

    def test_non_numeric_value_becomes_none(self) -> None:
        """A non-numeric value maps to None rather than raising."""
        assert normalize_parent_id('not-a-number') is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_object_location_move                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidateObjectLocationMove:
    """validate_object_location_move checks object/type/location-field, then runs placement validation."""

    @pytest.fixture(autouse=True)
    def _authorized(self):
        """The ACL decision is authorize_object_placement's own (tested on its own): granted here"""
        with patch(f'{HELPER_PATH}.authorize_object_placement') as authorize:
            yield authorize

    @staticmethod
    def _object(has_location: bool) -> MagicMock:
        """A MagicMock CmdbObject with a type id and a configurable has-location-field answer."""
        cmdb_object = MagicMock(name='cmdb_object')
        cmdb_object.get_type_id.return_value = TYPE_ID
        cmdb_object.get_public_id.return_value = OBJECT_ID
        cmdb_object.has_fields_of_type.return_value = has_location
        return cmdb_object

    def test_missing_object_aborts_404(self, flask_app: Flask) -> None:
        """A missing object aborts 404."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = None

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_move(OBJECT_ID, NEW_PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        assert exc_info.value.code == HTTP_NOT_FOUND

    def test_missing_type_aborts_500(self, flask_app: Flask) -> None:
        """An object whose type cannot be resolved aborts 500."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = self._object(True)
        objects_manager.get_object_type.return_value = None

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_move(OBJECT_ID, NEW_PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        assert exc_info.value.code == HTTP_INTERNAL_SERVER_ERROR

    def test_object_without_location_field_aborts_400(self, flask_app: Flask) -> None:
        """An object whose type declares no location field cannot be placed -> 400."""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = self._object(False)
        objects_manager.get_object_type.return_value = MagicMock(name='type')

        with flask_app.test_request_context(), pytest.raises(HTTPException) as exc_info:
            validate_object_location_move(OBJECT_ID, NEW_PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_valid_returns_type_and_runs_placement_validation(self) -> None:
        """A placeable object answers itself with its type, and delegates the placement check to the validator."""
        objects_manager = MagicMock(name='objects_manager')
        cmdb_object = self._object(True)
        object_type = MagicMock(name='type')
        objects_manager.get_object.return_value = cmdb_object
        objects_manager.get_object_type.return_value = object_type
        locations_manager = MagicMock(name='locations_manager')

        with patch(f'{HELPER_PATH}.validate_object_location_change') as validate_change:
            result = validate_object_location_move(
                OBJECT_ID, NEW_PARENT_ID, objects_manager, locations_manager, REQUEST_USER,
            )

        assert result == PlacementTarget(cmdb_object, object_type)
        cmdb_object.has_fields_of_type.assert_called_once_with(FieldType.LOCATION)
        validate_change.assert_called_once_with(OBJECT_ID, NEW_PARENT_ID, locations_manager)

    def test_the_type_is_read_once(self) -> None:
        """The type the ACL read resolved is the one answered - no second get_object_type"""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object.return_value = self._object(True)
        objects_manager.get_object_type.return_value = MagicMock(name='type')

        with patch(f'{HELPER_PATH}.validate_object_location_change'):
            validate_object_location_move(OBJECT_ID, NEW_PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        objects_manager.get_object_type.assert_called_once_with(TYPE_ID)

    def test_the_placement_is_judged_after_the_acl(self, flask_app: Flask, _authorized: MagicMock) -> None:
        """A refused caller learns nothing of the placement: no location-field or parent check runs"""
        objects_manager = MagicMock(name='objects_manager')
        cmdb_object = self._object(False)
        objects_manager.get_object.return_value = cmdb_object
        _authorized.side_effect = HTTPException(response=None)

        with flask_app.test_request_context(), pytest.raises(HTTPException), \
                patch(f'{HELPER_PATH}.validate_object_location_change') as validate_change:
            validate_object_location_move(OBJECT_ID, NEW_PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        cmdb_object.has_fields_of_type.assert_not_called()
        validate_change.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              move_object_location                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMoveObjectLocation:
    """move_object_location validates (unless a target is supplied), then mirrors field + node."""

    def test_validates_then_mirrors_both_sides(self) -> None:
        """With no pre-validated target, it validates first, sets the object field and syncs the node."""
        objects_manager = MagicMock(name='objects_manager')
        locations_manager = MagicMock(name='locations_manager')
        request_user = MagicMock(name='request_user')
        target = PlacementTarget(MagicMock(name='cmdb_object'), MagicMock(name='type'))
        placed = MagicMock(name='placed_object')

        with patch(f'{HELPER_PATH}.validate_object_location_move', return_value=target) as validate_move, \
             patch(f'{HELPER_PATH}.with_location_parent', return_value=placed) as with_parent, \
             patch(f'{HELPER_PATH}.sync_object_location') as sync:
            move_object_location(OBJECT_ID, NEW_PARENT_ID, request_user, objects_manager, locations_manager)

        validate_move.assert_called_once_with(
            OBJECT_ID, NEW_PARENT_ID, objects_manager, locations_manager, request_user,
        )
        objects_manager.set_location_field_for_objects.assert_called_once_with([OBJECT_ID], NEW_PARENT_ID)
        with_parent.assert_called_once_with(target.cmdb_object, NEW_PARENT_ID)
        sync.assert_called_once_with(
            OBJECT_ID, NEW_PARENT_ID, None, target.object_type, request_user, objects_manager, locations_manager,
            cmdb_object=placed,
        )

    def test_supplied_target_skips_validation(self) -> None:
        """When a pre-validated target is passed (bulk path) it does not re-validate; None removes placement."""
        objects_manager = MagicMock(name='objects_manager')
        locations_manager = MagicMock(name='locations_manager')
        request_user = MagicMock(name='request_user')
        target = PlacementTarget(MagicMock(name='cmdb_object'), MagicMock(name='type'))

        with patch(f'{HELPER_PATH}.validate_object_location_move') as validate_move, \
             patch(f'{HELPER_PATH}.with_location_parent', return_value=target.cmdb_object), \
             patch(f'{HELPER_PATH}.sync_object_location') as sync:
            move_object_location(OBJECT_ID, None, request_user, objects_manager, locations_manager, target)

        validate_move.assert_not_called()
        objects_manager.set_location_field_for_objects.assert_called_once_with([OBJECT_ID], None)
        sync.assert_called_once_with(
            OBJECT_ID, None, None, target.object_type, request_user, objects_manager, locations_manager,
            cmdb_object=target.cmdb_object,
        )

    def test_the_moved_object_is_not_read_again(self) -> None:
        """The validated object reaches the mirror, so the name is derived without a second read"""
        objects_manager = MagicMock(name='objects_manager')
        locations_manager = MagicMock(name='locations_manager')
        locations_manager.get_location_for_object.return_value = None
        target = PlacementTarget(_real_object(), MagicMock(name='type'))

        with patch(f'{HELPER_PATH}.derive_location_name', return_value=RESOLVED_NAME):
            move_object_location(OBJECT_ID, NEW_PARENT_ID, MagicMock(), objects_manager, locations_manager, target)

        objects_manager.get_object.assert_not_called()
        assert locations_manager.insert_location.call_args.args[0]['name'] == RESOLVED_NAME


# -------------------------------------------------------------------------------------------------------------------- #
#                                        delete_location_with_reparenting                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteLocationWithReparenting:
    """Promotes the direct-child location nodes AND their objects' location fields to the grandparent."""

    def test_reparents_child_nodes_and_object_fields(self) -> None:
        """The child nodes are promoted by delete_location; the owning objects' fields are re-pointed."""
        locations_manager = MagicMock(name='locations_manager')
        objects_manager = MagicMock(name='objects_manager')
        locations_manager.get_child_object_ids.return_value = [101, 102]
        locations_manager.delete_location.return_value = True

        result = delete_location_with_reparenting(
            {'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID}, locations_manager, objects_manager,
        )

        assert result is True
        # children snapshotted by parent, then the node deleted (which promotes the child nodes)
        locations_manager.get_child_object_ids.assert_called_once_with(OWN_LOCATION_ID)
        locations_manager.delete_location.assert_called_once_with(OWN_LOCATION_ID)
        # the owning objects' location fields are re-pointed at the grandparent
        objects_manager.set_location_field_for_objects.assert_called_once_with([101, 102], NEW_PARENT_ID)

    def test_no_children_still_deletes_and_skips_the_object_write(self) -> None:
        """With no children the node is still deleted, and there is no object field to re-point."""
        locations_manager = MagicMock(name='locations_manager')
        objects_manager = MagicMock(name='objects_manager')
        locations_manager.get_child_object_ids.return_value = []
        locations_manager.find.return_value = []
        locations_manager.delete_location.return_value = True

        delete_location_with_reparenting(
            {'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID}, locations_manager, objects_manager,
        )

        locations_manager.delete_location.assert_called_once_with(OWN_LOCATION_ID)
        objects_manager.set_location_field_for_objects.assert_not_called()

    def test_a_node_already_gone_is_not_recorded_for_re_insertion(self) -> None:
        """
        Deleted concurrently between the caller's read and the snapshot: the delete still runs (and answers
        as the manager does), but there is no snapshot the undo could put back
        """
        locations_manager = MagicMock(name='locations_manager')
        locations_manager.get_one_by.return_value = None
        locations_manager.find.return_value = []
        locations_manager.get_child_object_ids.return_value = []
        locations_manager.delete_location.side_effect = RuntimeError('delete failed')

        with pytest.raises(RuntimeError):
            delete_location_with_reparenting(
                {'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID}, locations_manager, MagicMock(),
            )

        locations_manager.insert.assert_not_called()

    def test_a_failed_object_write_puts_every_earlier_write_back(self) -> None:
        """
        The fields fail after the node is gone: the undo re-points the fields at the node, re-inserts the node
        and restores each child's parent - then the original error surfaces
        """
        node = {'public_id': OWN_LOCATION_ID, 'parent': NEW_PARENT_ID}
        child = {'public_id': 91, 'parent': OWN_LOCATION_ID}
        store: dict[int, dict[str, Any]] = {}
        locations_manager = MagicMock(name='locations_manager')
        locations_manager.get_one_by.side_effect = lambda criteria: store.get(
            criteria['public_id'], node if criteria['public_id'] == OWN_LOCATION_ID else child,
        )
        locations_manager.find.return_value = [child]
        locations_manager.get_child_object_ids.return_value = [101]
        locations_manager.delete_location.return_value = True
        objects_manager = MagicMock(name='objects_manager')
        failure = RuntimeError('field write failed')
        objects_manager.set_location_field_for_objects.side_effect = [failure, None]
        objects_manager.find_objects.return_value = [
            {'public_id': 101, 'fields': [{'name': 'loc', 'type': 'location', 'value': OWN_LOCATION_ID}]},
        ]

        with pytest.raises(RuntimeError) as caught:
            delete_location_with_reparenting(node, locations_manager, objects_manager)

        assert caught.value is failure
        # the inverse re-points the fields back at the node being deleted
        assert objects_manager.set_location_field_for_objects.call_args_list[-1].args == ([101], OWN_LOCATION_ID)
        locations_manager.replace.assert_called_once_with(91, child)


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
        """Runs sync_object_location with the name derivation patched to a fixed value."""
        with patch(f'{HELPER_PATH}.read_linked_object'), \
             patch(f'{HELPER_PATH}.derive_location_name', return_value=RESOLVED_NAME):
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

    def test_deletes_location_with_reparenting_when_parent_removed(self) -> None:
        """A removed parent deletes the existing CmdbLocation via the re-parenting helper."""
        existing = {'public_id': OWN_LOCATION_ID, 'parent': ROOT_PUBLIC_ID}
        manager = self._manager(existing)

        with patch(f'{HELPER_PATH}.delete_location_with_reparenting') as reparent:
            self._sync(manager, None, None)

        reparent.assert_called_once()
        assert reparent.call_args.args[0] == existing
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

        self._sync(manager, NEW_PARENT_ID, EXPLICIT_NAME)

        manager.update_location.assert_called_once_with(OBJECT_ID, {'parent': NEW_PARENT_ID, 'name': EXPLICIT_NAME})

    def test_an_explicit_name_reads_no_object(self) -> None:
        """The name is given, so nothing is derived and the object is not read"""
        manager = self._manager(None)

        with patch(f'{HELPER_PATH}.read_linked_object') as read, \
             patch(f'{HELPER_PATH}.derive_location_name') as derive:
            sync_object_location(OBJECT_ID, NEW_PARENT_ID, EXPLICIT_NAME, self._object_type(),
                                 MagicMock(), MagicMock(), manager)

        read.assert_not_called()
        derive.assert_not_called()
        assert manager.insert_location.call_args.args[0]['name'] == EXPLICIT_NAME

    def test_a_derived_name_reads_the_stored_object_unscoped(self) -> None:
        """No object handed in: the stored one is read without a user - the caller's write authorized it"""
        manager = self._manager(None)
        objects_manager = MagicMock(name='objects_manager')
        request_user = MagicMock(name='request_user')

        with patch(f'{HELPER_PATH}.read_linked_object') as read, \
             patch(f'{HELPER_PATH}.derive_location_name', return_value=RESOLVED_NAME) as derive:
            sync_object_location(OBJECT_ID, NEW_PARENT_ID, None, self._object_type(),
                                 request_user, objects_manager, manager)

        read.assert_called_once_with(OBJECT_ID, objects_manager, None)
        derive.assert_called_once_with(read.return_value, request_user)

    def test_a_handed_in_object_is_not_read_again(self) -> None:
        """The caller's object is what the name is derived from"""
        manager = self._manager(None)
        handed_in = MagicMock(name='cmdb_object')

        with patch(f'{HELPER_PATH}.read_linked_object') as read, \
             patch(f'{HELPER_PATH}.derive_location_name', return_value=RESOLVED_NAME) as derive:
            sync_object_location(OBJECT_ID, NEW_PARENT_ID, None, self._object_type(),
                                 MagicMock(), MagicMock(), manager, cmdb_object=handed_in)

        read.assert_not_called()
        assert derive.call_args.args[0] is handed_in

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

    def test_drops_unused_type_metadata_but_keeps_selectable(self) -> None:
        """type_id and type_label are stripped; type_selectable is kept (for drag-drop) with the rest."""
        manager = MagicMock(name='locations_manager')
        manager.get_parents_with_children.return_value = set()

        node = build_location_level([{
            'public_id': NEW_PARENT_ID, 'name': 'node', 'parent': ROOT_PUBLIC_ID, 'object_id': 99,
            'type_icon': 'fa-cube', 'type_id': 6, 'type_label': 'Building', 'type_selectable': True,
        }], manager)[0]

        assert 'type_id' not in node
        assert 'type_label' not in node
        assert node['type_selectable'] is True
        assert node['type_icon'] == 'fa-cube'
        assert node['object_id'] == 99


# -------------------------------------------------------------------------------------------------------------------- #
#                                          validate_object_location_moves                                              #
# -------------------------------------------------------------------------------------------------------------------- #
BULK_OBJECT_IDS: list[int] = [11, 12, 13]
SHARED_TYPE_ID: int = 700
OTHER_TYPE_ID: int = 701


def _bulk_object(public_id: int, type_id: int) -> MagicMock:
    """A CmdbObject stand-in that has a location field and reports the given type."""
    current_object = MagicMock(name=f'object-{public_id}')
    current_object.get_public_id.return_value = public_id
    current_object.get_type_id.return_value = type_id
    current_object.has_fields_of_type.return_value = True

    return current_object


def _bulk_objects_manager(objects: list[MagicMock]) -> MagicMock:
    """An ObjectsManager stand-in whose $in read returns the given objects."""
    manager = MagicMock(name='objects_manager')
    manager.get_objects_by.return_value = objects
    manager.get_object_type.side_effect = lambda type_id: MagicMock(name=f'type-{type_id}')

    return manager


class TestValidateObjectLocationMoves:
    """The batched pre-flight validates the same things without re-reading what the batch shares."""

    @pytest.fixture(autouse=True)
    def _authorized(self):
        """The ACL decision is authorize_object_placement's own (tested on its own): granted here"""
        with patch(f'{HELPER_PATH}.authorize_object_placement') as authorize:
            yield authorize

    def test_reads_every_object_in_one_query(self, flask_app: Flask) -> None:
        """
        One `$in` read for the whole batch instead of one get_object per object

        This is the point of the helper: the bulk route used to pay a read per object for the objects
        and another per object for their types.
        """
        objects = [_bulk_object(object_id, SHARED_TYPE_ID) for object_id in BULK_OBJECT_IDS]
        objects_manager = _bulk_objects_manager(objects)

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            validate_object_location_moves(BULK_OBJECT_IDS, PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        objects_manager.get_objects_by.assert_called_once_with(criteria={'public_id': {'$in': BULK_OBJECT_IDS}})
        objects_manager.get_object.assert_not_called()

    def test_resolves_each_distinct_type_once(self, flask_app: Flask) -> None:
        """Three objects sharing one type cost one type read, not three."""
        objects = [_bulk_object(object_id, SHARED_TYPE_ID) for object_id in BULK_OBJECT_IDS]
        objects_manager = _bulk_objects_manager(objects)

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            result = validate_object_location_moves(
                BULK_OBJECT_IDS, PARENT_ID, objects_manager, MagicMock(), REQUEST_USER,
            )

        assert objects_manager.get_object_type.call_count == 1
        assert set(result) == set(BULK_OBJECT_IDS)
        assert len({id(target.object_type) for target in result.values()}) == 1

    def test_two_types_are_resolved_once_each(self, flask_app: Flask) -> None:
        """A mixed batch resolves one type per distinct type_id, and maps each object to its own."""
        objects = [_bulk_object(11, SHARED_TYPE_ID), _bulk_object(12, OTHER_TYPE_ID),
                   _bulk_object(13, SHARED_TYPE_ID)]
        objects_manager = _bulk_objects_manager(objects)

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            result = validate_object_location_moves([11, 12, 13], PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        assert objects_manager.get_object_type.call_count == 2
        assert result[11].object_type is result[13].object_type
        assert result[12].object_type is not result[11].object_type

    def test_validates_the_shared_parent_once(self, flask_app: Flask) -> None:
        """The parent is the same for the whole batch, so it is checked once."""
        objects = [_bulk_object(object_id, SHARED_TYPE_ID) for object_id in BULK_OBJECT_IDS]

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent') as shared_parent:
            validate_object_location_moves(
                BULK_OBJECT_IDS, PARENT_ID, _bulk_objects_manager(objects), MagicMock(), MagicMock(name='request_user')
            )

        shared_parent.assert_called_once()

    def test_still_runs_the_cycle_check_per_object(self, flask_app: Flask) -> None:
        """The per-object half depends on where each object sits, so it is NOT batched away."""
        objects = [_bulk_object(object_id, SHARED_TYPE_ID) for object_id in BULK_OBJECT_IDS]

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change') as per_object, \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            validate_object_location_moves(
                BULK_OBJECT_IDS, PARENT_ID, _bulk_objects_manager(objects), MagicMock(), MagicMock(name='request_user')
            )

        assert per_object.call_count == len(BULK_OBJECT_IDS)

    def test_a_missing_object_aborts_404(self, flask_app: Flask) -> None:
        """An id the $in read did not return is a 404, naming that id."""
        objects_manager = _bulk_objects_manager([_bulk_object(11, SHARED_TYPE_ID)])

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            with pytest.raises(HTTPException) as raised:
                validate_object_location_moves([11, 12], PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        assert raised.value.code == HTTP_NOT_FOUND
        assert '12' in raised.value.description

    def test_an_unresolvable_type_aborts_500(self, flask_app: Flask) -> None:
        """A type that does not resolve is a server error, as in the single-object validator."""
        objects_manager = _bulk_objects_manager([_bulk_object(11, SHARED_TYPE_ID)])
        objects_manager.get_object_type.side_effect = None
        objects_manager.get_object_type.return_value = None

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            with pytest.raises(HTTPException) as raised:
                validate_object_location_moves([11], PARENT_ID, objects_manager, MagicMock(), REQUEST_USER)

        assert raised.value.code == HTTP_INTERNAL_SERVER_ERROR

    def test_an_object_without_a_location_field_aborts_400(self, flask_app: Flask) -> None:
        """Only objects whose type declares a location field can sit in the tree."""
        placeless = _bulk_object(11, SHARED_TYPE_ID)
        placeless.has_fields_of_type.return_value = False

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            with pytest.raises(HTTPException) as raised:
                validate_object_location_moves([11], PARENT_ID, _bulk_objects_manager([placeless]),
                                               MagicMock(), REQUEST_USER)

        assert raised.value.code == HTTP_BAD_REQUEST

    def test_the_acl_is_decided_once_per_type(self, flask_app: Flask, _authorized: MagicMock) -> None:
        """Three objects of two types: two decisions, each for the first object of its type"""
        objects = [_bulk_object(11, SHARED_TYPE_ID), _bulk_object(12, OTHER_TYPE_ID),
                   _bulk_object(13, SHARED_TYPE_ID)]

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent'):
            validate_object_location_moves([11, 12, 13], PARENT_ID, _bulk_objects_manager(objects), MagicMock(),
                                           REQUEST_USER)

        assert [call.args[0] for call in _authorized.call_args_list] == [objects[0], objects[1]]
        assert all(call.args[3] is REQUEST_USER for call in _authorized.call_args_list)

    def test_a_denied_object_stops_the_batch_before_the_parent_is_judged(
            self, flask_app: Flask, _authorized: MagicMock) -> None:
        """The ACL comes first: neither the shared parent nor any cycle is checked"""
        objects = [_bulk_object(object_id, SHARED_TYPE_ID) for object_id in BULK_OBJECT_IDS]

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_object_location_change') as per_object, \
             patch(f'{HELPER_PATH}.validate_shared_move_parent') as shared_parent:
            _authorized.side_effect = HTTPException(description='denied')

            with pytest.raises(HTTPException):
                validate_object_location_moves(BULK_OBJECT_IDS, PARENT_ID, _bulk_objects_manager(objects),
                                               MagicMock(), REQUEST_USER)

        shared_parent.assert_not_called()
        per_object.assert_not_called()

    def test_a_missing_object_is_found_before_the_parent_is_judged(self, flask_app: Flask) -> None:
        """Every object is read and authorized first, so a missing one is the 404 whatever the parent"""
        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.validate_shared_move_parent') as shared_parent:
            with pytest.raises(HTTPException) as raised:
                validate_object_location_moves([11, 12], PARENT_ID,
                                               _bulk_objects_manager([_bulk_object(11, SHARED_TYPE_ID)]),
                                               MagicMock(), REQUEST_USER)

        assert raised.value.code == HTTP_NOT_FOUND
        shared_parent.assert_not_called()


class TestValidateSharedMoveParent:
    """The object-independent half of the placement validation."""

    def test_none_parent_is_allowed(self, flask_app: Flask) -> None:
        """Removing the placement needs no parent, so nothing is read."""
        locations_manager = MagicMock(name='locations_manager')

        with flask_app.test_request_context('/'):
            validate_shared_move_parent(None, locations_manager)

        locations_manager.get_location.assert_not_called()

    def test_the_root_is_always_selectable(self, flask_app: Flask) -> None:
        """The synthetic root needs no lookup either."""
        locations_manager = MagicMock(name='locations_manager')

        with flask_app.test_request_context('/'):
            validate_shared_move_parent(RootLocationDefault.PUBLIC_ID, locations_manager)

        locations_manager.get_location.assert_not_called()

    def test_a_missing_parent_aborts_400(self, flask_app: Flask) -> None:
        """A parent id that resolves to nothing is a client error."""
        locations_manager = MagicMock(name='locations_manager')
        locations_manager.get_location.return_value = None

        with flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as raised:
                validate_shared_move_parent(PARENT_ID, locations_manager)

        assert raised.value.code == HTTP_BAD_REQUEST

    def test_a_non_selectable_parent_aborts_400(self, flask_app: Flask) -> None:
        """type_selectable is denormalised onto the node, so the check needs no type read."""
        locations_manager = MagicMock(name='locations_manager')
        locations_manager.get_location.return_value = {'public_id': PARENT_ID, 'type_selectable': False}

        with flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as raised:
                validate_shared_move_parent(PARENT_ID, locations_manager)

        assert raised.value.code == HTTP_BAD_REQUEST


class TestSyncObjectLocationRemovalWithoutNode:
    """Removing a placement an object never had is a no-op, not an error."""

    def test_no_existing_node_means_nothing_is_deleted(self, flask_app: Flask) -> None:
        """
        parent None + no existing CmdbLocation -> return without deleting anything

        A name has to be supplied to get here at all: with no name and no parent change the earlier
        no-op guard returns first. The branch matters because the bulk move normalises "unplace" to
        parent None for every listed object, including ones that were never in the tree.
        """
        locations_manager = MagicMock(name='locations_manager')
        locations_manager.get_location_for_object.return_value = None
        objects_manager = MagicMock(name='objects_manager')

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.delete_location_with_reparenting') as delete_helper:
            sync_object_location(OBJECT_ID, None, EXPLICIT_NAME, MagicMock(), MagicMock(),
                                 objects_manager, locations_manager)

        delete_helper.assert_not_called()
        locations_manager.insert_location.assert_not_called()


class TestLocationFieldsPointAt:
    """The verification of an undone location-field write."""

    @staticmethod
    def _objects(*documents: dict[str, Any]) -> MagicMock:
        """An ObjectsManager whose find_objects answers the given documents."""
        manager = MagicMock(name='objects_manager')
        manager.find_objects.return_value = list(documents)
        return manager

    @staticmethod
    def _with_location(public_id: int, value: Any) -> dict[str, Any]:
        """An object document whose location field holds `value`."""
        return {'public_id': public_id, 'fields': [{'name': 'loc', 'type': 'location', 'value': value}]}

    def test_every_field_at_the_parent_is_true(self) -> None:
        """The undo took effect."""
        manager = self._objects(self._with_location(1, OWN_LOCATION_ID), self._with_location(2, OWN_LOCATION_ID))

        assert location_fields_point_at(manager, [1, 2], OWN_LOCATION_ID) is True

    def test_one_field_elsewhere_is_false(self) -> None:
        """A single object left at the other parent is enough."""
        manager = self._objects(self._with_location(1, OWN_LOCATION_ID), self._with_location(2, NEW_PARENT_ID))

        assert location_fields_point_at(manager, [1, 2], OWN_LOCATION_ID) is False

    def test_a_missing_object_is_false(self) -> None:
        """Nothing to verify is not a verified undo."""
        assert location_fields_point_at(self._objects(self._with_location(1, OWN_LOCATION_ID)), [1, 2],
                                        OWN_LOCATION_ID) is False

    def test_an_object_without_a_location_field_does_not_count_against_it(self) -> None:
        """Only location fields are compared."""
        manager = self._objects({'public_id': 1, 'fields': [{'name': 't', 'type': 'text', 'value': 'x'}]})

        assert location_fields_point_at(manager, [1], OWN_LOCATION_ID) is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                         the placement ACL (READ + UPDATE)                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _placed(type_active: bool = True) -> tuple[MagicMock, MagicMock]:
    """A CmdbObject stand-in and its type, active unless told otherwise."""
    cmdb_object = MagicMock(name='cmdb_object')
    cmdb_object.get_public_id.return_value = OBJECT_ID
    cmdb_object.get_type_id.return_value = TYPE_ID
    object_type = MagicMock(name='object_type')
    object_type.active = type_active

    return cmdb_object, object_type


class TestAuthorizeObjectPlacement:
    """READ on the type, then UPDATE and an active type through the object write guard."""

    def test_granted_answers_nothing(self, flask_app: Flask) -> None:
        """READ asked with READ; the guard asked for UPDATE on the already-resolved type"""
        cmdb_object, object_type = _placed()
        objects_manager = MagicMock(name='objects_manager')

        with flask_app.test_request_context('/'), patch(f'{HELPER_PATH}.verify_access') as read_check:
            authorize_object_placement(cmdb_object, object_type, objects_manager, REQUEST_USER)

        read_check.assert_called_once_with(object_type, REQUEST_USER, AccessControlPermission.READ)
        objects_manager.guard_writable_type.assert_called_once_with(
            TYPE_ID, REQUEST_USER, AccessControlPermission.UPDATE, ObjectsManagerGetError, ObjectWriteVerb.UPDATED,
            object_type=object_type,
        )

    def test_no_read_is_the_read_403_and_asks_no_further(self, flask_app: Flask) -> None:
        """The caller may not see the object: the read message, and the update is not asked"""
        cmdb_object, object_type = _placed()
        objects_manager = MagicMock(name='objects_manager')

        with flask_app.test_request_context('/'), \
             patch(f'{HELPER_PATH}.verify_access', side_effect=AccessDeniedError('no')), \
             pytest.raises(HTTPException) as raised:
            authorize_object_placement(cmdb_object, object_type, objects_manager, REQUEST_USER)

        assert raised.value.code == HTTP_FORBIDDEN
        assert raised.value.description == LINKED_OBJECT_DENIED_MSG.format(object_id=OBJECT_ID)
        objects_manager.guard_writable_type.assert_not_called()

    def test_no_update_is_the_update_403(self, flask_app: Flask) -> None:
        """Readable, not changeable"""
        cmdb_object, object_type = _placed()
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.guard_writable_type.side_effect = AccessDeniedError('Protected by ACL permission!')

        with flask_app.test_request_context('/'), patch(f'{HELPER_PATH}.verify_access'), \
             pytest.raises(HTTPException) as raised:
            authorize_object_placement(cmdb_object, object_type, objects_manager, REQUEST_USER)

        assert raised.value.code == HTTP_FORBIDDEN
        assert raised.value.description == LINKED_OBJECT_UPDATE_DENIED_MSG.format(object_id=OBJECT_ID)

    def test_a_deactivated_type_is_the_guards_own_403(self, flask_app: Flask) -> None:
        """The same message the object write path gives"""
        cmdb_object, object_type = _placed(type_active=False)
        objects_manager = MagicMock(name='objects_manager')
        refusal = 'Objects cannot be updated because type `t` is deactivated.'
        objects_manager.guard_writable_type.side_effect = AccessDeniedError(refusal)

        with flask_app.test_request_context('/'), patch(f'{HELPER_PATH}.verify_access'), \
             pytest.raises(HTTPException) as raised:
            authorize_object_placement(cmdb_object, object_type, objects_manager, REQUEST_USER)

        assert raised.value.code == HTTP_FORBIDDEN
        assert raised.value.description == refusal


class TestResolvePlacedObjectType:
    """The type of a placed object, or a 500."""

    def test_the_type_is_answered(self) -> None:
        """Read by the object's own type id"""
        cmdb_object, object_type = _placed()
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object_type.return_value = object_type

        assert resolve_placed_object_type(cmdb_object, objects_manager) is object_type
        objects_manager.get_object_type.assert_called_once_with(TYPE_ID)

    def test_a_missing_type_is_a_500(self, flask_app: Flask) -> None:
        """A server error, as everywhere a placement resolves the type"""
        objects_manager = MagicMock(name='objects_manager')
        objects_manager.get_object_type.return_value = None

        with flask_app.test_request_context('/'), pytest.raises(HTTPException) as raised:
            resolve_placed_object_type(_placed()[0], objects_manager)

        assert raised.value.code == HTTP_INTERNAL_SERVER_ERROR


class TestReadPlaceableObject:
    """Read through READ, resolve the type, authorize - in that order."""

    def test_reads_resolves_and_authorizes(self) -> None:
        """The object read with the caller, then its type, then the decision on both"""
        cmdb_object, object_type = _placed()
        objects_manager = MagicMock(name='objects_manager')

        with patch(f'{HELPER_PATH}.read_linked_object', return_value=cmdb_object) as read, \
             patch(f'{HELPER_PATH}.resolve_placed_object_type', return_value=object_type), \
             patch(f'{HELPER_PATH}.authorize_object_placement') as authorize:
            target = read_placeable_object(OBJECT_ID, objects_manager, REQUEST_USER)

        assert target == PlacementTarget(cmdb_object, object_type)
        read.assert_called_once_with(OBJECT_ID, objects_manager, REQUEST_USER)
        authorize.assert_called_once_with(cmdb_object, object_type, objects_manager, REQUEST_USER)
