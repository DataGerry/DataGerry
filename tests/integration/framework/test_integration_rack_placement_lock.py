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
Integration tests for the per-rack placement lock against a real MongoDB, with real threads

What the unit tests can only assume: the settings collection's unique _id lets exactly one of two concurrent claims
through, a release by another token deletes nothing, a stale lock is taken over - and the races themselves. Two
placements into one range (the second one checked while the first is between its check and its write) and a height
shrink racing a placement each run twice: without the lock, to show the race is real, and with it, where the second
request waits for the first and sees its write
"""
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.manager.rack_mounts_manager import RackMountsManager
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY
from cmdb.manager.system_manager.settings_section_lock import (
    SectionLockSpec,
    acquire_section_lock,
    release_section_lock,
)
from cmdb.manager.system_manager.settings_section_lock_constants import SectionLockKey
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKey
from cmdb.framework.rack.height_change import unplace_mounts_beyond_height, unplace_under_placement_lock
from cmdb.framework.rack.placement_lock import rack_placement_lock, rack_placement_lock_spec
from cmdb.framework.rack.rack_constants import RackPlacementLock
from cmdb.interface.rest_api.routes.rack_routes.rack_mount_helper import placement_blockers
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 943101
FIRST_MOUNT_ID: int = 943110
SECOND_MOUNT_ID: int = 943111
USER_ID: int = 1
RACK_HEIGHT: int = 42
LOWERED_HEIGHT: int = 20
START_SLOT: int = 30
MOUNT_HEIGHT: int = 2
CONTESTED_START: int = 31
#: How long the first request stays between its check and its write - the window the race needs, well inside the
#: placement lock's retry budget (ATTEMPTS x RETRY_WAIT_SECONDS = 0.4 s of waits)
WRITE_DELAY_SECONDS: float = 0.15
JOIN_TIMEOUT_SECONDS: float = 10.0
EXPIRED_AGE: timedelta = timedelta(seconds=RackPlacementLock.TTL_SECONDS + 60)
OTHER_HOLDER: str = 'another-request'


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[SettingsManager]:
    """The settings manager; the rack's lock section is removed around each test"""
    settings = SettingsManager(database_manager, database_name)
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    section: str = rack_placement_lock_spec(RACK_ID).section
    collection.delete_many({SETTINGS_SECTION_ID_KEY: section})
    yield settings
    collection.delete_many({SETTINGS_SECTION_ID_KEY: section})


@pytest.fixture(name='mounts')
def fixture_mounts(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[RackMountsManager]:
    """The rack mounts manager; the rack's mounts are removed around each test"""
    collection = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)
    collection.delete_many({RackMountKey.RACK_ID.value: RACK_ID})
    yield RackMountsManager(database_manager, database_name)
    collection.delete_many({RackMountKey.RACK_ID.value: RACK_ID})


def _occupant(public_id: int, start_slot: int) -> dict[str, Any]:
    """A placed FRONT reservation (an occupant names no object, so the object_id index stays out of it)"""
    return {
        RackMountKey.PUBLIC_ID.value: public_id, RackMountKey.RACK_ID.value: RACK_ID,
        RackMountKey.KIND.value: 'OCCUPANT', RackMountKey.LABEL.value: f'reserved-{public_id}',
        RackMountKey.AREA.value: RackArea.FRONT.value, RackMountKey.START_SLOT.value: start_slot,
        RackMountKey.HEIGHT.value: MOUNT_HEIGHT, RackMountKey.POSITION.value: None,
    }


def _place(mounts: RackMountsManager, candidate: dict[str, Any], rack_height: int, *, delay: float = 0.0,
           checked: threading.Event | None = None) -> list[str]:
    """The route's critical section: check, (optionally linger), write when the check passed; answers the refusals"""
    errors: list[str] = placement_blockers(mounts, candidate, rack_height)

    if checked is not None:
        checked.set()

    threading.Event().wait(delay)

    if not errors:
        mounts.insert_item(candidate)

    return errors


def _in_thread(target: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    """Starts a thread; its answer (or its error) lands in the list"""
    outcome: list[Any] = []

    def run() -> None:
        try:
            outcome.append(target())
        except Exception as err:  # pylint: disable=broad-exception-caught
            outcome.append(err)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


def _placed_in_range(mounts: RackMountsManager) -> list[int]:
    """The ids of the placed mounts of the rack"""
    return sorted(mount[RackMountKey.PUBLIC_ID.value]
                  for mount in mounts.get_mounts_of_rack(RACK_ID, RackArea.FRONT.value))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the lock on MongoDB                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_two_claims_at_once_let_exactly_one_through(settings: SettingsManager) -> None:
    """The unique _id decides: one token stored, the other refused"""
    spec: SectionLockSpec = rack_placement_lock_spec(RACK_ID, attempts=1)
    barrier = threading.Barrier(2)
    answers: list[Any] = []

    def claim() -> None:
        barrier.wait()
        try:
            answers.append(acquire_section_lock(settings, spec, USER_ID))
        except Exception as err:  # pylint: disable=broad-exception-caught
            answers.append(err)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_TIMEOUT_SECONDS)

    tokens: list[str] = [answer for answer in answers if isinstance(answer, str)]
    assert len(tokens) == 1
    assert settings.get_section(spec.section)[SectionLockKey.HOLDER.value] == tokens[0]


def test_a_release_by_another_token_deletes_nothing(settings: SettingsManager) -> None:
    """Only the holder frees the rack"""
    spec: SectionLockSpec = rack_placement_lock_spec(RACK_ID)
    token: str = acquire_section_lock(settings, spec, USER_ID)

    release_section_lock(settings, spec, OTHER_HOLDER)
    assert settings.get_section(spec.section)[SectionLockKey.HOLDER.value] == token

    release_section_lock(settings, spec, token)
    assert not settings.get_section(spec.section)


def test_a_lock_past_its_ttl_is_taken_over(settings: SettingsManager, database_manager: MongoDatabaseManager,
                                           database_name: str) -> None:
    """A holder that died never releases; after the TTL the rack is usable again"""
    spec: SectionLockSpec = rack_placement_lock_spec(RACK_ID, attempts=1)
    database_manager.get_collection(SettingsManager.COLLECTION, database_name).insert_one({
        SETTINGS_SECTION_ID_KEY: spec.section, SectionLockKey.HOLDER.value: OTHER_HOLDER,
        SectionLockKey.ACQUIRED_AT.value: datetime.now(timezone.utc) - EXPIRED_AGE,
    })

    token: str = acquire_section_lock(settings, spec, USER_ID)

    assert settings.get_section(spec.section)[SectionLockKey.HOLDER.value] == token


# -------------------------------------------------------------------------------------------------------------------- #
#                                               two placements, one range                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_without_the_lock_two_placements_overlap(mounts: RackMountsManager) -> None:
    """The race is real: the second check runs while the first write is pending, both pass, both are stored"""
    checked = threading.Event()
    first, first_errors = _in_thread(lambda: _place(
        mounts, _occupant(FIRST_MOUNT_ID, START_SLOT), RACK_HEIGHT, delay=WRITE_DELAY_SECONDS, checked=checked))
    checked.wait(JOIN_TIMEOUT_SECONDS)
    second_errors = _place(mounts, _occupant(SECOND_MOUNT_ID, CONTESTED_START), RACK_HEIGHT)
    first.join(JOIN_TIMEOUT_SECONDS)

    assert first_errors == [[]] and second_errors == []
    assert _placed_in_range(mounts) == [FIRST_MOUNT_ID, SECOND_MOUNT_ID]


def test_with_the_lock_the_second_placement_waits_and_is_refused(
        settings: SettingsManager, mounts: RackMountsManager) -> None:
    """The second request waits for the first one's write and then sees the slots taken"""
    checked = threading.Event()

    def first_placement() -> list[str]:
        with rack_placement_lock(settings, RACK_ID, USER_ID):
            return _place(mounts, _occupant(FIRST_MOUNT_ID, START_SLOT), RACK_HEIGHT, delay=WRITE_DELAY_SECONDS,
                          checked=checked)

    first, first_errors = _in_thread(first_placement)
    checked.wait(JOIN_TIMEOUT_SECONDS)
    with rack_placement_lock(settings, RACK_ID, USER_ID):
        second_errors = _place(mounts, _occupant(SECOND_MOUNT_ID, CONTESTED_START), RACK_HEIGHT)
    first.join(JOIN_TIMEOUT_SECONDS)

    assert first_errors == [[]]
    assert second_errors, 'the second placement was checked after the first write'
    assert _placed_in_range(mounts) == [FIRST_MOUNT_ID]
    assert not settings.get_section(rack_placement_lock_spec(RACK_ID).section)


# -------------------------------------------------------------------------------------------------------------------- #
#                                           a height shrink against a placement                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_without_the_lock_a_shrink_misses_a_placement_being_written(mounts: RackMountsManager) -> None:
    """Checked against 42 U, read by the shrink before it is written: left at U30 of a 20 U rack"""
    checked = threading.Event()
    placement, _errors = _in_thread(lambda: _place(
        mounts, _occupant(FIRST_MOUNT_ID, START_SLOT), RACK_HEIGHT, delay=WRITE_DELAY_SECONDS, checked=checked))
    checked.wait(JOIN_TIMEOUT_SECONDS)
    unplaced: list[int] = unplace_mounts_beyond_height(mounts, RACK_ID, LOWERED_HEIGHT)
    placement.join(JOIN_TIMEOUT_SECONDS)

    assert unplaced == []
    assert _placed_in_range(mounts) == [FIRST_MOUNT_ID]


def test_with_the_lock_the_shrink_waits_and_unplaces_the_new_mount(
        settings: SettingsManager, mounts: RackMountsManager) -> None:
    """The shrink reads the mounts only after the placement was written, and unplaces it"""
    checked = threading.Event()

    def placement() -> list[str]:
        with rack_placement_lock(settings, RACK_ID, USER_ID):
            return _place(mounts, _occupant(FIRST_MOUNT_ID, START_SLOT), RACK_HEIGHT, delay=WRITE_DELAY_SECONDS,
                          checked=checked)

    thread, _errors = _in_thread(placement)
    checked.wait(JOIN_TIMEOUT_SECONDS)
    unplaced: list[int] = unplace_under_placement_lock(settings, mounts, RACK_ID, LOWERED_HEIGHT, USER_ID)
    thread.join(JOIN_TIMEOUT_SECONDS)

    assert unplaced == [FIRST_MOUNT_ID]
    assert _placed_in_range(mounts) == []
    stored: dict[str, Any] = mounts.get_item(FIRST_MOUNT_ID, as_dict=True)
    assert stored[RackMountKey.AREA.value] == RackArea.UNASSIGNED.value
    assert stored[RackMountKey.HEIGHT.value] == MOUNT_HEIGHT
