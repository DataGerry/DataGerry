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
Unit tests for the CmdbRackMount route helpers

Managers are mocked, so these assert the decisions each step makes rather than any stored data: which
requests are refused and with which status, that the rack and the object never come from the body, how a
PATCH is merged onto the stored mount, and that unplacing frees the slots while keeping the height hint
"""
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.rack_model import RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKind
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.interface.rest_api.routes.rack_routes.rack_mount_helper import (
    apply_mount_changes,
    assign_position_if_needed,
    build_mount_candidate,
    build_type_meta,
    format_mount_errors_for_abort,
    get_area_filter_or_abort,
    get_mount_of_rack_or_abort,
    get_rack_display_name,
    get_rack_height,
    get_rack_or_abort,
    get_requested_height_or_abort,
    is_rack_type,
    refuse_kind_change,
    resolve_kind_or_abort,
    resolve_assigned_racks,
    resolve_move_source_or_abort,
    resolve_mounted_object_meta,
    same_rack_membership_blocker,
    shape_assignable_page,
    normalize_geometry_value,
    validate_member_object_or_abort,
    validate_placement_or_abort,
    validate_shape_or_abort,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 700
OTHER_RACK_ID: int = 701
RACK_TYPE_ID: int = 70
PLAIN_TYPE_ID: int = 71
NO_LOCATION_TYPE_ID: int = 72
OBJECT_ID: int = 800
MOUNT_ID: int = 900
OTHER_MOUNT_ID: int = 901
RACK_HEIGHT: int = 42

LOCATION_FIELD: dict[str, Any] = {'name': 'dg_location', 'label': 'Location', 'type': FieldType.LOCATION}


def _rack_object(height: Any = RACK_HEIGHT) -> dict[str, Any]:
    """Builds a Rack CmdbObject document"""
    return {
        'public_id': RACK_ID,
        'type_id': RACK_TYPE_ID,
        'fields': [{'name': RackField.HEIGHT.value, 'value': height, 'type': 'number'}],
    }


def _types_manager(rack_type_ids: set[int] | None = None) -> MagicMock:
    """
    A TypesManager where the given type ids resolve to the RACK SpecialType

    PLAIN_TYPE_ID is an ordinary mountable type: it declares a location field, which every rack member's
    type must. NO_LOCATION_TYPE_ID is the same type without one, so it may not be mounted.
    """
    rack_type_ids = rack_type_ids if rack_type_ids is not None else {RACK_TYPE_ID}
    manager = MagicMock()

    def _get_type(type_id: int) -> dict[str, Any] | None:
        if type_id in rack_type_ids:
            # A Rack is placed in the location tree itself, so its own type carries a location field
            return {
                'public_id': type_id,
                'special_type': SpecialType.RACK.value,
                'fields': [LOCATION_FIELD],
            }

        if type_id == PLAIN_TYPE_ID:
            return {'public_id': type_id, 'fields': [LOCATION_FIELD]}

        if type_id == NO_LOCATION_TYPE_ID:
            return {'public_id': type_id, 'fields': [{'name': 'hostname', 'type': 'text'}]}

        return None

    manager.get_type.side_effect = _get_type

    return manager


def _stored_mount(**overrides: Any) -> dict[str, Any]:
    """Builds a stored mount document"""
    mount: dict[str, Any] = {
        'public_id': MOUNT_ID,
        'rack_id': RACK_ID,
        'object_id': OBJECT_ID,
        'area': RackArea.FRONT.value,
        'start_slot': 10,
        'height': 3,
        'position': None,
    }
    mount.update(overrides)

    return mount

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 is_rack_type                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_is_rack_type_true_for_the_rack_type() -> None:
    """The RACK marker on the stored type identifies a rack"""
    assert is_rack_type(_types_manager(), RACK_TYPE_ID) is True


@pytest.mark.parametrize('type_id', [PLAIN_TYPE_ID, 999, None, 'abc'], ids=str)
def test_is_rack_type_false_otherwise(type_id: Any) -> None:
    """An ordinary type, a missing type and a malformed id are all not a rack"""
    assert is_rack_type(_types_manager(), type_id) is False

# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_rack_or_abort                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_rack_returns_the_rack_object() -> None:
    """A real rack is resolved and handed back for its height"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = _rack_object()

    assert get_rack_or_abort(objects_manager, _types_manager(), RACK_ID)['public_id'] == RACK_ID


def test_get_rack_aborts_404_when_nothing_carries_the_id() -> None:
    """A mount is meaningless without its rack"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = None

    with pytest.raises(HTTPException) as err:
        get_rack_or_abort(objects_manager, _types_manager(), RACK_ID)

    assert err.value.code == 404


def test_get_rack_aborts_400_when_the_object_is_not_a_rack() -> None:
    """
    Mounting into an arbitrary object is a business-rule rejection, not a missing resource

    400 rather than 404 because the object does exist - it is just the wrong kind.
    """
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': RACK_ID, 'type_id': PLAIN_TYPE_ID}

    with pytest.raises(HTTPException) as err:
        get_rack_or_abort(objects_manager, _types_manager(), RACK_ID)

    assert err.value.code == 400

# -------------------------------------------------------------------------------------------------------------------- #
#                                                get_rack_height                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('stored, expected', [(42, 42), ('42', 42), (42.0, 42)], ids=str)
def test_get_rack_height_reads_the_field(stored: Any, expected: int) -> None:
    """The height is a normal field, and the same coercion as the write invariants applies"""
    assert get_rack_height(_rack_object(height=stored)) == expected


@pytest.mark.parametrize('stored', [None, '', 0, -3, 'abc', 3.5], ids=str)
def test_get_rack_height_falls_back_to_zero_for_a_drifted_rack(stored: Any) -> None:
    """
    An unusable height yields 0, which fails every placement rather than passing it

    A rack that got through the write invariants always has a positive int here; this is the guard for
    one that did not.
    """
    assert get_rack_height(_rack_object(height=stored)) == 0

# -------------------------------------------------------------------------------------------------------------------- #
#                                       validate_member_object_or_abort                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_plain_object_may_be_mounted() -> None:
    """A type that declares a location field and is not a Rack is mountable"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID}

    assert validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, OBJECT_ID) == OBJECT_ID


def test_a_string_object_id_is_accepted_and_coerced() -> None:
    """A form-encoded client sends the id as a string"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID}

    assert validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, str(OBJECT_ID)) == OBJECT_ID


def test_a_missing_object_id_is_refused() -> None:
    """There is nothing to mount without an object"""
    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(MagicMock(), _types_manager(), RACK_ID, None)

    assert err.value.code == 400


@pytest.mark.parametrize('object_id', [0, -5, 'abc', 3.5], ids=str)
def test_an_unusable_object_id_is_refused(object_id: Any) -> None:
    """A public_id is a positive whole number"""
    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(MagicMock(), _types_manager(), RACK_ID, object_id)

    assert err.value.code == 400


def test_mounting_the_rack_into_itself_is_refused() -> None:
    """Caught before any read - the ids alone settle it"""
    objects_manager = MagicMock()

    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, RACK_ID)

    assert err.value.code == 400
    objects_manager.get_object.assert_not_called()


def test_mounting_a_nonexistent_object_is_refused() -> None:
    """A membership pointing at nothing would dangle from the moment it was written"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = None

    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, OBJECT_ID)

    assert err.value.code == 400


def test_mounting_another_rack_is_refused() -> None:
    """Racks do not nest, although the Rack type does carry a location field"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': OBJECT_ID, 'type_id': RACK_TYPE_ID}

    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, OBJECT_ID)

    assert err.value.code == 400
    assert 'another Rack' in err.value.description


def test_mounting_an_object_whose_type_has_no_location_field_is_refused() -> None:
    """
    A member is mirrored into the tree through its own location field

    Without one there is nowhere to record where the object is, so it can not be a member at all - the
    same rule the picker filters on, enforced here so an API client meets it too.
    """
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': OBJECT_ID, 'type_id': NO_LOCATION_TYPE_ID}

    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, OBJECT_ID)

    assert err.value.code == 400
    assert 'location field' in err.value.description


def test_mounting_an_object_whose_type_vanished_is_refused() -> None:
    """A type that does not resolve can not be shown to declare a location field"""
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': OBJECT_ID, 'type_id': 4242}

    with pytest.raises(HTTPException) as err:
        validate_member_object_or_abort(objects_manager, _types_manager(), RACK_ID, OBJECT_ID)

    assert err.value.code == 400

# -------------------------------------------------------------------------------------------------------------------- #
#                                       same_rack_membership_blocker                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_an_object_in_no_rack_is_free_to_mount() -> None:
    """Nothing holds it, so there is nothing to judge"""
    assert same_rack_membership_blocker(None, RACK_ID, OBJECT_ID) is None


def test_an_object_in_another_rack_is_not_blocked() -> None:
    """It is offered by the picker and mounting it moves it - a second membership is no longer refused"""
    other_mount = _stored_mount(public_id=OTHER_MOUNT_ID, rack_id=OTHER_RACK_ID)

    assert same_rack_membership_blocker(other_mount, RACK_ID, OBJECT_ID) is None


def test_an_object_already_in_this_rack_is_blocked() -> None:
    """Re-inserting it would drop its mount's public_id and collide with its own slots - PATCH it instead"""
    blocker = same_rack_membership_blocker(_stored_mount(), RACK_ID, OBJECT_ID)

    assert blocker is not None
    assert 'already in this Rack' in blocker


def test_the_mount_being_changed_is_excluded_from_its_own_check() -> None:
    """A PATCH of an existing mount is obviously allowed to be the one holding the object"""
    assert same_rack_membership_blocker(_stored_mount(), RACK_ID, OBJECT_ID, MOUNT_ID) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                        resolve_move_source_or_abort                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_free_object_has_no_move_source() -> None:
    """An ordinary mount - nothing has to be removed first"""
    manager = MagicMock()
    manager.get_mount_of_object.return_value = None

    assert resolve_move_source_or_abort(manager, RACK_ID, OBJECT_ID) is None


def test_the_mount_of_another_rack_is_returned_as_the_move_source() -> None:
    """The caller deletes it to complete the move"""
    other_mount = _stored_mount(public_id=OTHER_MOUNT_ID, rack_id=OTHER_RACK_ID)
    manager = MagicMock()
    manager.get_mount_of_object.return_value = other_mount

    assert resolve_move_source_or_abort(manager, RACK_ID, OBJECT_ID) == other_mount


def test_resolving_a_move_aborts_400_for_an_object_already_in_this_rack() -> None:
    """The write path's wrapper around the blocker"""
    manager = MagicMock()
    manager.get_mount_of_object.return_value = _stored_mount()

    with pytest.raises(HTTPException) as err:
        resolve_move_source_or_abort(manager, RACK_ID, OBJECT_ID)

    assert err.value.code == 400

# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_mount_candidate                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_bare_request_assigns_without_placing() -> None:
    """
    A body carrying only an object_id means "assign to this rack, do not place it"

    That is what makes the unassigned bucket reachable without a special route.
    """
    candidate = build_mount_candidate(RACK_ID, OBJECT_ID, {})

    assert candidate['area'] == RackArea.UNASSIGNED.value
    assert candidate['start_slot'] is None
    assert candidate['height'] is None
    assert candidate['position'] is None


def test_the_rack_and_object_come_from_the_arguments_not_the_body() -> None:
    """A payload can not move a mount into a different rack or onto a different object"""
    candidate = build_mount_candidate(RACK_ID, OBJECT_ID, {'rack_id': 1, 'object_id': 2})

    assert candidate['rack_id'] == RACK_ID
    assert candidate['object_id'] == OBJECT_ID


def test_geometry_is_taken_from_the_body_and_coerced() -> None:
    """A placement request carries its geometry, as strings from a form client"""
    candidate = build_mount_candidate(RACK_ID, OBJECT_ID, {
        'area': RackArea.FRONT.value, 'start_slot': '10', 'height': '3',
    })

    assert candidate['start_slot'] == 10
    assert candidate['height'] == 3


def test_every_geometry_key_is_always_present() -> None:
    """A mount document has one shape whether or not the request set the geometry"""
    candidate = build_mount_candidate(RACK_ID, OBJECT_ID, {'area': RackArea.LEFT.value})

    for key in ('start_slot', 'height', 'position'):
        assert key in candidate

# -------------------------------------------------------------------------------------------------------------------- #
#                                          normalize_geometry_value                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value, expected', [(None, None), ('', None), (5, 5), ('5', 5), (5.0, 5)], ids=str)
def test_normalize_geometry_value(value: Any, expected: Any) -> None:
    """An empty string is what a cleared number input sends, so it means "unset\""""
    assert normalize_geometry_value(value) == expected


@pytest.mark.parametrize('value', ['abc', 3.5], ids=str)
def test_an_unusable_geometry_value_is_passed_through(value: Any) -> None:
    """
    Kept as sent so the validator can echo it back

    Coercing it to None would turn "3.5 is not a slot" into the misleading "a start slot is required".
    """
    assert normalize_geometry_value(value) == value

# -------------------------------------------------------------------------------------------------------------------- #
#                                            apply_mount_changes                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_patch_only_applies_the_keys_it_carries() -> None:
    """A body naming just an area moves the mount without touching its geometry"""
    candidate = apply_mount_changes(_stored_mount(), {'area': RackArea.BACK.value})

    assert candidate['area'] == RackArea.BACK.value
    assert candidate['start_slot'] == 10
    assert candidate['height'] == 3


def test_a_patch_can_reslot_a_mount() -> None:
    """The common move: same area, new slot"""
    candidate = apply_mount_changes(_stored_mount(), {'start_slot': 20})

    assert candidate['start_slot'] == 20
    assert candidate['area'] == RackArea.FRONT.value


def test_unplacing_clears_the_slot_but_keeps_the_height() -> None:
    """
    The height is the tedious value to re-enter, so it survives as a re-placing hint

    The slot is what the user picks when re-placing, so it is cleared.
    """
    candidate = apply_mount_changes(_stored_mount(), {'area': RackArea.UNASSIGNED.value})

    assert candidate['area'] == RackArea.UNASSIGNED.value
    assert candidate['start_slot'] is None
    assert candidate['height'] == 3


def test_a_patch_never_changes_the_membership() -> None:
    """The rack and the object are not patchable - a move between racks is a delete plus a create"""
    candidate = apply_mount_changes(_stored_mount(), {'rack_id': 1, 'object_id': 2})

    assert candidate['rack_id'] == RACK_ID
    assert candidate['object_id'] == OBJECT_ID


def test_an_empty_patch_leaves_the_mount_as_it_was() -> None:
    """Nothing requested, nothing changed"""
    assert apply_mount_changes(_stored_mount(), {}) == _stored_mount()

# -------------------------------------------------------------------------------------------------------------------- #
#                                         assign_position_if_needed                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('area', [RackArea.LEFT.value, RackArea.RIGHT.value, RackArea.UNASSIGNED.value])
def test_an_ordered_area_gets_an_appended_position(area: str) -> None:
    """A member of an ordered area with no position given goes to the end"""
    manager = MagicMock()
    manager.get_next_position.return_value = 4
    candidate = {'rack_id': RACK_ID, 'area': area, 'position': None}

    assign_position_if_needed(manager, candidate)

    assert candidate['position'] == 4


def test_an_explicit_position_is_respected() -> None:
    """A reorder request names the position it wants"""
    manager = MagicMock()
    candidate = {'rack_id': RACK_ID, 'area': RackArea.LEFT.value, 'position': 2}

    assign_position_if_needed(manager, candidate)

    assert candidate['position'] == 2
    manager.get_next_position.assert_not_called()


def test_a_main_area_mount_has_its_position_cleared() -> None:
    """A main-area mount is ordered by its slots, so a position there is meaningless"""
    manager = MagicMock()
    candidate = {'rack_id': RACK_ID, 'area': RackArea.FRONT.value, 'position': 7}

    assign_position_if_needed(manager, candidate)

    assert candidate['position'] is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                        validate_placement_or_abort                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_overlap_read_asks_only_for_the_competing_areas() -> None:
    """
    A FRONT placement competes with FRONT and FULL_DEPTH only

    Reading the whole rack would work but scans rows that can never conflict.
    """
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = []

    validate_placement_or_abort(
        manager, {'rack_id': RACK_ID, 'area': RackArea.FRONT.value, 'start_slot': 1, 'height': 1}, RACK_HEIGHT,
    )

    _, areas = manager.get_mounts_in_areas.call_args.args
    assert areas == {RackArea.FRONT.value, RackArea.FULL_DEPTH.value}


def test_a_side_placement_reads_no_competing_areas() -> None:
    """Nothing can collide in a side list, so the read is empty by construction"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = []

    validate_placement_or_abort(manager, {'rack_id': RACK_ID, 'area': RackArea.LEFT.value}, RACK_HEIGHT)

    _, areas = manager.get_mounts_in_areas.call_args.args
    assert areas == set()


def test_an_invalid_placement_aborts_400_with_the_rack_mount_prefix() -> None:
    """The message is labelled as a Rack mount problem, not an IPAM or a generic one"""
    manager = MagicMock()
    manager.get_mounts_in_areas.return_value = [
        {'public_id': 5, 'area': RackArea.FRONT.value, 'start_slot': 4, 'height': 4},
    ]

    with pytest.raises(HTTPException) as err:
        validate_placement_or_abort(
            manager, {'rack_id': RACK_ID, 'area': RackArea.FRONT.value, 'start_slot': 2, 'height': 1}, RACK_HEIGHT,
        )

    assert err.value.code == 400
    assert 'Rack mount validation failed' in err.value.description


def test_the_formatter_joins_every_message() -> None:
    """All problems with one placement are reported together"""
    assert format_mount_errors_for_abort(['a', 'b']) == 'Rack mount validation failed: a | b'

# -------------------------------------------------------------------------------------------------------------------- #
#                                       get_mount_of_rack_or_abort                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_mount_of_the_rack_is_returned() -> None:
    """The happy path"""
    manager = MagicMock()
    manager.get_item.return_value = _stored_mount()

    assert get_mount_of_rack_or_abort(manager, RACK_ID, MOUNT_ID)['public_id'] == MOUNT_ID


def test_a_missing_mount_aborts_404() -> None:
    """Nothing to change"""
    manager = MagicMock()
    manager.get_item.return_value = None

    with pytest.raises(HTTPException) as err:
        get_mount_of_rack_or_abort(manager, RACK_ID, MOUNT_ID)

    assert err.value.code == 404


def test_a_mount_of_a_different_rack_aborts_404() -> None:
    """
    The ownership check stops a caller editing any mount by guessing its id

    Reported as 404 so it is indistinguishable from a mount that does not exist.
    """
    manager = MagicMock()
    manager.get_item.return_value = _stored_mount(rack_id=RACK_ID + 1)

    with pytest.raises(HTTPException) as err:
        get_mount_of_rack_or_abort(manager, RACK_ID, MOUNT_ID)

    assert err.value.code == 404

# -------------------------------------------------------------------------------------------------------------------- #
#                                         get_area_filter_or_abort                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('raw', [None, ''], ids=str)
def test_no_area_filter_means_every_area(raw: Any) -> None:
    """An absent filter is not an error"""
    assert get_area_filter_or_abort(raw) is None


def test_a_valid_area_filter_is_returned() -> None:
    """A known area narrows the read"""
    assert get_area_filter_or_abort(RackArea.LEFT.value) == RackArea.LEFT.value


def test_an_unknown_area_filter_aborts_400() -> None:
    """A typo'd filter must not silently return every mount"""
    with pytest.raises(HTTPException) as err:
        get_area_filter_or_abort('NOPE')

    assert err.value.code == 400


def test_an_invalid_area_leaves_the_position_alone() -> None:
    """
    A candidate with an unknown area is the validator's problem, not the ordering's

    Inventing a position for it would write a value the request never asked for onto a mount that is
    about to be refused anyway.
    """
    manager = MagicMock()
    candidate = {'rack_id': RACK_ID, 'area': 'GARBAGE', 'position': None}

    assign_position_if_needed(manager, candidate)

    assert candidate['position'] is None
    manager.get_next_position.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_rack_display_name                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def _rack_with(name: Any = None, number: Any = None) -> dict[str, Any]:
    """Builds a Rack CmdbObject carrying the given name and number"""
    return {
        'public_id': RACK_ID,
        'type_id': RACK_TYPE_ID,
        'fields': [
            {'name': RackField.NAME.value, 'value': name, 'type': 'text'},
            {'name': RackField.NUMBER.value, 'value': number, 'type': 'text'},
        ],
    }


def test_the_display_name_is_the_rackname() -> None:
    """dg-rack-name is required, so it normally wins outright"""
    assert get_rack_display_name(_rack_with(name='rack-a', number='R-1')) == 'rack-a'


def test_the_display_name_is_stripped() -> None:
    """Surrounding whitespace is not part of a name"""
    assert get_rack_display_name(_rack_with(name='  rack-a  ')) == 'rack-a'


@pytest.mark.parametrize('name', [None, '', '   '], ids=repr)
def test_a_blank_name_falls_back_to_the_number(name: Any) -> None:
    """
    Only reachable for a Rack predating the write invariants

    'required' is a frontend marker, so a stored rack could carry a blank name - and an empty label in
    the picker or the location tree is worse than a generated one.
    """
    assert get_rack_display_name(_rack_with(name=name, number='R-9')) == 'Rack #R-9'


def test_a_blank_name_and_number_fall_back_to_the_public_id() -> None:
    """The last resort always identifies the rack uniquely"""
    assert get_rack_display_name(_rack_with()) == f'Rack #{RACK_ID}'


@pytest.mark.parametrize('number', [None, '', '  '], ids=repr)
def test_a_blank_number_is_not_used_as_a_name(number: Any) -> None:
    """'Rack #' with nothing after it would be worse than the id"""
    assert get_rack_display_name(_rack_with(number=number)) == f'Rack #{RACK_ID}'

# -------------------------------------------------------------------------------------------------------------------- #
#                                       resolve_mounted_object_meta                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_object_meta_is_resolved_in_bulk() -> None:
    """
    Three reads for the whole rack, however many objects it holds

    Resolving per mount would be an N+1 on the one route called every time a rack is opened.
    """
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [
        {'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID},
        {'public_id': OBJECT_ID + 1, 'type_id': PLAIN_TYPE_ID},
    ]
    objects_manager.get_summary_lines_lookup.return_value = {OBJECT_ID: 'server-01'}

    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        PLAIN_TYPE_ID: SimpleNamespace(
            label='Server', get_icon=lambda: 'fa-server', ci_explorer_color='#4b9e46',
        ),
    }

    mounts = [
        {'public_id': 1, 'object_id': OBJECT_ID},
        {'public_id': 2, 'object_id': OBJECT_ID + 1},
    ]

    summary_lines, type_meta, object_types = resolve_mounted_object_meta(
        objects_manager, types_manager, mounts,
    )

    assert objects_manager.find_objects.call_count == 1
    assert objects_manager.get_summary_lines_lookup.call_count == 1
    assert types_manager.get_types_lookup.call_count == 1
    assert summary_lines == {OBJECT_ID: 'server-01'}
    assert type_meta[PLAIN_TYPE_ID]['type_label'] == 'Server'
    assert type_meta[PLAIN_TYPE_ID]['type_color'] == '#4b9e46'
    assert object_types == {OBJECT_ID: PLAIN_TYPE_ID, OBJECT_ID + 1: PLAIN_TYPE_ID}


def test_the_object_meta_reuses_the_loaded_documents() -> None:
    """The summary lookup is handed the docs already read, so it does not fetch them again"""
    objects_manager = MagicMock()
    docs = [{'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID}]
    objects_manager.find_objects.return_value = docs
    objects_manager.get_summary_lines_lookup.return_value = {}
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {}

    resolve_mounted_object_meta(objects_manager, types_manager, [{'public_id': 1, 'object_id': OBJECT_ID}])

    assert objects_manager.get_summary_lines_lookup.call_args.kwargs['object_docs'] == docs


def test_no_reads_happen_for_an_empty_rack() -> None:
    """An empty rack costs nothing"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    assert resolve_mounted_object_meta(objects_manager, types_manager, []) == ({}, {}, {})
    objects_manager.find_objects.assert_not_called()


def test_a_mount_without_an_integer_object_id_is_skipped() -> None:
    """A drifted row must not poison the '$in' of the bulk read"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    assert resolve_mounted_object_meta(
        objects_manager, types_manager, [{'public_id': 1, 'object_id': None}],
    ) == ({}, {}, {})
    objects_manager.find_objects.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                     get_requested_height_or_abort                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('raw, expected', [('10', 10), (10, 10), ('10.0', 10)], ids=str)
def test_a_valid_candidate_height_is_accepted(raw: Any, expected: int) -> None:
    """The parameter arrives as a query string, so it is coerced like every other geometry value"""
    assert get_requested_height_or_abort(raw) == expected


@pytest.mark.parametrize('raw', [None, ''], ids=repr)
def test_a_missing_candidate_height_aborts_400(raw: Any) -> None:
    """There is nothing to check against"""
    with pytest.raises(HTTPException) as err:
        get_requested_height_or_abort(raw)

    assert err.value.code == 400


@pytest.mark.parametrize('raw', [0, -5, 'abc', '3.5'], ids=str)
def test_an_unusable_candidate_height_aborts_400(raw: Any) -> None:
    """A rack height is a positive whole number, here as everywhere else"""
    with pytest.raises(HTTPException) as err:
        get_requested_height_or_abort(raw)

    assert err.value.code == 400

# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_type_meta                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_type_meta_collapses_duplicate_ids() -> None:
    """A page full of one type must not ask for that type once per row"""
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        PLAIN_TYPE_ID: SimpleNamespace(
            label='Server', get_icon=lambda: 'fa-server', ci_explorer_color='#4b9e46',
        ),
    }

    meta = build_type_meta(types_manager, [PLAIN_TYPE_ID, PLAIN_TYPE_ID, PLAIN_TYPE_ID])

    assert types_manager.get_types_lookup.call_args.args[0] == [PLAIN_TYPE_ID]
    assert meta[PLAIN_TYPE_ID]['type_label'] == 'Server'
    assert meta[PLAIN_TYPE_ID]['type_icon'] == 'fa-server'
    assert meta[PLAIN_TYPE_ID]['type_color'] == '#4b9e46'


def test_the_type_meta_skips_the_read_for_no_ids() -> None:
    """An empty page costs nothing"""
    types_manager = MagicMock()

    assert build_type_meta(types_manager, []) == {}
    types_manager.get_types_lookup.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                         shape_assignable_page                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_picker_page_is_resolved_in_bulk_reads() -> None:
    """One page, one summary lookup and one type lookup - however many candidates it holds"""
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {OBJECT_ID: 'server-01'}
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {
        PLAIN_TYPE_ID: SimpleNamespace(
            label='Server', get_icon=lambda: 'fa-server', ci_explorer_color='#4b9e46',
        ),
    }
    rack_mounts_manager = MagicMock()
    rack_mounts_manager.get_mounts_of_objects.return_value = []

    docs = [
        {'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID},
        {'public_id': OBJECT_ID + 1, 'type_id': PLAIN_TYPE_ID},
    ]

    rows = shape_assignable_page(objects_manager, types_manager, rack_mounts_manager, docs)

    assert objects_manager.get_summary_lines_lookup.call_count == 1
    assert types_manager.get_types_lookup.call_count == 1
    assert rack_mounts_manager.get_mounts_of_objects.call_count == 1
    assert [row['public_id'] for row in rows] == [OBJECT_ID, OBJECT_ID + 1]
    assert rows[0]['summary_line'] == 'server-01'
    assert rows[0]['type_label'] == 'Server'
    assert rows[0]['assigned_rack_id'] is None


def test_the_picker_page_reuses_the_documents_it_was_given() -> None:
    """The aggregation already returned the documents, so the summary lookup must not re-fetch them"""
    objects_manager = MagicMock()
    objects_manager.get_summary_lines_lookup.return_value = {}
    types_manager = MagicMock()
    types_manager.get_types_lookup.return_value = {}
    rack_mounts_manager = MagicMock()
    rack_mounts_manager.get_mounts_of_objects.return_value = []
    docs = [{'public_id': OBJECT_ID, 'type_id': PLAIN_TYPE_ID}]

    shape_assignable_page(objects_manager, types_manager, rack_mounts_manager, docs)

    assert objects_manager.get_summary_lines_lookup.call_args.kwargs['object_docs'] == docs
    assert objects_manager.get_summary_lines_lookup.call_args.kwargs['with_type'] is False


def test_an_empty_picker_page_reads_nothing() -> None:
    """A rack whose every candidate is taken costs no lookup at all"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    rack_mounts_manager = MagicMock()
    rack_mounts_manager.get_mounts_of_objects.return_value = []

    assert shape_assignable_page(objects_manager, types_manager, rack_mounts_manager, []) == []
    objects_manager.get_summary_lines_lookup.assert_not_called()
    types_manager.get_types_lookup.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                           resolve_assigned_racks                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_page_of_free_candidates_reads_no_rack() -> None:
    """No mount holds any of them, so there is no rack to name and no second read"""
    objects_manager = MagicMock()
    rack_mounts_manager = MagicMock()
    rack_mounts_manager.get_mounts_of_objects.return_value = []

    assert resolve_assigned_racks(objects_manager, rack_mounts_manager, [OBJECT_ID]) == {}
    objects_manager.find_objects.assert_not_called()


def test_a_candidate_in_another_rack_resolves_to_that_racks_name() -> None:
    """The hint is the rack's id and its display name, resolved for the whole page in one read"""
    rack_mounts_manager = MagicMock()
    rack_mounts_manager.get_mounts_of_objects.return_value = [
        _stored_mount(public_id=OTHER_MOUNT_ID, rack_id=OTHER_RACK_ID),
    ]
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [{
        'public_id': OTHER_RACK_ID,
        'type_id': RACK_TYPE_ID,
        'fields': [{'name': RackField.NAME.value, 'value': 'Rack A', 'type': 'text'}],
    }]

    assigned = resolve_assigned_racks(objects_manager, rack_mounts_manager, [OBJECT_ID])

    assert assigned[OBJECT_ID]['public_id'] == OTHER_RACK_ID
    assert assigned[OBJECT_ID]['display_name'] == 'Rack A'


def test_a_mount_whose_rack_vanished_contributes_no_hint() -> None:
    """A row reads as free rather than naming a rack the user can not open"""
    rack_mounts_manager = MagicMock()
    rack_mounts_manager.get_mounts_of_objects.return_value = [
        _stored_mount(public_id=OTHER_MOUNT_ID, rack_id=OTHER_RACK_ID),
    ]
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    assert resolve_assigned_racks(objects_manager, rack_mounts_manager, [OBJECT_ID]) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the row kinds - build and merge                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_candidate_defaults_to_the_mount_kind() -> None:
    """A client that predates the reservations keeps creating mounts without saying so"""
    candidate = build_mount_candidate(RACK_ID, OBJECT_ID, {})

    assert candidate['kind'] == RackMountKind.MOUNT.value
    assert candidate['object_id'] == OBJECT_ID


def test_an_occupant_candidate_omits_the_object_id_entirely() -> None:
    """
    Omitted, not stored as null

    The unique index is partial on the field's presence, and a stored null would still be indexed - so
    the second occupant in the collection would be refused with a duplicate-key error.
    """
    candidate = build_mount_candidate(RACK_ID, None, {}, RackMountKind.BLOCKER.value)

    assert 'object_id' not in candidate
    assert candidate['kind'] == RackMountKind.BLOCKER.value


def test_a_reservation_candidate_carries_its_dates_and_colour() -> None:
    """Parsed on the way in, so what is stored is a datetime rather than whatever string arrived"""
    candidate = build_mount_candidate(RACK_ID, None, {
        'start_date': '2026-09-01', 'end_date': '2026-09-30', 'color': '#4CAF50',
    }, RackMountKind.RESERVATION.value)

    assert candidate['start_date'] == datetime(2026, 9, 1)
    assert candidate['end_date'] == datetime(2026, 9, 30)
    assert candidate['color'] == '#4CAF50'


def test_a_blocker_candidate_carries_no_reservation_fields_at_all() -> None:
    """Not even as nulls - a blocker has no date range to speak of"""
    candidate = build_mount_candidate(RACK_ID, None, {}, RackMountKind.BLOCKER.value)

    assert 'start_date' not in candidate
    assert 'end_date' not in candidate
    assert 'color' not in candidate


def test_a_label_is_carried_on_any_kind() -> None:
    """The one descriptive field that is not reservation-specific"""
    assert build_mount_candidate(RACK_ID, None, {'label': 'Metal frame'},
                                 RackMountKind.BLOCKER.value)['label'] == 'Metal frame'


def test_a_patch_can_edit_a_reservations_descriptive_fields() -> None:
    """Each is editable on its own, without re-sending the geometry"""
    stored = _stored_mount(kind=RackMountKind.RESERVATION.value, label='old', color='#000000')

    candidate = apply_mount_changes(stored, {'label': 'new', 'color': '#4CAF50'})

    assert candidate['label'] == 'new'
    assert candidate['color'] == '#4CAF50'
    assert candidate['start_slot'] == stored['start_slot']


def test_a_patch_can_clear_a_reservation_date() -> None:
    """Both ends are optional, so removing one has to be expressible"""
    stored = _stored_mount(kind=RackMountKind.RESERVATION.value, end_date=datetime(2026, 9, 30))

    assert apply_mount_changes(stored, {'end_date': None})['end_date'] is None


def test_a_patch_parses_a_date_it_is_given() -> None:
    """A JSON body carries a string; what is stored is a datetime"""
    stored = _stored_mount(kind=RackMountKind.RESERVATION.value)

    assert apply_mount_changes(stored, {'start_date': '2026-09-01'})['start_date'] == datetime(2026, 9, 1)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          the kind route guards                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_resolving_an_absent_kind_yields_mount() -> None:
    """The default that keeps every existing client working"""
    assert resolve_kind_or_abort({}) == RackMountKind.MOUNT.value


def test_resolving_an_unknown_kind_aborts_400() -> None:
    """Refused rather than defaulted - a misspelling must not create the wrong kind of row"""
    with pytest.raises(HTTPException) as err:
        resolve_kind_or_abort({'kind': 'RESERVATON'})

    assert err.value.code == 400


def test_a_wrong_shaped_row_aborts_400_with_every_reason() -> None:
    """One corrected payload rather than one refusal per request"""
    with pytest.raises(HTTPException) as err:
        validate_shape_or_abort(
            RackMountKind.BLOCKER.value,
            {'object_id': OBJECT_ID, 'color': '#4CAF50'},
            {'area': RackArea.FRONT.value},
        )

    assert err.value.code == 400
    assert 'object_id' in err.value.description
    assert 'color' in err.value.description


def test_a_well_shaped_row_passes_the_guard() -> None:
    """The happy path writes nothing and raises nothing"""
    validate_shape_or_abort(RackMountKind.MOUNT.value, {'object_id': OBJECT_ID},
                            {'area': RackArea.FRONT.value})


def test_changing_the_kind_of_a_stored_row_aborts_400() -> None:
    """A reservation is deleted and re-created as a mount, never converted in place"""
    with pytest.raises(HTTPException) as err:
        refuse_kind_change(_stored_mount(kind=RackMountKind.RESERVATION.value),
                           {'kind': RackMountKind.MOUNT.value})

    assert err.value.code == 400


def test_echoing_the_stored_kind_back_is_allowed() -> None:
    """A client that PATCHes the whole row must not be refused for sending what is already there"""
    refuse_kind_change(_stored_mount(kind=RackMountKind.RESERVATION.value),
                       {'kind': RackMountKind.RESERVATION.value})
