# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.framework.person_sync.sync_pass

What the pass writes on a real database is the integration test's. Pinned here: with the user sync off nothing is read;
an unusable target is refused before an id is reserved or anything written; the switch-off edits only the persons
still active and removes every fingerprint in one update
"""
from unittest.mock import MagicMock

import pytest

from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync.sync_engine import SyncContext
from cmdb.framework.person_sync.sync_pass import run_sync_pass, switch_off_pass
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings
from cmdb.errors.person_sync import PersonSyncTargetError
# -------------------------------------------------------------------------------------------------------------------- #

ACTING: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True)
MISSING_TYPE_ID: int = 77


def _context(settings: PersonSyncSettings) -> SyncContext:
    """A context of mocked managers"""
    return SyncContext(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, ACTING)


def test_with_the_user_sync_off_nothing_is_read() -> None:
    """Not even the users"""
    context = _context(PersonSyncSettings())

    run_sync_pass(context)

    context.users_manager.find.assert_not_called()
    context.objects_manager.find.assert_not_called()


def test_an_unusable_target_is_refused_before_anything_is_written() -> None:
    """No id reserved, no bulk write"""
    context = _context(PersonSyncSettings(users=UserSyncSettings(active=True, default_type_id=MISSING_TYPE_ID)))
    context.users_manager.find.return_value = [{'public_id': 5, 'user_name': 'ann', 'active': True}]
    context.objects_manager.find.return_value = []
    context.types_manager.get_types_lookup.return_value = {}

    with pytest.raises(PersonSyncTargetError):
        run_sync_pass(context)

    context.objects_manager.reserve_public_ids.assert_not_called()
    context.objects_manager.bulk_write.assert_not_called()


def test_switching_off_edits_the_active_persons_and_drops_every_fingerprint() -> None:
    """The read selects the active ones; one update removes the fingerprints"""
    context = _context(PersonSyncSettings())
    context.objects_manager.find.return_value = [{
        'public_id': 9, 'type_id': 3, 'author_id': 1, 'active': True, 'fields': [], 'sync_hash': 'h',
        'system_ref': {'kind': 'user', 'id': 5},
    }]

    result = switch_off_pass(context)

    assert context.objects_manager.find.call_args.kwargs['criteria'] == {'system_ref.kind': 'user', 'active': True}
    assert list(result.edits) == [9]
    context.objects_manager.bulk_write.assert_called_once()
    context.objects_manager.update_many_raw.assert_called_once_with(
        {'system_ref.kind': 'user', 'sync_hash': {'$exists': True}}, {'$unset': {'sync_hash': ''}})
