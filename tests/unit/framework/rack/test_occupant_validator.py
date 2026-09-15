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
Unit tests for cmdb.framework.rack.occupant_validator

Pure, no database. The SHAPE rules of a rack row: which fields a MOUNT, a RESERVATION and a BLOCKER may
carry, and what makes a reservation's optional date range and colour usable.

The load-bearing assertion of the whole module is that **the dates are descriptive**: nothing here reads
the clock, so a reservation whose end date is long past is as valid, and blocks its slots as hard, as one
starting tomorrow. A test pins that explicitly, because "expired reservations stop blocking" is the
plausible-sounding rule this deliberately does not implement
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from cmdb.models.rack_model.rack_mount_constants import RackArea, RackMountKey, RackMountKind
from cmdb.framework.rack.occupant_validator import (
    area_blocker,
    coerce_kind,
    read_stored_kind,
    date_order_blocker,
    date_value_blockers,
    field_blockers,
    kind_change_blocker,
    shape_blockers,
    unknown_kind_blocker,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 800
COLOR: str = '#4CAF50'

MOUNT: str = RackMountKind.MOUNT.value
RESERVATION: str = RackMountKind.RESERVATION.value
BLOCKER: str = RackMountKind.BLOCKER.value

START: datetime = datetime(2026, 9, 1, tzinfo=timezone.utc)
END: datetime = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _candidate(**overrides: Any) -> dict[str, Any]:
    """A persisted row, as the routes build it"""
    candidate: dict[str, Any] = {
        RackMountKey.AREA.value: RackArea.FRONT.value,
        RackMountKey.START_DATE.value: None,
        RackMountKey.END_DATE.value: None,
    }
    candidate.update(overrides)

    return candidate

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  coerce_kind                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def test_an_absent_kind_means_mount() -> None:
    """Every client that predates the reservations keeps working, and so does every row they wrote"""
    assert coerce_kind(None) == MOUNT


@pytest.mark.parametrize('kind', [MOUNT, RESERVATION, BLOCKER])
def test_a_known_kind_is_kept(kind: str) -> None:
    """The three kinds a row may be"""
    assert coerce_kind(kind) == kind


@pytest.mark.parametrize('raw_kind', ['RESERVATON', 'mount', '', 42, True], ids=str)
def test_an_unknown_kind_is_not_defaulted(raw_kind: Any) -> None:
    """
    Guessing MOUNT for a misspelling would create the wrong kind of row silently

    Note 'mount' in lower case is refused too - the stored value is the enum's, so accepting a second
    spelling would put two different strings in the same field.
    """
    assert coerce_kind(raw_kind) is None
    assert unknown_kind_blocker(raw_kind) is not None


def test_a_valid_kind_has_no_blocker() -> None:
    """The guard is silent when there is nothing wrong"""
    assert unknown_kind_blocker(RESERVATION) is None
    assert unknown_kind_blocker(None) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                        field_blockers - per kind                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_mount_may_carry_an_object_id() -> None:
    """The ordinary case - nothing about a mount changed"""
    assert field_blockers(MOUNT, {RackMountKey.OBJECT_ID.value: OBJECT_ID}) == []


@pytest.mark.parametrize('kind', [RESERVATION, BLOCKER])
def test_an_occupant_may_not_carry_an_object_id(kind: str) -> None:
    """An occupant holds space; naming an object would make it a mount by another name"""
    blockers = field_blockers(kind, {RackMountKey.OBJECT_ID.value: OBJECT_ID})

    assert len(blockers) == 1
    assert 'object_id' in blockers[0]


@pytest.mark.parametrize('kind', [MOUNT, BLOCKER])
@pytest.mark.parametrize('key', [RackMountKey.START_DATE, RackMountKey.END_DATE, RackMountKey.COLOR])
def test_a_reservation_field_is_refused_on_another_kind(kind: str, key: RackMountKey) -> None:
    """
    Refused rather than dropped

    A client sending a colour on a blocker and getting a colourless blocker back would have no way to
    notice the field was never stored.
    """
    value: Any = COLOR if key == RackMountKey.COLOR else START
    blockers = field_blockers(kind, {key.value: value})

    assert len(blockers) == 1
    assert key.value in blockers[0]


def test_a_reservation_may_carry_all_three_of_its_fields() -> None:
    """Together, which is the common create"""
    assert field_blockers(RESERVATION, {
        RackMountKey.START_DATE.value: START,
        RackMountKey.END_DATE.value: END,
        RackMountKey.COLOR.value: COLOR,
    }) == []


def test_a_reservation_needs_none_of_its_fields() -> None:
    """All three are optional by decision - a bare reservation is a valid reservation"""
    assert field_blockers(RESERVATION, {}) == []


def test_a_label_is_allowed_on_every_kind() -> None:
    """It is the one descriptive field that is not reservation-specific"""
    for kind in (MOUNT, RESERVATION, BLOCKER):
        assert field_blockers(kind, {RackMountKey.LABEL.value: 'Metal frame'}) == []


def test_a_non_text_label_is_refused() -> None:
    """The label is rendered, so it has to be text"""
    assert field_blockers(BLOCKER, {RackMountKey.LABEL.value: 42}) != []


def test_every_reason_is_reported_at_once() -> None:
    """One corrected payload rather than one refusal per request"""
    blockers = field_blockers(BLOCKER, {
        RackMountKey.OBJECT_ID.value: OBJECT_ID,
        RackMountKey.START_DATE.value: START,
        RackMountKey.COLOR.value: COLOR,
    })

    # The object id, and the two reservation fields. The colour is well formed, so it is reported once
    # for not belonging on a blocker rather than twice
    assert len(blockers) == 3

# -------------------------------------------------------------------------------------------------------------------- #
#                                                the colour                                                            #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('color', ['#4CAF50', '#4caf50', '#000000', '#ffffff'])
def test_a_valid_hex_colour_is_accepted(color: str) -> None:
    """'#RRGGBB' in either casing"""
    assert field_blockers(RESERVATION, {RackMountKey.COLOR.value: color}) == []


@pytest.mark.parametrize('color', ['#4C5', '4CAF50', 'red', '#GGGGGG', '#4CAF5', '#4CAF500', 42], ids=str)
def test_a_malformed_colour_is_refused(color: Any) -> None:
    """One spelling only, so a frontend never has to guess how to render a stored colour"""
    blockers = field_blockers(RESERVATION, {RackMountKey.COLOR.value: color})

    assert len(blockers) == 1
    assert 'RRGGBB' in blockers[0]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the dates                                                            #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', ['2026-09-01', '2026-09-01T12:30:00Z', START], ids=str)
def test_a_usable_date_passes(value: Any) -> None:
    """A datetime out of the database and an ISO string out of a JSON body both work"""
    assert date_value_blockers({RackMountKey.START_DATE.value: value}) == []


@pytest.mark.parametrize('value', ['not-a-date', '', '   ', 42, True], ids=str)
def test_an_unusable_date_is_refused(value: Any) -> None:
    """
    Refused rather than dropped

    A client sending '01.09.2026' and getting a reservation with no dates would find out much later.
    """
    assert date_value_blockers({RackMountKey.START_DATE.value: value}) != []


def test_both_unusable_dates_are_reported() -> None:
    """One corrected payload"""
    assert len(date_value_blockers({
        RackMountKey.START_DATE.value: 'nope',
        RackMountKey.END_DATE.value: 'also-nope',
    })) == 2


def test_an_absent_date_is_not_a_problem() -> None:
    """Both ends are optional"""
    assert date_value_blockers({}) == []


def test_an_end_before_the_start_is_refused() -> None:
    """The one cross-field rule the dates have"""
    assert date_order_blocker(END, START) is not None


def test_an_end_after_the_start_is_accepted() -> None:
    """The ordinary range"""
    assert date_order_blocker(START, END) is None


def test_the_same_instant_at_both_ends_is_accepted() -> None:
    """A single-day hold is a range of zero length, not an inverted one"""
    assert date_order_blocker(START, START) is None


@pytest.mark.parametrize('start,end', [(START, None), (None, END), (None, None)], ids=str)
def test_a_half_open_range_is_always_accepted(start: Any, end: Any) -> None:
    """Both dates are optional, so only a range given in full can be inverted"""
    assert date_order_blocker(start, end) is None


def test_a_naive_and_an_aware_date_are_still_comparable() -> None:
    """
    A JSON body may carry a date with no zone while the stored one has UTC

    Comparing them raw would raise a TypeError and turn a business-rule check into a 500.
    """
    naive_end: datetime = datetime(2026, 8, 1)

    assert date_order_blocker(START, naive_end) is not None
    assert date_order_blocker(naive_end, END) is None


def test_a_long_expired_reservation_is_still_valid() -> None:
    """
    **The dates are descriptive.** Nothing here reads the clock

    This is the rule the feature deliberately does not have: an expired reservation keeps holding its
    slots until somebody deletes or unassigns it. Were it otherwise, the overlap check would answer
    differently on different days and a reservation could quietly stop holding space the user still
    believes is held.
    """
    long_ago: datetime = datetime.now(timezone.utc) - timedelta(days=3650)

    assert date_order_blocker(long_ago, long_ago + timedelta(days=1)) is None
    assert shape_blockers(RESERVATION, {}, _candidate(
        **{RackMountKey.START_DATE.value: long_ago,
           RackMountKey.END_DATE.value: long_ago + timedelta(days=1)},
    )) == []

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the area                                                            #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('area', [a.value for a in RackArea.get_main_areas()])
@pytest.mark.parametrize('kind', [RESERVATION, BLOCKER])
def test_an_occupant_may_sit_in_any_main_area(kind: str, area: str) -> None:
    """The main areas are the ones with a U range to hold"""
    assert area_blocker(kind, area) is None


@pytest.mark.parametrize('area', [a.value for a in RackArea.get_side_areas()])
@pytest.mark.parametrize('kind', [RESERVATION, BLOCKER])
def test_an_occupant_may_not_sit_in_a_side_list(kind: str, area: str) -> None:
    """A side list carries no geometry, so a blocker there would block nothing"""
    assert area_blocker(kind, area) is not None


@pytest.mark.parametrize('kind', [RESERVATION, BLOCKER])
def test_an_occupant_may_be_unassigned(kind: str) -> None:
    """Where a rack shrink puts one that no longer fits - the 'still needs re-placing' list"""
    assert area_blocker(kind, RackArea.UNASSIGNED.value) is None


@pytest.mark.parametrize('area', [a.value for a in RackArea])
def test_a_mount_may_sit_anywhere(area: str) -> None:
    """The area rule is about occupants only; an object may be in a side list"""
    assert area_blocker(MOUNT, area) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                             kind_change_blocker                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_changing_the_kind_is_refused() -> None:
    """A reservation may cover space for several devices, so there is nothing to convert into a mount"""
    assert kind_change_blocker(RESERVATION, MOUNT) is not None


def test_echoing_the_same_kind_back_is_not_a_change() -> None:
    """A client that PATCHes the whole row must not be refused for sending what is already stored"""
    assert kind_change_blocker(RESERVATION, RESERVATION) is None


def test_a_patch_that_names_no_kind_changes_nothing() -> None:
    """The common PATCH - just an area or a slot"""
    assert kind_change_blocker(RESERVATION, None) is None

# -------------------------------------------------------------------------------------------------------------------- #
#                                              shape_blockers                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_aggregate_judges_the_request_and_the_result() -> None:
    """
    The per-field rules judge what the request carries; the order and the area what the row becomes

    Which is the same thing on a create and deliberately different on a PATCH.
    """
    blockers = shape_blockers(
        RESERVATION,
        {RackMountKey.COLOR.value: 'nonsense'},
        _candidate(**{RackMountKey.START_DATE.value: END, RackMountKey.END_DATE.value: START}),
    )

    assert len(blockers) == 2


def test_a_patch_naming_only_the_end_date_is_judged_against_the_stored_start() -> None:
    """This is why the order check reads the candidate rather than the payload"""
    blockers = shape_blockers(
        RESERVATION,
        {RackMountKey.END_DATE.value: START},
        _candidate(**{RackMountKey.START_DATE.value: END, RackMountKey.END_DATE.value: START}),
    )

    assert len(blockers) == 1
    assert 'end_date' in blockers[0]


def test_a_well_formed_row_has_no_reasons() -> None:
    """The happy path of every kind"""
    assert shape_blockers(MOUNT, {RackMountKey.OBJECT_ID.value: OBJECT_ID}, _candidate()) == []
    assert shape_blockers(BLOCKER, {RackMountKey.LABEL.value: 'Metal frame'}, _candidate()) == []
    assert shape_blockers(
        RESERVATION,
        {RackMountKey.COLOR.value: COLOR},
        _candidate(**{RackMountKey.START_DATE.value: START, RackMountKey.END_DATE.value: END}),
    ) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                              read_stored_kind                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_a_stored_row_without_a_kind_reads_as_a_mount() -> None:
    """Which is what every row written before the kinds existed is"""
    assert read_stored_kind({'public_id': 900}) == MOUNT


@pytest.mark.parametrize('kind', [MOUNT, RESERVATION, BLOCKER])
def test_a_stored_kind_is_read_back(kind: str) -> None:
    """The ordinary case - what the grid styles the row from"""
    assert read_stored_kind({RackMountKey.KIND.value: kind}) == kind


@pytest.mark.parametrize('raw_kind', ['nonsense', '', 42, True], ids=str)
def test_a_drifted_stored_kind_reads_as_a_mount(raw_kind: Any) -> None:
    """
    Defaulted rather than propagated

    A create is refused for an unknown kind, but a row already in the database must stay drawable and
    editable even if its kind did not survive whatever wrote it.
    """
    assert read_stored_kind({RackMountKey.KIND.value: raw_kind}) == MOUNT
