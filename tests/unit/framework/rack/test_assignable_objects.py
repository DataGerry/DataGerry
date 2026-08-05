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

Pure, no database. Two rules decide assignability and both are exclusions: an object of a RACK-marked type
is never mountable, and an object already held by a mount belongs to that rack. The tests pin that the
exclusions are APPENDED behind the caller's own ?filter= rather than merged into it - a caller must not be
able to name the same key and widen the result - and that a picker row carries exactly the keys a mount row
carries
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
OBJECT_ID: int = 800
OTHER_OBJECT_ID: int = 801

TYPE_ID_KEY: str = 'type_id'
PUBLIC_ID_KEY: str = 'public_id'
MATCH: str = '$match'
NIN: str = '$nin'

SERVER_META: dict[str, Any] = {'type_label': 'Server', 'type_icon': 'fa-server', 'type_color': '#4b9e46'}

# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_assignable_criteria                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_both_exclusions_are_expressed_as_a_nin() -> None:
    """A Rack is not mountable and a mounted object is taken - both are 'everything except these'"""
    criteria = build_assignable_criteria([RACK_TYPE_ID], [OBJECT_ID, OTHER_OBJECT_ID])

    assert criteria[TYPE_ID_KEY] == {NIN: [RACK_TYPE_ID]}
    assert criteria[PUBLIC_ID_KEY] == {NIN: [OBJECT_ID, OTHER_OBJECT_ID]}


def test_an_empty_exclusion_list_is_left_out_entirely() -> None:
    """A '$nin' against an empty list excludes nothing, so it is noise in the pipeline"""
    assert build_assignable_criteria([], [OBJECT_ID]) == {PUBLIC_ID_KEY: {NIN: [OBJECT_ID]}}
    assert build_assignable_criteria([RACK_TYPE_ID], []) == {TYPE_ID_KEY: {NIN: [RACK_TYPE_ID]}}


def test_a_fresh_installation_needs_no_criteria_at_all() -> None:
    """No rack type and no mounts means every object is assignable"""
    assert build_assignable_criteria([], []) == {}

# -------------------------------------------------------------------------------------------------------------------- #
#                                          append_criteria_to_filter                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_dict_filter_becomes_a_match_stage_the_exclusions_follow() -> None:
    """The caller's filter narrows the candidates and the exclusions narrow them further"""
    criteria = build_assignable_criteria([RACK_TYPE_ID], [])

    pipeline = append_criteria_to_filter({TYPE_ID_KEY: TYPE_ID}, criteria)

    assert pipeline == [{MATCH: {TYPE_ID_KEY: TYPE_ID}}, {MATCH: criteria}]


def test_a_pipeline_filter_keeps_its_stages_and_gains_one() -> None:
    """A caller who already sent stages gets the exclusions appended after them"""
    stages: list[dict[str, Any]] = [{MATCH: {TYPE_ID_KEY: TYPE_ID}}, {'$sort': {PUBLIC_ID_KEY: 1}}]
    criteria = build_assignable_criteria([], [OBJECT_ID])

    pipeline = append_criteria_to_filter(stages, criteria)

    assert pipeline == [*stages, {MATCH: criteria}]


def test_the_callers_pipeline_is_not_mutated() -> None:
    """The parsed request filter is shared state - appending to it in place would leak across the request"""
    stages: list[dict[str, Any]] = [{MATCH: {TYPE_ID_KEY: TYPE_ID}}]

    append_criteria_to_filter(stages, build_assignable_criteria([RACK_TYPE_ID], []))

    assert stages == [{MATCH: {TYPE_ID_KEY: TYPE_ID}}]


def test_a_caller_cannot_overwrite_an_exclusion_by_naming_the_same_key() -> None:
    """
    Appending rather than merging is what makes the rules unbypassable

    A filter asking for exactly the Rack type still ends up behind the exclusion of that type, so the
    two stages contradict and the result is empty - not 'the caller wins'.
    """
    criteria = build_assignable_criteria([RACK_TYPE_ID], [])

    pipeline = append_criteria_to_filter({TYPE_ID_KEY: RACK_TYPE_ID}, criteria)

    assert pipeline[0] == {MATCH: {TYPE_ID_KEY: RACK_TYPE_ID}}
    assert pipeline[-1] == {MATCH: {TYPE_ID_KEY: {NIN: [RACK_TYPE_ID]}}}


@pytest.mark.parametrize('request_filter', [None, {}, []], ids=['none', 'empty-dict', 'empty-list'])
def test_no_filter_yields_the_exclusions_alone(request_filter: Any) -> None:
    """An unfiltered request still gets the two rules"""
    criteria = build_assignable_criteria([RACK_TYPE_ID], [])

    assert append_criteria_to_filter(request_filter, criteria) == [{MATCH: criteria}]


def test_no_filter_and_no_criteria_yields_an_empty_pipeline() -> None:
    """Nothing to narrow by means no stages, not a stage matching everything"""
    assert append_criteria_to_filter(None, {}) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                             the picker rows                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_row_carries_the_same_keys_a_mount_row_carries() -> None:
    """One shape for 'an object I could mount' and 'an object I have mounted'"""
    row = build_assignable_row(
        {PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID}, {OBJECT_ID: 'server-01'}, {TYPE_ID: SERVER_META},
    )

    assert row == {
        RackOverviewKey.PUBLIC_ID.value: OBJECT_ID,
        RackOverviewKey.SUMMARY_LINE.value: 'server-01',
        RackOverviewKey.TYPE_ID.value: TYPE_ID,
        RackOverviewKey.TYPE_LABEL.value: 'Server',
        RackOverviewKey.TYPE_ICON.value: 'fa-server',
        RackOverviewKey.TYPE_COLOR.value: '#4b9e46',
    }


def test_a_candidate_whose_type_did_not_resolve_keeps_its_row() -> None:
    """It is still assignable, and hiding it would offer no way to notice the broken type"""
    row = build_assignable_row({PUBLIC_ID_KEY: OBJECT_ID, TYPE_ID_KEY: TYPE_ID}, {}, {})

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

    rows = build_assignable_rows(docs, {}, {})

    assert [row[RackOverviewKey.PUBLIC_ID.value] for row in rows] == [OTHER_OBJECT_ID, OBJECT_ID]


def test_an_empty_page_yields_no_rows() -> None:
    """A rack whose every candidate is taken renders an empty picker without a special case"""
    assert build_assignable_rows([], {}, {}) == []
