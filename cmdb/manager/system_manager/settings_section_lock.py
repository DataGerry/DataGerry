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
A lock held as a settings section - one request at a time per section, across every worker and process

The section's name is the lock's name and the settings collection's unique ``_id`` decides between two requests
claiming it at once (``SettingsManager.claim_section``): exactly one insert is stored. While the section exists the
lock is held. Its owner names it by a ``SectionLockSpec``:

* ``ttl_seconds`` - a lock older than this is taken over with one conditional update (``claim_section_where``),
  which only one of two takers can win, and the takeover is logged. A worker gunicorn kills never reaches the
  release, so the TTL has to outlive any request that is still running
* ``attempts`` / ``retry_wait_seconds`` - how often a held lock is asked again before giving up, and how long to
  wait in between. One attempt refuses at once

The release deletes the section only while it still holds this request's token, so a request that outlived its lock
never releases the lock another request took over. A release that fails is logged, not raised: the lock expires on
its own. A lock that stays held raises ``SettingsSectionLockHeldError``; the owner decides what that answers
"""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging import Logger, getLogger
from time import sleep
from typing import Any
from uuid import uuid4

from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.manager.system_manager.settings_section_lock_constants import SectionLockKey
from cmdb.errors.database import DocumentDeleteError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.settings_section_lock import SettingsSectionLockHeldError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: What a failed release can raise - the lock then simply expires after its TTL
LOCK_RELEASE_ERRORS: tuple[type[Exception], ...] = (DocumentDeleteError, DocumentLockTimeoutError, DocumentNetworkError)


@dataclass(frozen=True)
class SectionLockSpec:
    """
    One lock: which settings section it is held as, and how long it is honoured and waited for

    Attributes:
        section (str): The settings section the lock is held as
        label (str): What the log calls it ("configuration lock")
        ttl_seconds (int): How long a lock is honoured before another request may take it over
        attempts (int): How often a held lock is asked before giving up; 1 refuses at once
        retry_wait_seconds (float): The wait between two attempts
    """
    section: str
    label: str
    ttl_seconds: int
    attempts: int = 1
    retry_wait_seconds: float = 0.0


def acquire_section_lock(settings_manager: SettingsManager, spec: SectionLockSpec, user_id: Any) -> str:
    """
    Takes a lock, asking up to ``spec.attempts`` times with ``spec.retry_wait_seconds`` in between

    Args:
        settings_manager (SettingsManager): db interface for the settings, bound to the database that is locked
        spec (SectionLockSpec): The lock
        user_id (Any): public_id of the requesting user, stored for the log

    Raises:
        SettingsSectionLockHeldError: When another request held the lock at every attempt
        DocumentInsertError / DocumentUpdateError: When the lock could not be written

    Returns:
        str: This request's holder token - what releases the lock
    """
    token: str = uuid4().hex

    for attempt in range(max(spec.attempts, 1)):
        if attempt:
            sleep(spec.retry_wait_seconds)

        if claim_section_lock_once(settings_manager, spec, token, user_id):
            return token

    raise SettingsSectionLockHeldError(f"The {spec.label} '{spec.section}' is held by another request")


def claim_section_lock_once(settings_manager: SettingsManager, spec: SectionLockSpec, token: str, user_id: Any) -> bool:
    """
    One attempt at a lock: claim it free, else take it over when it is older than its TTL

    Args:
        settings_manager (SettingsManager): db interface for the settings
        spec (SectionLockSpec): The lock
        token (str): This request's holder token
        user_id (Any): public_id of the requesting user

    Raises:
        DocumentInsertError / DocumentUpdateError: When the lock could not be written

    Returns:
        bool: True when this request holds the lock now
    """
    now: datetime = datetime.now(timezone.utc)
    lock: dict[str, Any] = {
        SectionLockKey.HOLDER.value: token,
        SectionLockKey.ACQUIRED_AT.value: now,
        SectionLockKey.USER_ID.value: user_id,
    }

    if settings_manager.claim_section(spec.section, lock):
        return True

    expired: dict[str, Any] = {SectionLockKey.ACQUIRED_AT.value: {'$lt': now - timedelta(seconds=spec.ttl_seconds)}}

    if not settings_manager.claim_section_where(spec.section, expired, lock):
        return False

    LOGGER.warning("[settings_section_lock] User %s took over a %s older than %s s", user_id, spec.label,
                   spec.ttl_seconds)

    return True


def release_section_lock(settings_manager: SettingsManager, spec: SectionLockSpec, token: str) -> None:
    """
    Releases a lock - only while it is still this request's

    A failure is logged, not raised: whatever ran under the lock stands, and the lock expires after its TTL

    Args:
        settings_manager (SettingsManager): db interface for the settings
        spec (SectionLockSpec): The lock
        token (str): This request's holder token (``acquire_section_lock``)
    """
    try:
        settings_manager.delete_section(spec.section, {SectionLockKey.HOLDER.value: token})
    except LOCK_RELEASE_ERRORS as err:
        LOGGER.error("[settings_section_lock] The %s could not be released, it expires after %s s: %s",
                     spec.label, spec.ttl_seconds, err, exc_info=True)


@contextmanager
def settings_section_lock(settings_manager: SettingsManager, spec: SectionLockSpec, user_id: Any) -> Iterator[None]:
    """
    Holds a lock for the duration of the block, releasing it after a success and a failure alike

    Args:
        settings_manager (SettingsManager): db interface for the settings, bound to the database that is locked
        spec (SectionLockSpec): The lock
        user_id (Any): public_id of the requesting user, stored for the log

    Raises:
        SettingsSectionLockHeldError: When another request held the lock at every attempt (the block does not run)
        DocumentInsertError / DocumentUpdateError: When the lock could not be taken (the block does not run)

    Yields:
        None: Runs the block while the lock is held
    """
    token: str = acquire_section_lock(settings_manager, spec, user_id)

    try:
        yield
    finally:
        release_section_lock(settings_manager, spec, token)
