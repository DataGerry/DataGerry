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
Unit tests for cmdb.framework.person_sync.sync_relocation - the writes' order

What a move and a copy write is the integration test's. Pinned here: a move records the stored person in the ledger
before it overwrites it, so an update applied but unanswered is undone too
"""
from unittest.mock import MagicMock, patch

from cmdb.framework.person_sync import sync_relocation as module
from cmdb.framework.person_sync.sync_engine import SyncResult
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_ID: int = 501


def test_a_move_is_recorded_before_the_update() -> None:
    """The stored person first, then the write"""
    context, ledger = MagicMock(), MagicMock()
    calls: list[str] = []
    ledger.updated.side_effect = lambda *_args: calls.append('recorded')
    context.objects_manager.update.side_effect = lambda *_args: calls.append('written')
    stored: dict[str, int] = {'public_id': PERSON_ID}

    with patch.object(module, 'relocated_person', return_value={'multi_data_sections': []}), \
            patch.object(module, 'plan_edit_write', return_value=('plan', {'$set': {}})), \
            patch.object(module, '_restamp'):
        module._move(context, MagicMock(), ledger, stored, MagicMock(), SyncResult())  # pylint: disable=protected-access

    assert calls == ['recorded', 'written']
