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
Unit tests for cmdb.framework.rack.placement_lock - the per-rack placement lock

The lock mechanics are the settings-section lock's (tests/unit/manager/system_manager/test_settings_section_lock.py);
here: which section one rack's lock is, how long it is honoured and waited for, and that the block runs inside it
"""
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.system_manager.settings_section_lock_constants import SectionLockKey
from cmdb.framework.rack.placement_lock import rack_placement_lock, rack_placement_lock_spec
from cmdb.framework.rack.rack_constants import RackPlacementLock
from cmdb.errors.manager.settings_section_lock import SettingsSectionLockHeldError
# -------------------------------------------------------------------------------------------------------------------- #

RACK_ID: int = 4711
OTHER_RACK_ID: int = 4712
USER_ID: int = 9
GUNICORN_WORKER_TIMEOUT_SECONDS: int = 120


def test_each_rack_has_its_own_section() -> None:
    """The section is named after the rack, so two racks never wait for each other"""
    assert rack_placement_lock_spec(RACK_ID).section == 'rack_placement_lock_4711'
    assert rack_placement_lock_spec(RACK_ID).section != rack_placement_lock_spec(OTHER_RACK_ID).section


def test_a_placement_waits_briefly_and_the_lock_outlives_a_running_request() -> None:
    """A placement's attempts and wait; a TTL past the worker timeout, so a live holder is never taken over"""
    spec = rack_placement_lock_spec(RACK_ID)

    assert (spec.attempts, spec.retry_wait_seconds, spec.label) == (
        RackPlacementLock.ATTEMPTS, RackPlacementLock.RETRY_WAIT_SECONDS, 'rack placement lock',
    )
    assert spec.ttl_seconds > GUNICORN_WORKER_TIMEOUT_SECONDS
    assert RackPlacementLock.HEIGHT_CHANGE_ATTEMPTS > RackPlacementLock.ATTEMPTS


def test_the_attempts_can_be_raised_for_a_caller_that_must_run() -> None:
    """The height-shrink clean-up asks longer"""
    assert rack_placement_lock_spec(RACK_ID, RackPlacementLock.HEIGHT_CHANGE_ATTEMPTS).attempts == 50


def test_the_block_runs_inside_the_racks_lock() -> None:
    """Claimed as the rack's section before the block, released after it"""
    settings = MagicMock()
    settings.claim_section.return_value = True

    with rack_placement_lock(settings, RACK_ID, USER_ID):
        assert settings.claim_section.call_args.args[0] == 'rack_placement_lock_4711'
        settings.delete_section.assert_not_called()

    holder: str = settings.claim_section.call_args.args[1][SectionLockKey.HOLDER.value]
    settings.delete_section.assert_called_once_with('rack_placement_lock_4711', {SectionLockKey.HOLDER.value: holder})


def test_a_held_rack_lock_raises_after_its_attempts() -> None:
    """The typed error reaches the caller, who decides the answer"""
    settings = MagicMock()
    settings.claim_section.return_value = False
    settings.claim_section_where.return_value = False

    with patch('cmdb.manager.system_manager.settings_section_lock.sleep'),             pytest.raises(SettingsSectionLockHeldError):
        with rack_placement_lock(settings, RACK_ID, USER_ID):
            pass

    assert settings.claim_section.call_count == RackPlacementLock.ATTEMPTS
