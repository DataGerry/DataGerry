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
Unit tests for cmdb.framework.rack.overview

Pure, no database. **A mount is anchored at its start_slot and extends DOWNWARD** - slot 1 is the bottom of
the rack, so a 3U mount at 25 occupies 25, 24 and 23. Covers the per-mount row projection (geometry plus the
mounted object's summary line and its type's label, icon and colour), the per-area bucketing and its ordering,
the types legend and its tally, and the assembled document.

Which slots are FREE is deliberately not computed here - the frontend draws the rack from the buckets, and
whether a specific placement is allowed is answered by the mount pre-validation route
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKind
from cmdb.models.special_type_model.rack_constants import RackField
from cmdb.framework.rack.rack_constants import RackOverviewKey
from cmdb.framework.rack.overview import (
    build_area_buckets,
    build_mount_row,
    build_occupants_legend,
    build_rack_header,
    build_rack_overview,
    build_types_legend,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 700
RACK_HEIGHT: int = 12
DISPLAY_NAME: str = 'rack-a'

OBJECT_ID: int = 800
OTHER_OBJECT_ID: int = 801
THIRD_OBJECT_ID: int = 802
TYPE_ID: int = 70
OTHER_TYPE_ID: int = 71

SERVER_META: dict[str, Any] = {'type_label': 'Server', 'type_icon': 'fa-server', 'type_color': '#4b9e46'}
SWITCH_META: dict[str, Any] = {'type_label': 'Switch', 'type_icon': 'fa-network', 'type_color': '#2196f3'}


def _mount(public_id: int, area: str, start_slot: Any = None, height: Any = None,
           position: Any = None, object_id: int = OBJECT_ID) -> dict[str, Any]:
    """Builds a stored mount document"""
    return {
        'public_id': public_id,
        'rack_id': RACK_ID,
        'object_id': object_id,
        'area': area,
        'start_slot': start_slot,
        'height': height,
        'position': position,
    }


def _rack(name: Any = DISPLAY_NAME, number: Any = 'R-1', notes: Any = 'a note') -> dict[str, Any]:
    """Builds a Rack CmdbObject document"""
    return {
        'public_id': RACK_ID,
        'fields': [
            {'name': RackField.NAME.value, 'value': name, 'type': 'text'},
            {'name': RackField.NUMBER.value, 'value': number, 'type': 'text'},
            {'name': RackField.NOTES.value, 'value': notes, 'type': 'textarea'},
        ],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                               build_mount_row                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_row_carries_the_geometry_and_the_resolved_object() -> None:
    """One row is everything needed to draw one mounted object"""
    row = build_mount_row(
        _mount(1, RackArea.FRONT.value, 3, 2),
        {OBJECT_ID: 'server-01'},
        {TYPE_ID: {'type_label': 'Server', 'type_icon': 'fa-server', 'type_color': '#4b9e46'}},
        {OBJECT_ID: TYPE_ID},
    )

    assert row[RackOverviewKey.MOUNT_ID.value] == 1
    assert row[RackOverviewKey.START_SLOT.value] == 3
    assert row[RackOverviewKey.SUMMARY_LINE.value] == 'server-01'
    assert row[RackOverviewKey.TYPE_LABEL.value] == 'Server'
    assert row[RackOverviewKey.TYPE_ICON.value] == 'fa-server'
    assert row[RackOverviewKey.TYPE_COLOR.value] == '#4b9e46'


def test_an_unresolvable_object_keeps_its_slots() -> None:
    """
    A mount whose object no longer resolves is reported without a summary line, not dropped

    Leaving a hole in the layout would misrepresent the rack as having free space it does not have.
    """
    row = build_mount_row(_mount(1, RackArea.FRONT.value, 3, 2), {}, {}, {})

    assert row[RackOverviewKey.START_SLOT.value] == 3
    assert row[RackOverviewKey.SUMMARY_LINE.value] is None
    assert row[RackOverviewKey.TYPE_LABEL.value] is None
    assert row[RackOverviewKey.TYPE_COLOR.value] is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_area_buckets                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_every_area_is_present_even_when_empty() -> None:
    """An empty rack renders without special cases in the frontend"""
    buckets = build_area_buckets([], {}, {}, {})

    assert set(buckets) == {area.value for area in RackArea}
    assert all(rows == [] for rows in buckets.values())


def test_mounts_land_in_their_own_bucket() -> None:
    """Grouping by area is what the rack view draws from"""
    mounts = [_mount(1, RackArea.FRONT.value, 1, 1), _mount(2, RackArea.LEFT.value, position=0)]

    buckets = build_area_buckets(mounts, {}, {}, {})

    assert [r[RackOverviewKey.MOUNT_ID.value] for r in buckets[RackArea.FRONT.value]] == [1]
    assert [r[RackOverviewKey.MOUNT_ID.value] for r in buckets[RackArea.LEFT.value]] == [2]


def test_a_main_area_bucket_is_ordered_by_slot() -> None:
    """A main area has no position index - its slots are its order"""
    mounts = [_mount(1, RackArea.FRONT.value, 9, 1), _mount(2, RackArea.FRONT.value, 2, 1)]

    rows = build_area_buckets(mounts, {}, {}, {})[RackArea.FRONT.value]

    assert [r[RackOverviewKey.START_SLOT.value] for r in rows] == [2, 9]


def test_an_ordered_bucket_is_ordered_by_position() -> None:
    """A side list has no geometry, so the explicit index decides"""
    mounts = [_mount(1, RackArea.LEFT.value, position=3), _mount(2, RackArea.LEFT.value, position=1)]

    rows = build_area_buckets(mounts, {}, {}, {})[RackArea.LEFT.value]

    assert [r[RackOverviewKey.POSITION.value] for r in rows] == [1, 3]


def test_rows_without_an_order_value_fall_back_to_the_mount_id() -> None:
    """A stable order for rows that predate a position rather than an arbitrary one"""
    mounts = [_mount(9, RackArea.LEFT.value), _mount(4, RackArea.LEFT.value)]

    rows = build_area_buckets(mounts, {}, {}, {})[RackArea.LEFT.value]

    assert [r[RackOverviewKey.MOUNT_ID.value] for r in rows] == [4, 9]


def test_a_mount_with_an_unknown_area_is_dropped() -> None:
    """It cannot be drawn anywhere, so it is skipped rather than crashing the whole overview"""
    buckets = build_area_buckets([{'public_id': 1, 'area': 'GARBAGE'}], {}, {}, {})

    assert all(rows == [] for rows in buckets.values())

# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_types_legend                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_legend_has_one_entry_per_distinct_type() -> None:
    """The legend is a key to the colours in the drawing, so a type appears once no matter how often it is held"""
    mounts = [
        _mount(1, RackArea.FRONT.value, 4, 1),
        _mount(2, RackArea.FRONT.value, 6, 1, object_id=OTHER_OBJECT_ID),
        _mount(3, RackArea.LEFT.value, position=0, object_id=THIRD_OBJECT_ID),
    ]

    legend = build_types_legend(
        mounts,
        {TYPE_ID: SERVER_META, OTHER_TYPE_ID: SWITCH_META},
        {OBJECT_ID: TYPE_ID, OTHER_OBJECT_ID: TYPE_ID, THIRD_OBJECT_ID: OTHER_TYPE_ID},
    )

    assert [entry[RackOverviewKey.TYPE_ID.value] for entry in legend] == [TYPE_ID, OTHER_TYPE_ID]


def test_a_legend_entry_carries_the_label_icon_colour_and_count() -> None:
    """Everything a legend row renders, without a follow-up request per type"""
    mounts = [
        _mount(1, RackArea.FRONT.value, 4, 1),
        _mount(2, RackArea.FRONT.value, 6, 1, object_id=OTHER_OBJECT_ID),
    ]

    entry = build_types_legend(
        mounts, {TYPE_ID: SERVER_META}, {OBJECT_ID: TYPE_ID, OTHER_OBJECT_ID: TYPE_ID},
    )[0]

    assert entry[RackOverviewKey.TYPE_LABEL.value] == 'Server'
    assert entry[RackOverviewKey.TYPE_ICON.value] == 'fa-server'
    assert entry[RackOverviewKey.TYPE_COLOR.value] == '#4b9e46'
    assert entry[RackOverviewKey.COUNT.value] == 2


def test_the_legend_counts_unplaced_members() -> None:
    """It follows membership, not placement - an unplaced member is in the rack"""
    mounts = [_mount(1, RackArea.UNASSIGNED.value, position=0)]

    legend = build_types_legend(mounts, {TYPE_ID: SERVER_META}, {OBJECT_ID: TYPE_ID})

    assert legend[0][RackOverviewKey.COUNT.value] == 1


def test_an_unresolvable_object_is_tallied_nowhere() -> None:
    """
    A mount whose object no longer resolves has no type

    Its row is still drawn, so the legend's counts can sum to less than the rack's total mount count.
    """
    mounts = [_mount(1, RackArea.FRONT.value, 4, 1), _mount(2, RackArea.FRONT.value, 6, 1,
                                                            object_id=OTHER_OBJECT_ID)]

    legend = build_types_legend(mounts, {TYPE_ID: SERVER_META}, {OBJECT_ID: TYPE_ID})

    assert len(legend) == 1
    assert legend[0][RackOverviewKey.COUNT.value] == 1


def test_the_legend_is_empty_when_nothing_resolves() -> None:
    """An empty list rather than nothing, so the frontend renders an empty rack without a special case"""
    assert build_types_legend([], {}, {}) == []
    assert build_types_legend([_mount(1, RackArea.FRONT.value, 4, 1)], {}, {}) == []


def test_the_legend_is_ordered_by_label() -> None:
    """A legend is read top to bottom, so it is alphabetical rather than insertion-ordered"""
    mounts = [_mount(1, RackArea.FRONT.value, 4, 1), _mount(2, RackArea.FRONT.value, 6, 1,
                                                            object_id=OTHER_OBJECT_ID)]

    legend = build_types_legend(
        mounts,
        {TYPE_ID: SWITCH_META, OTHER_TYPE_ID: SERVER_META},
        {OBJECT_ID: TYPE_ID, OTHER_OBJECT_ID: OTHER_TYPE_ID},
    )

    assert [entry[RackOverviewKey.TYPE_LABEL.value] for entry in legend] == ['Server', 'Switch']


def test_types_sharing_a_label_are_ordered_by_id() -> None:
    """Without the tie-break their order would wobble between two reads of the same rack"""
    mounts = [_mount(1, RackArea.FRONT.value, 4, 1), _mount(2, RackArea.FRONT.value, 6, 1,
                                                            object_id=OTHER_OBJECT_ID)]

    legend = build_types_legend(
        mounts,
        {TYPE_ID: SERVER_META, OTHER_TYPE_ID: dict(SERVER_META)},
        {OBJECT_ID: OTHER_TYPE_ID, OTHER_OBJECT_ID: TYPE_ID},
    )

    assert [entry[RackOverviewKey.TYPE_ID.value] for entry in legend] == [TYPE_ID, OTHER_TYPE_ID]


def test_a_type_whose_document_vanished_keeps_its_entry() -> None:
    """
    Dropping it would lose a legend row for objects that are visibly drawn in the rack

    A null label sorts to the front rather than breaking the comparison against the resolved labels.
    """
    mounts = [_mount(1, RackArea.FRONT.value, 4, 1), _mount(2, RackArea.FRONT.value, 6, 1,
                                                            object_id=OTHER_OBJECT_ID)]

    legend = build_types_legend(
        mounts,
        {TYPE_ID: SERVER_META},
        {OBJECT_ID: TYPE_ID, OTHER_OBJECT_ID: OTHER_TYPE_ID},
    )

    assert [entry[RackOverviewKey.TYPE_ID.value] for entry in legend] == [OTHER_TYPE_ID, TYPE_ID]
    assert legend[0][RackOverviewKey.TYPE_LABEL.value] is None
    assert legend[0][RackOverviewKey.COUNT.value] == 1

# -------------------------------------------------------------------------------------------------------------------- #
#                                               the whole overview                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_header_carries_the_racks_own_fields() -> None:
    """The frontend draws the rack's identity from here, not from a second request"""
    header = build_rack_header(_rack(), RACK_HEIGHT, DISPLAY_NAME)

    assert header[RackOverviewKey.PUBLIC_ID.value] == RACK_ID
    assert header[RackOverviewKey.DISPLAY_NAME.value] == DISPLAY_NAME
    assert header[RackOverviewKey.NAME.value] == DISPLAY_NAME
    assert header[RackOverviewKey.NUMBER.value] == 'R-1'
    assert header[RackOverviewKey.NOTES.value] == 'a note'
    assert header[RackOverviewKey.HEIGHT.value] == RACK_HEIGHT


def test_the_overview_bundles_header_legends_buckets_and_count() -> None:
    """One document, five parts"""
    mounts = [
        _mount(1, RackArea.FRONT.value, 2, 2),
        _mount(2, RackArea.UNASSIGNED.value, position=0, object_id=OTHER_OBJECT_ID),
    ]

    overview = build_rack_overview(
        _rack(), RACK_HEIGHT, DISPLAY_NAME, mounts,
        {OBJECT_ID: 'server-01'},
        {TYPE_ID: SERVER_META},
        {OBJECT_ID: TYPE_ID},
    )

    assert set(overview) == {
        RackOverviewKey.RACK.value,
        RackOverviewKey.TYPES_LEGEND.value,
        RackOverviewKey.OCCUPANTS_LEGEND.value,
        RackOverviewKey.AREAS.value,
        RackOverviewKey.TOTAL_MOUNTS.value,
    }
    assert overview[RackOverviewKey.TOTAL_MOUNTS.value] == 2


def test_the_count_includes_unplaced_members() -> None:
    """Membership is membership, placed or not"""
    mounts = [_mount(1, RackArea.UNASSIGNED.value, position=0)]

    overview = build_rack_overview(_rack(), RACK_HEIGHT, DISPLAY_NAME, mounts, {}, {}, {})

    assert overview[RackOverviewKey.TOTAL_MOUNTS.value] == 1


def test_the_legend_reflects_the_whole_rack_not_one_area() -> None:
    """The legend is per rack, so a member of any area contributes to it"""
    mounts = [
        _mount(1, RackArea.FRONT.value, 2, 2),
        _mount(2, RackArea.UNASSIGNED.value, position=0, object_id=OTHER_OBJECT_ID),
    ]

    overview = build_rack_overview(
        _rack(), RACK_HEIGHT, DISPLAY_NAME, mounts,
        {},
        {TYPE_ID: SERVER_META},
        {OBJECT_ID: TYPE_ID, OTHER_OBJECT_ID: TYPE_ID},
    )

    legend = overview[RackOverviewKey.TYPES_LEGEND.value]

    assert len(legend) == 1
    assert legend[0][RackOverviewKey.COUNT.value] == 2


def test_the_count_excludes_a_mount_with_an_unknown_area() -> None:
    """A row that could not be bucketed is not counted as drawable either"""
    overview = build_rack_overview(
        _rack(), RACK_HEIGHT, DISPLAY_NAME, [{'public_id': 1, 'area': 'GARBAGE'}], {}, {}, {},
    )

    assert overview[RackOverviewKey.TOTAL_MOUNTS.value] == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the row kinds on the overview                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def _occupant(public_id: int, kind: str, area: str = RackArea.FRONT.value, **extra: Any) -> dict[str, Any]:
    """
    Builds a stored occupant row

    It OMITS object_id, the way the write path stores one - which is also what the projection has to
    tolerate without producing a hole in the layout.
    """
    row: dict[str, Any] = {
        'public_id': public_id,
        'rack_id': RACK_ID,
        'kind': kind,
        'area': area,
        'start_slot': 20,
        'height': 2,
        'position': None,
    }
    row.update(extra)

    return row


def test_a_mount_row_says_it_is_a_mount() -> None:
    """The grid switches on one key rather than guessing from which fields are null"""
    row = build_mount_row(_mount(900, RackArea.FRONT.value, 10, 2), {}, {}, {})

    assert row[RackOverviewKey.KIND.value] == RackMountKind.MOUNT.value


def test_a_row_written_before_the_kinds_reads_as_a_mount() -> None:
    """A stored row with no kind is a mount, which is what it was when it was written"""
    stored = _mount(900, RackArea.FRONT.value, 10, 2)
    stored.pop('kind', None)

    assert build_mount_row(stored, {}, {}, {})[RackOverviewKey.KIND.value] == RackMountKind.MOUNT.value


@pytest.mark.parametrize('kind', [RackMountKind.RESERVATION.value, RackMountKind.BLOCKER.value])
def test_an_occupant_row_keeps_its_slots_and_says_what_it_is(kind: str) -> None:
    """
    It occupies the rack, so it is drawn - with no object to name

    A hole in the layout would be a worse lie than an unnamed block, which is the same reasoning that
    keeps a mount whose object vanished.
    """
    row = build_mount_row(_occupant(900, kind), {}, {}, {})

    assert row[RackOverviewKey.KIND.value] == kind
    assert row[RackOverviewKey.START_SLOT.value] == 20
    assert row[RackOverviewKey.HEIGHT.value] == 2
    assert row[RackOverviewKey.OBJECT_ID.value] is None
    assert row[RackOverviewKey.SUMMARY_LINE.value] is None
    assert row[RackOverviewKey.TYPE_ID.value] is None


def test_a_reservation_row_carries_its_dates_and_colour() -> None:
    """What the grid needs to draw a reservation differently from a blocker"""
    row = build_mount_row(_occupant(
        900, RackMountKind.RESERVATION.value,
        label='Reserved for DB cluster',
        start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 9, 30, tzinfo=timezone.utc),
        color='#4CAF50',
    ), {}, {}, {})

    assert row[RackOverviewKey.LABEL.value] == 'Reserved for DB cluster'
    assert row[RackOverviewKey.START_DATE.value] == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert row[RackOverviewKey.END_DATE.value] == datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert row[RackOverviewKey.COLOR.value] == '#4CAF50'


def test_every_row_carries_every_key() -> None:
    """
    One row shape whatever the row is

    A mount carries null reservation fields and an occupant null type metadata, so the frontend reads one
    shape rather than one per kind.
    """
    mount_row = build_mount_row(_mount(900, RackArea.FRONT.value, 10, 2), {}, {}, {})
    blocker_row = build_mount_row(_occupant(901, RackMountKind.BLOCKER.value), {}, {}, {})

    assert set(mount_row) == set(blocker_row)
    assert mount_row[RackOverviewKey.COLOR.value] is None
    assert mount_row[RackOverviewKey.START_DATE.value] is None
    assert blocker_row[RackOverviewKey.TYPE_LABEL.value] is None


def test_occupants_are_bucketed_and_sorted_beside_the_mounts() -> None:
    """They share the rack's geometry, so they share its ordering"""
    rows = build_area_buckets([
        _occupant(901, RackMountKind.BLOCKER.value),
        _mount(900, RackArea.FRONT.value, 10, 2),
    ], {}, {}, {})[RackArea.FRONT.value]

    assert [row[RackOverviewKey.MOUNT_ID.value] for row in rows] == [900, 901]


def test_an_unassigned_occupant_lands_in_the_bucket() -> None:
    """Where a shrink puts one - the 'still needs re-placing' list, mixed with the unplaced objects"""
    rows = build_area_buckets(
        [_occupant(901, RackMountKind.BLOCKER.value, area=RackArea.UNASSIGNED.value)], {}, {}, {},
    )[RackArea.UNASSIGNED.value]

    assert len(rows) == 1
    assert rows[0][RackOverviewKey.KIND.value] == RackMountKind.BLOCKER.value


def test_occupants_are_tallied_nowhere_in_the_legend() -> None:
    """
    The legend is types-only, and an occupant has no type

    An occupant tally is a different thing and belongs beside the legend, not inside it.
    """
    legend = build_types_legend([
        _mount(900, RackArea.FRONT.value, 10, 2),
        _occupant(901, RackMountKind.BLOCKER.value),
        _occupant(902, RackMountKind.RESERVATION.value),
    ], {TYPE_ID: SERVER_META}, {OBJECT_ID: TYPE_ID})

    assert len(legend) == 1
    assert legend[0][RackOverviewKey.COUNT.value] == 1


def test_the_total_counts_every_row_including_occupants() -> None:
    """
    They occupy the rack the same way a mount does

    Which is why the total can exceed the sum of the legend's counts - the legend tallies only the rows
    that name a resolvable object.
    """
    overview = build_rack_overview(
        {'public_id': RACK_ID}, RACK_HEIGHT, DISPLAY_NAME,
        [
            _mount(900, RackArea.FRONT.value, 10, 2),
            _occupant(901, RackMountKind.BLOCKER.value),
            _occupant(902, RackMountKind.RESERVATION.value, area=RackArea.BACK.value),
        ],
        {}, {TYPE_ID: SERVER_META}, {OBJECT_ID: TYPE_ID},
    )

    assert overview[RackOverviewKey.TOTAL_MOUNTS.value] == 3
    assert sum(entry[RackOverviewKey.COUNT.value]
               for entry in overview[RackOverviewKey.TYPES_LEGEND.value]) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the occupants legend                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_occupants_legend_tallies_each_kind() -> None:
    """The counterpart of the types legend for the rows that have no type"""
    legend = build_occupants_legend([
        _occupant(901, RackMountKind.BLOCKER.value),
        _occupant(902, RackMountKind.RESERVATION.value),
        _occupant(903, RackMountKind.RESERVATION.value, area=RackArea.BACK.value),
    ])

    assert legend == [
        {RackOverviewKey.KIND.value: RackMountKind.BLOCKER.value,
         RackOverviewKey.COUNT.value: 1, RackOverviewKey.SLOTS.value: 2},
        {RackOverviewKey.KIND.value: RackMountKind.RESERVATION.value,
         RackOverviewKey.COUNT.value: 2, RackOverviewKey.SLOTS.value: 4},
    ]


def test_the_slots_are_the_u_actually_held() -> None:
    """A 3U reservation holds three slots, however many rows the rack has"""
    legend = build_occupants_legend([
        _occupant(901, RackMountKind.RESERVATION.value, start_slot=30, height=3),
    ])

    assert legend[0][RackOverviewKey.SLOTS.value] == 3


def test_a_full_depth_occupant_counts_its_u_range_once() -> None:
    """
    It blocks the front and the back, but it is 2U of rack height, not 4

    The question the tally answers is "how much of the rack is held", and a full-depth row holds one U
    range - it just holds it in both views.
    """
    legend = build_occupants_legend([
        _occupant(901, RackMountKind.BLOCKER.value, area=RackArea.FULL_DEPTH.value,
                  start_slot=20, height=2),
    ])

    assert legend[0][RackOverviewKey.SLOTS.value] == 2


def test_an_unassigned_occupant_counts_but_holds_nothing() -> None:
    """
    The two numbers answer different questions

    It is still one blocker the user has to deal with, which is what makes the unassigned bucket a to-do
    list - but it holds no slot until it is placed again.
    """
    legend = build_occupants_legend([
        _occupant(901, RackMountKind.BLOCKER.value, area=RackArea.UNASSIGNED.value,
                  start_slot=None, height=2),
    ])

    assert legend[0][RackOverviewKey.COUNT.value] == 1
    assert legend[0][RackOverviewKey.SLOTS.value] == 0


def test_mounts_are_not_in_the_occupants_legend() -> None:
    """It tallies the rows that hold space without being an object - a mount is tallied by its type"""
    assert build_occupants_legend([_mount(900, RackArea.FRONT.value, 10, 2)]) == []


def test_a_row_without_a_kind_is_not_an_occupant() -> None:
    """Which is right: a row written before the kinds existed is a mount"""
    stored = _mount(900, RackArea.FRONT.value, 10, 2)
    stored.pop('kind', None)

    assert build_occupants_legend([stored]) == []


def test_a_kind_the_rack_does_not_hold_is_left_out() -> None:
    """An ordinary rack renders no occupant legend at all rather than two zeroes"""
    legend = build_occupants_legend([_occupant(901, RackMountKind.BLOCKER.value)])

    assert [entry[RackOverviewKey.KIND.value] for entry in legend] == [RackMountKind.BLOCKER.value]


def test_an_empty_rack_yields_an_empty_occupants_legend() -> None:
    """[] rather than null, the same no-special-cases rule the buckets follow"""
    assert build_occupants_legend([]) == []


def test_the_two_legends_account_for_the_total_between_them() -> None:
    """
    Which is what this legend is for

    The types legend alone can not explain total_mounts, because it skips every row that names no
    resolvable object.
    """
    overview = build_rack_overview(
        {'public_id': RACK_ID}, RACK_HEIGHT, DISPLAY_NAME,
        [
            _mount(900, RackArea.FRONT.value, 10, 2),
            _occupant(901, RackMountKind.BLOCKER.value),
            _occupant(902, RackMountKind.RESERVATION.value, area=RackArea.BACK.value),
        ],
        {}, {TYPE_ID: SERVER_META}, {OBJECT_ID: TYPE_ID},
    )

    typed: int = sum(entry[RackOverviewKey.COUNT.value]
                     for entry in overview[RackOverviewKey.TYPES_LEGEND.value])
    occupants: int = sum(entry[RackOverviewKey.COUNT.value]
                         for entry in overview[RackOverviewKey.OCCUPANTS_LEGEND.value])

    assert typed + occupants == overview[RackOverviewKey.TOTAL_MOUNTS.value] == 3
