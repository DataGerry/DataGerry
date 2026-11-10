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
The per-rack placement lock - one change of a rack's slots at a time

The overlap check reads a rack's mounts and the write comes after it, so two placements checked at the same moment
could both find the range free and both be stored on top of each other (and a placement checked against the old height
could land past the top of a rack being lowered). Every write that decides geometry - the mount POST and PATCH, and the
height-shrink clean-up - runs inside this lock, from the rack read through the write: a settings-section lock named
after the rack (``cmdb.manager.system_manager.settings_section_lock``), so it holds across workers and processes.
Writes that only add or remove membership without a slot (the location-tree membership, a delete) need no lock: they
cannot make two ranges overlap
"""
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.manager.system_manager.settings_section_lock import SectionLockSpec, settings_section_lock
from cmdb.framework.rack.rack_constants import RackPlacementLock
# -------------------------------------------------------------------------------------------------------------------- #


def rack_placement_lock_spec(rack_id: int, attempts: int = RackPlacementLock.ATTEMPTS) -> SectionLockSpec:
    """
    The placement lock of one rack

    Args:
        rack_id (int): public_id of the Rack CmdbObject
        attempts (int): How often a held lock is asked before giving up. Defaults to a placement's

    Returns:
        SectionLockSpec: The lock, held as the settings section ``rack_placement_lock_<rack_id>``
    """
    return SectionLockSpec(
        section=f'{RackPlacementLock.SECTION_PREFIX}{rack_id}',
        label=RackPlacementLock.LABEL,
        ttl_seconds=RackPlacementLock.TTL_SECONDS,
        attempts=attempts,
        retry_wait_seconds=RackPlacementLock.RETRY_WAIT_SECONDS,
    )


@contextmanager
def rack_placement_lock(
        settings_manager: SettingsManager,
        rack_id: int,
        user_id: Any,
        attempts: int = RackPlacementLock.ATTEMPTS) -> Iterator[None]:
    """
    Holds a rack's placement lock for the duration of the block

    Args:
        settings_manager (SettingsManager): db interface for the settings of the rack's database
        rack_id (int): public_id of the Rack CmdbObject
        user_id (Any): public_id of the requesting user, stored for the log
        attempts (int): How often a held lock is asked before giving up. Defaults to a placement's

    Raises:
        SettingsSectionLockHeldError: When another request held the lock at every attempt (the block does not run)

    Yields:
        None: Runs the block while the lock is held
    """
    with settings_section_lock(settings_manager, rack_placement_lock_spec(rack_id, attempts), user_id):
        yield
