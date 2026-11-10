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
Unit tests for cmdb.manager.system_manager.settings_section_lock - the lock held as a settings section

A MagicMock stands in for the SettingsManager, so each answer of the atomic claim, the TTL takeover and the
conditional release can be chosen; the claim's atomicity itself is the settings collection's unique _id, exercised
against MongoDB in tests/integration/framework/test_integration_rack_placement_lock.py
"""
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.system_manager.settings_section_lock import (
    SectionLockSpec,
    acquire_section_lock,
    claim_section_lock_once,
    release_section_lock,
    settings_section_lock,
)
from cmdb.manager.system_manager.settings_section_lock_constants import SectionLockKey
from cmdb.errors.database import DocumentDeleteError, DocumentNetworkError
from cmdb.errors.manager.settings_section_lock import SettingsSectionLockHeldError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.manager.system_manager.settings_section_lock'
SECTION: str = 'unit_test_lock'
LABEL: str = 'unit test lock'
TTL_SECONDS: int = 77
ATTEMPTS: int = 4
WAIT_SECONDS: float = 0.25
USER_ID: int = 31
TOKEN: str = 'token-of-this-request'
SPEC: SectionLockSpec = SectionLockSpec(SECTION, LABEL, TTL_SECONDS, ATTEMPTS, WAIT_SECONDS)


def _settings(claims: list[bool] | bool = True, takeovers: list[bool] | bool = False) -> MagicMock:
    """A SettingsManager whose claims and takeovers answer in turn"""
    settings: MagicMock = MagicMock()

    if isinstance(claims, list):
        settings.claim_section.side_effect = claims
    else:
        settings.claim_section.return_value = claims

    if isinstance(takeovers, list):
        settings.claim_section_where.side_effect = takeovers
    else:
        settings.claim_section_where.return_value = takeovers

    return settings


# -------------------------------------------------------------------------------------------------------------------- #
#                                               claim_section_lock_once                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_free_lock_is_claimed_with_holder_time_and_user() -> None:
    """One atomic claim of the section, naming the token, now and the user; no takeover asked"""
    settings = _settings()
    before: datetime = datetime.now(timezone.utc)

    assert claim_section_lock_once(settings, SPEC, TOKEN, USER_ID)

    section, lock = settings.claim_section.call_args.args
    assert section == SECTION
    assert lock[SectionLockKey.HOLDER.value] == TOKEN
    assert lock[SectionLockKey.USER_ID.value] == USER_ID
    assert lock[SectionLockKey.ACQUIRED_AT.value] >= before
    settings.claim_section_where.assert_not_called()


def test_a_held_lock_is_taken_over_only_past_its_ttl(caplog: pytest.LogCaptureFixture) -> None:
    """The takeover matches the section only while acquired before now - TTL; it is logged with the label"""
    settings = _settings(claims=False, takeovers=True)

    assert claim_section_lock_once(settings, SPEC, TOKEN, USER_ID)

    section, condition, lock = settings.claim_section_where.call_args.args
    assert section == SECTION
    assert lock == settings.claim_section.call_args.args[1]
    assert condition == {SectionLockKey.ACQUIRED_AT.value: {
        '$lt': lock[SectionLockKey.ACQUIRED_AT.value] - timedelta(seconds=TTL_SECONDS),
    }}
    assert f'took over a {LABEL} older than {TTL_SECONDS} s' in caplog.text


def test_a_live_lock_is_not_taken() -> None:
    """Held and not expired: this attempt fails"""
    assert not claim_section_lock_once(_settings(claims=False, takeovers=False), SPEC, TOKEN, USER_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 acquire_section_lock                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_acquire_answers_a_fresh_token_per_request() -> None:
    """Every request holds its own token, so none can release another's lock"""
    first: str = acquire_section_lock(_settings(), SPEC, USER_ID)
    second: str = acquire_section_lock(_settings(), SPEC, USER_ID)

    assert first and second and first != second


def test_acquire_retries_and_waits_between_attempts() -> None:
    """Held twice, free the third time: two waits of the spec's length, then the lock"""
    settings = _settings(claims=[False, False, True])

    with patch(f'{MODULE}.sleep') as sleep:
        token: str = acquire_section_lock(settings, SPEC, USER_ID)

    assert settings.claim_section.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [WAIT_SECONDS, WAIT_SECONDS]
    assert settings.claim_section.call_args.args[1][SectionLockKey.HOLDER.value] == token


def test_acquire_gives_up_after_every_attempt_with_the_held_error() -> None:
    """Held at every attempt: the typed error naming the lock, after exactly ATTEMPTS asks"""
    settings = _settings(claims=False, takeovers=False)

    with patch(f'{MODULE}.sleep') as sleep, pytest.raises(SettingsSectionLockHeldError, match=SECTION):
        acquire_section_lock(settings, SPEC, USER_ID)

    assert settings.claim_section.call_count == ATTEMPTS
    assert sleep.call_count == ATTEMPTS - 1


@pytest.mark.parametrize('attempts', [1, 0, -3])
def test_one_attempt_or_fewer_refuses_at_once_without_waiting(attempts: int) -> None:
    """One ask, no wait - a non-positive count still asks once"""
    settings = _settings(claims=False, takeovers=False)

    with patch(f'{MODULE}.sleep') as sleep, pytest.raises(SettingsSectionLockHeldError):
        acquire_section_lock(settings, SectionLockSpec(SECTION, LABEL, TTL_SECONDS, attempts), USER_ID)

    assert settings.claim_section.call_count == 1
    sleep.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 release_section_lock                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_release_deletes_the_section_only_while_it_is_this_requests() -> None:
    """Conditional on the holder token"""
    settings = _settings()

    release_section_lock(settings, SPEC, TOKEN)

    settings.delete_section.assert_called_once_with(SECTION, {SectionLockKey.HOLDER.value: TOKEN})


@pytest.mark.parametrize('error', [DocumentDeleteError('refused'), DocumentNetworkError('connection lost')],
                         ids=['refused', 'lost connection'])
def test_a_failed_release_is_logged_not_raised(error: Exception, caplog: pytest.LogCaptureFixture) -> None:
    """The lock expires on its own; the log names the label and the TTL"""
    settings = _settings()
    settings.delete_section.side_effect = error

    release_section_lock(settings, SPEC, TOKEN)

    assert f'The {LABEL} could not be released, it expires after {TTL_SECONDS} s' in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                                settings_section_lock                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_block_runs_inside_the_lock_and_releases_it() -> None:
    """Claimed before the block, released after it, with the same token"""
    settings = _settings()
    seen: list[Any] = []

    with settings_section_lock(settings, SPEC, USER_ID):
        seen.append(settings.claim_section.call_count)
        settings.delete_section.assert_not_called()

    holder: str = settings.claim_section.call_args.args[1][SectionLockKey.HOLDER.value]
    assert seen == [1]
    settings.delete_section.assert_called_once_with(SECTION, {SectionLockKey.HOLDER.value: holder})


def test_a_failing_block_still_releases_and_its_error_stands() -> None:
    """The release runs in a finally"""
    settings = _settings()

    with pytest.raises(RuntimeError, match='write failed'), settings_section_lock(settings, SPEC, USER_ID):
        raise RuntimeError('write failed')

    settings.delete_section.assert_called_once()


def test_a_held_lock_runs_nothing_and_releases_nothing() -> None:
    """Held at every attempt: the block never runs"""
    settings = _settings(claims=False, takeovers=False)
    ran: list[bool] = []

    with patch(f'{MODULE}.sleep'), pytest.raises(SettingsSectionLockHeldError):
        with settings_section_lock(settings, SPEC, USER_ID):
            ran.append(True)

    assert not ran
    settings.delete_section.assert_not_called()
