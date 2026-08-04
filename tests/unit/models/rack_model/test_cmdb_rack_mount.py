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
Unit tests for cmdb.models.rack_model.cmdb_rack_mount and its constants

Pins the index declarations - the unique 'object_id' index is what actually guarantees one rack per
object, so it is a contract, not an implementation detail - plus the from_data / to_json round trip and
the two convenience readers on the model
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.models.rack_model import CmdbRackMount, RackArea, RackMountKey
from cmdb.errors.models.cmdb_rack_mount import (
    CmdbRackMountInitError,
    CmdbRackMountInitFromDataError,
    CmdbRackMountToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 700
OBJECT_ID: int = 800
MOUNT_ID: int = 900


def _mount_data(**overrides: Any) -> dict[str, Any]:
    """Builds a stored mount document, overridable per test"""
    data: dict[str, Any] = {
        'public_id': MOUNT_ID,
        'rack_id': RACK_ID,
        'object_id': OBJECT_ID,
        'area': RackArea.FRONT.value,
        'start_slot': 10,
        'height': 3,
        'position': None,
        'author_id': 1,
    }
    data.update(overrides)

    return data

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     indexes                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_object_id_index_is_unique() -> None:
    """
    One rack per object is enforced by this index and nothing else

    The routes pre-check it for a readable error, but a concurrent pair of requests can only be stopped
    here - so this declaration is the guarantee.
    """
    index = next(i for i in CmdbRackMount.INDEX_KEYS if i['name'] == 'object_id')

    assert index['unique'] is True


def test_rack_area_compound_index_exists() -> None:
    """Every rack read filters on (rack_id, area), so it is served from one index"""
    index = next(i for i in CmdbRackMount.INDEX_KEYS if i['name'] == 'rack_area')

    assert [key for key, _ in index['keys']] == ['rack_id', 'area']
    assert index['unique'] is False


def test_collection_name_is_pinned() -> None:
    """The collection name is stored data - changing it would orphan every mount"""
    assert CmdbRackMount.COLLECTION == 'framework.rackMounts'

# -------------------------------------------------------------------------------------------------------------------- #
#                                              from_data / to_json                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_from_data_round_trips_through_to_json() -> None:
    """A stored document survives the model unchanged in the keys it declares"""
    instance = CmdbRackMount.from_data(_mount_data())
    result = CmdbRackMount.to_json(instance)

    for key in ('public_id', 'rack_id', 'object_id', 'area', 'start_slot', 'height', 'author_id'):
        assert result[key] == _mount_data()[key]


def test_from_data_defaults_the_creation_time() -> None:
    """A document without a creation time gets one rather than storing None"""
    instance = CmdbRackMount.from_data(_mount_data())

    assert isinstance(instance.creation_time, datetime)


def test_from_data_parses_string_timestamps() -> None:
    """A JSON round trip carries the timestamps as strings"""
    instance = CmdbRackMount.from_data(_mount_data(
        creation_time='2026-08-04T10:00:00+00:00',
        last_edit_time='2026-08-04T11:00:00+00:00',
    ))

    assert instance.creation_time.year == 2026
    assert instance.last_edit_time.hour == 11


def test_from_data_keeps_a_datetime_untouched() -> None:
    """A value already parsed by pymongo is not re-parsed"""
    stamp = datetime(2026, 8, 4, tzinfo=timezone.utc)

    assert CmdbRackMount.from_data(_mount_data(creation_time=stamp)).creation_time == stamp


def test_from_data_raises_on_unusable_data() -> None:
    """A malformed timestamp surfaces as the model's own error, not a bare ValueError"""
    with pytest.raises(CmdbRackMountInitFromDataError):
        CmdbRackMount.from_data(_mount_data(creation_time='not-a-date'))

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   is_placed                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('area', [a.value for a in RackArea if a != RackArea.UNASSIGNED])
def test_is_placed_true_for_every_real_area(area: str) -> None:
    """Anything but the unassigned bucket is a placement"""
    assert CmdbRackMount.from_data(_mount_data(area=area)).is_placed() is True


def test_is_placed_false_in_the_unassigned_bucket() -> None:
    """The unassigned bucket is membership without placement"""
    assert CmdbRackMount.from_data(_mount_data(area=RackArea.UNASSIGNED.value)).is_placed() is False

# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_occupied_slots                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_occupied_slots_span_downward_from_the_anchor() -> None:
    """
    A 3U mount anchored at slot 10 occupies 10, 9 and 8

    Slot 1 is the bottom of the rack and a mount grows toward it, so the start slot is the mount's
    topmost U - not its lowest.
    """
    instance = CmdbRackMount.from_data(_mount_data(start_slot=10, height=3))

    assert sorted(instance.get_occupied_slots()) == [8, 9, 10]


@pytest.mark.parametrize('area', [RackArea.LEFT.value, RackArea.RIGHT.value, RackArea.UNASSIGNED.value])
def test_occupied_slots_are_empty_outside_the_main_areas(area: str) -> None:
    """Side and unassigned mounts occupy no slots even when they carry a height hint"""
    instance = CmdbRackMount.from_data(_mount_data(area=area, start_slot=10, height=3))

    assert instance.get_occupied_slots() == set()


@pytest.mark.parametrize('start_slot, height', [(None, 3), (10, None), (None, None)], ids=str)
def test_occupied_slots_are_empty_without_usable_geometry(start_slot: Any, height: Any) -> None:
    """A drifted main-area mount occupies nothing rather than raising"""
    instance = CmdbRackMount.from_data(_mount_data(start_slot=start_slot, height=height))

    assert instance.get_occupied_slots() == set()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    RackArea                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_area_groups_partition_the_enum() -> None:
    """Every area is either a main area, a side area or the unassigned bucket - no member is orphaned"""
    grouped = RackArea.get_main_areas() | RackArea.get_side_areas() | {RackArea.UNASSIGNED}

    assert grouped == set(RackArea)


def test_ordered_areas_are_the_sides_plus_unassigned() -> None:
    """Exactly the areas with no geometry to sort by carry an explicit order"""
    assert RackArea.get_ordered_areas() == RackArea.get_side_areas() | {RackArea.UNASSIGNED}


def test_main_areas_are_not_ordered() -> None:
    """A main-area mount is ordered by its slots, so it needs no position"""
    assert not RackArea.get_main_areas() & RackArea.get_ordered_areas()


@pytest.mark.parametrize('area, expected', [
    (RackArea.FRONT, {RackArea.FRONT, RackArea.FULL_DEPTH}),
    (RackArea.BACK, {RackArea.BACK, RackArea.FULL_DEPTH}),
    (RackArea.FULL_DEPTH, {RackArea.FRONT, RackArea.BACK, RackArea.FULL_DEPTH}),
    (RackArea.LEFT, set()),
    (RackArea.RIGHT, set()),
    (RackArea.UNASSIGNED, set()),
], ids=str)
def test_conflicting_areas(area: RackArea, expected: set) -> None:
    """
    Pins which areas compete for the same U range

    The asymmetry matters: front and back are independent of each other, but a full-depth mount
    occupies the same range in both, so it competes with everything.
    """
    assert RackArea.get_conflicting_areas(area) == expected


def test_document_keys_are_pinned() -> None:
    """The document keys are stored data and a wire contract"""
    assert RackMountKey.RACK_ID.value == 'rack_id'
    assert RackMountKey.OBJECT_ID.value == 'object_id'
    assert RackMountKey.AREA.value == 'area'
    assert RackMountKey.START_SLOT.value == 'start_slot'
    assert RackMountKey.HEIGHT.value == 'height'
    assert RackMountKey.POSITION.value == 'position'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                error wrapping                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_an_unusable_public_id_raises_the_models_init_error() -> None:
    """A CmdbDAO needs an int public_id; the failure is the model's own error type"""
    with pytest.raises(CmdbRackMountInitError):
        CmdbRackMount(
            public_id='not-an-int', rack_id=RACK_ID, object_id=OBJECT_ID, area=RackArea.FRONT.value,
        )


def test_a_broken_instance_raises_the_models_to_json_error() -> None:
    """Serialising an instance missing its identity is reported as a model error, not an AttributeError"""
    instance = CmdbRackMount.from_data(_mount_data())
    del instance.public_id

    with pytest.raises(CmdbRackMountToJsonError):
        CmdbRackMount.to_json(instance)
