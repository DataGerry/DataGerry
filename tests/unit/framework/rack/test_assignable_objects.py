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
Unit tests for cmdb.framework.rack.assignable_objects

Pure, no database. One positive marker and two exclusions decide assignability: the type must declare a
location field, a RACK-marked type is never mountable, and an object already in THIS rack is out. The tests
pin that the rules are APPENDED behind the caller's own ?filter= rather than merged into it - a caller must
not be able to name the same key and widen the result - that an empty location-field list means nothing is
assignable rather than everything, and that a picker row carries the mount-row keys plus the rack hint
"""
from typing import Any

import pytest

from cmdb.framework.rack.rack_constants import RackOverviewKey
from cmdb.framework.rack.assignable_objects import (
    append_criteria_to_filter,
    build_assignable_criteria,
    build_assignable_row,
    build_assignable_rows,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACK_TYPE_ID: int = 9551
TYPE_ID: int = 70
OTHER_TYPE_ID: int = 71
OBJECT_ID: int = 800
OTHER_OBJECT_ID: int = 801
RACK_ID: int = 500

TYPE_ID_KEY: str = 'type_id'
PUBLIC_ID_KEY: str = 'public_id'
MATCH: str = '$match'
IN: str = '$in'
NIN: str = '$nin'

SERVER_META: dict[str, Any] = {'type_label': 'Server', 'type_icon': 'fa-server', 'type_color': '#4b9e46'}

LOCATION_TYPE_IDS: list[int] = [TYPE_ID, OTHER_TYPE_ID, RACK_TYPE_ID]

# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_assignable_criteria                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_three_rules_are_one_in_and_two_nins() -> None:
    """The type marker is positive, the Rack type and this rack's members are taken away from it"""
    criteria = build_assignable_criteria(LOCATION_TYPE_IDS, [RACK_TYPE_ID], [OBJECT_ID, OTHER_OBJECT_ID])

    assert criteria[TYPE_ID_KEY] == {IN: LOCATION_TYPE_IDS, NIN: [RACK_TYPE_ID]}
    assert criteria[PUBLIC_ID_KEY] == {NIN: [OBJECT_ID, OTHER_OBJECT_ID]}


def test_the_rack_type_is_excluded_although_it_carries_a_location_field() -> None:
    """
    The two type rules are not redundant

    A Rack can be placed in the location tree, so its own type declares a location field and passes the
    positive marker. Racks still do not nest, which is what the second half is for.
    """
    criteria = build_assignable_criteria([TYPE_ID, RACK_TYPE_ID], [RACK_TYPE_ID], [])

    assert RACK_TYPE_ID in criteria[TYPE_ID_KEY][IN]
    assert criteria[TYPE_ID_KEY][NIN] == [RACK_TYPE_ID]


def test_no_type_with_a_location_field_means_nothing_is_assignable() -> None:
    """
    An empty '$in' matching nothing is the right answer, not a rule to skip

    A member is mirrored into the location tree through its own location field, so an installation where
    no type declares one has nothing that may be mounted at all.
    """
    criteria = build_assignable_criteria([], [RACK_TYPE_ID], [])

    assert criteria[TYPE_ID_KEY][IN] == []


def test_an_empty_exclusion_list_is_left_out_entirely() -> None:
    """A '$nin' against an empty list excludes nothing, so it is noise in the pipeline"""
    assert build_assignable_criteria([TYPE_ID], [], [OBJECT_ID]) == {
        TYPE_ID_KEY: {IN: [TYPE_ID]},
        PUBLIC_ID_KEY: {NIN: [OBJECT_ID]},
    }
    assert build_assignable_criteria([TYPE_ID], [RACK_TYPE_ID], []) == {
        TYPE_ID_KEY: {IN: [TYPE_ID], NIN: [RACK_TYPE_ID]},
    }


def test_an_empty_rack_excludes_no_object() -> None:
    """A rack holding nothing hides nothing - every object of a mountable type is offered"""
    criteria = build_assignable_criteria(LOCATION_TYPE_IDS, [RACK_TYPE_ID], [])

    assert PUBLIC_ID_KEY not in criteria

# -------------------------------------------------------------------------------------------------------------------- #
#                                          append_criteria_to_filter                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_dict_filter_becomes_a_match_stage_the_rules_follow() -> None:
    """The caller's filter narrows the candidates and the rules narrow them further"""
    criteria = build_assignable_criteria(LOCATION_TYPE_IDS, [RACK_TYPE_ID], [])

    pipeline = append_criteria_to_filter({TYPE_ID_KEY: TYPE_ID}, criteria)

    assert pipeline == [{MATCH: {TYPE_ID_KEY: TYPE_ID}}, {MATCH: criteria}]


def test_a_pipeline_filter_keeps_its_stages_and_gains_one() -> None:
    """A caller who already sent stages gets the rules appended after them"""
    stages: list[dict[str, Any]] = [{MATCH: {TYPE_ID_KEY: TYPE_ID}}, {'$sort': {PUBLIC_ID_KEY: 1}}]
    criteria = build_assignable_criteria(LOCATION_TYPE_IDS, [], [OBJECT_ID])

    pipeline = append_criteria_to_filter(stages, criteria)

    assert pipeline == [*stages, {MATCH: criteria}]


def test_the_callers_pipeline_is_not_mutated() -> None:
    """The parsed request filter is shared state - appending to it in place would leak across the request"""
    stages: list[dict[str, Any]] = [{MATCH: {TYPE_ID_KEY: TYPE_ID}}]

    append_criteria_to_filter(stages, build_assignable_criteria(LOCATION_TYPE_IDS, [RACK_TYPE_ID], []))

    assert stages == [{MATCH: {TYPE_ID_KEY: TYPE_ID}}]


def test_a_caller_cannot_overwrite_a_rule_by_naming_the_same_key() -> None:
    """
    Appending rather than merging is what makes the rules unbypassable

    A filter asking for exactly the Rack type still ends up behind the exclusion of that type, so the
    two stages contradict and the result is empty - not 'the caller wins'.
    """
    criteria = build_assignable_criteria(LOCATION_TYPE_IDS, [RACK_TYPE_ID], [])

    pipeline = append_criteria_to_filter({TYPE_ID_KEY: RACK_TYPE_ID}, criteria)

    assert pipeline[0] == {MATCH: {TYPE_ID_KEY: RACK_TYPE_ID}}
    assert pipeline[-1][MATCH][TYPE_ID_KEY][NIN] == [RACK_TYPE_ID]


@pytest.mark.parametrize('request_filter', [None, {}, []], ids=['none', 'empty-dict', 'empty-list'])
def test_no_filter_yields_the_rules_alone(request_filter: Any) -> None:
    """An unfiltered request still gets every rule"""
    criteria = build_assignable_criteria(LOCATION_TYPE_IDS, [RACK_TYPE_ID], [])

    assert append_criteria_to_filter(request_filter, criteria) == [{MATCH: criteria}]


def test_no_filter_and_no_criteria_yields_an_empty_pipeline() -> None:
    """Nothing to narrow by means no stages, not a stage matching everything"""
    assert append_criteria_to_filter(None, {}) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                             the picker rows                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_row_carries_the_mount_row_keys_plus_the_rack_hint() -> None:
    """One shape for 'an object I could mount' and 'an object I have mounted', plus where it is now"""
    row = build_assignable_row(
        {PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID},
        {OBJECT_ID: 'server-01'},
        {TYPE_ID: SERVER_META},
        {},
    )

    assert row == {
        RackOverviewKey.PUBLIC_ID.value: OBJECT_ID,
        RackOverviewKey.SUMMARY_LINE.value: 'server-01',
        RackOverviewKey.TYPE_ID.value: TYPE_ID,
        RackOverviewKey.TYPE_LABEL.value: 'Server',
        RackOverviewKey.TYPE_ICON.value: 'fa-server',
        RackOverviewKey.TYPE_COLOR.value: '#4b9e46',
        RackOverviewKey.ASSIGNED_RACK_ID.value: None,
        RackOverviewKey.ASSIGNED_RACK_NAME.value: None,
    }


def test_a_candidate_in_another_rack_names_that_rack() -> None:
    """The hint is what lets the frontend say 'this will be moved out of Rack X' before it happens"""
    row = build_assignable_row(
        {PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID},
        {},
        {},
        {OBJECT_ID: {
            RackOverviewKey.PUBLIC_ID.value: RACK_ID,
            RackOverviewKey.DISPLAY_NAME.value: 'Rack A',
        }},
    )

    assert row[RackOverviewKey.ASSIGNED_RACK_ID.value] == RACK_ID
    assert row[RackOverviewKey.ASSIGNED_RACK_NAME.value] == 'Rack A'


def test_a_free_candidate_carries_both_hint_keys_as_null() -> None:
    """The keys are always present, so the frontend reads one shape rather than two"""
    row = build_assignable_row(
        {PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID},
        {},
        {},
        {OTHER_OBJECT_ID: {
            RackOverviewKey.PUBLIC_ID.value: RACK_ID,
            RackOverviewKey.DISPLAY_NAME.value: 'Rack A',
        }},
    )

    assert row[RackOverviewKey.ASSIGNED_RACK_ID.value] is None
    assert row[RackOverviewKey.ASSIGNED_RACK_NAME.value] is None


def test_a_candidate_whose_type_did_not_resolve_keeps_its_row() -> None:
    """It is still assignable, and hiding it would offer no way to notice the broken type"""
    row = build_assignable_row({PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID}, {}, {}, {})

    assert row[RackOverviewKey.PUBLIC_ID.value] == OBJECT_ID
    assert row[RackOverviewKey.SUMMARY_LINE.value] is None
    assert row[RackOverviewKey.TYPE_LABEL.value] is None
    assert row[RackOverviewKey.TYPE_COLOR.value] is None


def test_rows_keep_the_order_the_database_returned() -> None:
    """The order is the caller's ?sort= / ?order=, applied by the aggregation - not re-sorted here"""
    docs = [
        {PUBLIC_ID_KEY: OTHER_OBJECT_ID, TYPE_ID_KEY: TYPE_ID},
        {PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID},
    ]

    rows = build_assignable_rows(docs, {}, {}, {})

    assert [row[RackOverviewKey.PUBLIC_ID.value] for row in rows] == [OTHER_OBJECT_ID, OBJECT_ID]


def test_an_empty_page_yields_no_rows() -> None:
    """A rack whose every candidate is taken renders an empty picker without a special case"""
    assert build_assignable_rows([], {}, {}, {}) == []
