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
Unit tests for user_management_routes.person_sync_relocation_helper

Pinned: the pre-check's view and the counts; a blocked person refuses the change unless copied, the 400 naming each
blocked person with its blockers; nothing relocated writes nothing; a relocation runs on one ledger and copies the
blocked, then its events follow; a failed one is undone and raised
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync.sync_engine import SyncResult
from cmdb.framework.person_sync.sync_relocation_rules import PersonRelocation
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_relocation_helper import (
    apply_relocations,
    refuse_blocked,
    relocation_counts,
    relocations_view,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.interface.rest_api.routes.user_management_routes.person_sync_relocation_helper'
CALLER: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True)
FREE: PersonRelocation = PersonRelocation(5, 51, 7, 8)
HELD: PersonRelocation = PersonRelocation(6, 52, 7, 8, ('it is placed', 'object 9 references it'))


def test_the_view_and_the_counts() -> None:
    """Every relocation; blocked counted; moved and copied"""
    assert relocations_view([FREE, HELD]) == {'relocations': [FREE.to_json(), HELD.to_json()], 'blocked': 1}
    assert relocation_counts([FREE, HELD]) == {'moved': 1, 'copied': 1}
    assert relocation_counts([]) == {'moved': 0, 'copied': 0}


def test_a_blocked_person_refuses_unless_copied() -> None:
    """The 400 names the person, its user and every blocker"""
    with pytest.raises(BadRequest) as raised:
        refuse_blocked([FREE, HELD], 'cancel')

    assert raised.value.description.startswith('1 person(s) cannot move')
    assert 'person 52 of user 6 (it is placed, object 9 references it)' in raised.value.description
    assert 'person 51' not in raised.value.description
    refuse_blocked([FREE, HELD], 'copy')
    refuse_blocked([FREE], 'cancel')


def test_nothing_to_relocate_writes_nothing() -> None:
    """No ledger, no events"""
    with patch(f'{MODULE}.relocate_persons') as relocate, patch(f'{MODULE}.emit_sync_events') as emit:
        assert apply_relocations(CALLER, MagicMock(), MagicMock(), []) == SyncResult()

    relocate.assert_not_called()
    emit.assert_not_called()


def test_a_relocation_copies_the_blocked_then_emits() -> None:
    """One ledger; the events after it stood"""
    written = SyncResult(created=[60])

    with patch(f'{MODULE}.relocate_persons', return_value=written) as relocate, \
            patch(f'{MODULE}.emit_sync_events') as emit, patch(f'{MODULE}.build_sync_events'):
        assert apply_relocations(CALLER, MagicMock(), MagicMock(), [FREE, HELD]) is written

    assert relocate.call_args.args[3] == [FREE, HELD]
    assert relocate.call_args.kwargs['copy_blocked'] is True
    emit.assert_called_once()


def test_a_failed_relocation_is_undone_and_raised() -> None:
    """No events"""
    failure = RuntimeError('lost')
    undone: list[Any] = []

    def _failing(_context: Any, _stores: Any, ledger: Any, _relocations: Any, copy_blocked: bool) -> SyncResult:
        assert copy_blocked
        ledger.compensated('c', 'd', lambda: undone.append(True), lambda: True)
        raise failure

    with patch(f'{MODULE}.relocate_persons', side_effect=_failing), patch(f'{MODULE}.emit_sync_events') as emit:
        with pytest.raises(RuntimeError) as raised:
            apply_relocations(CALLER, MagicMock(), MagicMock(), [FREE])

    assert raised.value is failure
    assert undone == [True]
    emit.assert_not_called()
