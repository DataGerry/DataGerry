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
Unit tests for the ledger recording of cmdb.interface.rest_api.routes.isms_routes.isms_scale_helper

Pure tests against a MagicMock scale manager. Pinned: an insert is recorded once it has an id, a refused one not at
all; a plain update is recorded with the stored entry before it runs - and not at all for an entry already gone; a
basis change hands the route's ledger to ``update_with_follow_up``; the route's ledger carries the action and the
entity into its residue message.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.models.isms_model import IsmsImpact
from cmdb.interface.rest_api.routes.isms_routes import isms_scale_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    IMPACT_LABEL,
    SCALE_WRITE_UNDO_INCOMPLETE_MSG,
    IsmsWriteAction,
)
from cmdb.errors.manager.impact_manager import IMPACT_MANAGER_ERRORS, ImpactManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

IMPACT_ID: int = 5
STORED_IMPACT: dict[str, Any] = {'public_id': IMPACT_ID, 'name': 'High', 'calculation_basis': 3.0,
                                 'description': None}


def _manager() -> MagicMock:
    """A scale manager carrying the Impact error map and the stored entry"""
    manager = MagicMock(name='impact_manager')
    manager.exceptions = IMPACT_MANAGER_ERRORS
    manager.insert_item.return_value = IMPACT_ID
    manager.get_item.return_value = dict(STORED_IMPACT)

    return manager


def test_an_insert_is_recorded_once_it_has_an_id() -> None:
    """The new id is answered and recorded as the ledger's one insert"""
    manager = _manager()
    ledger = WriteLedger()

    assert isms_scale_helper.insert_scale_entry(manager, dict(STORED_IMPACT), IMPACT_LABEL, ledger) == IMPACT_ID
    assert [(entry.kind, entry.public_id) for entry in ledger.entries] == [(WriteKind.INSERT, IMPACT_ID)]


def test_a_failed_insert_records_nothing() -> None:
    """No id, nothing to undo; the manager's error passes on"""
    manager = _manager()
    manager.insert_item.side_effect = ImpactManagerInsertError('down')
    ledger = WriteLedger()

    with pytest.raises(ImpactManagerInsertError):
        isms_scale_helper.insert_scale_entry(manager, dict(STORED_IMPACT), IMPACT_LABEL, ledger)

    assert not ledger.entries


def test_a_plain_update_is_recorded_with_the_stored_entry() -> None:
    """Before the write, so the undo replaces the entry with what was stored"""
    manager = _manager()
    ledger = WriteLedger()

    with patch.object(isms_scale_helper, 'update_item_from_payload', return_value=STORED_IMPACT) as update:
        isms_scale_helper.update_scale_entry(manager, IsmsImpact, IMPACT_ID, dict(STORED_IMPACT), False,
                                             IMPACT_LABEL, ledger)

    assert [(entry.kind, entry.prior) for entry in ledger.entries] == [(WriteKind.UPDATE, STORED_IMPACT)]
    update.assert_called_once()
    manager.update_with_follow_up.assert_not_called()


def test_a_plain_update_of_an_entry_already_gone_records_nothing() -> None:
    """No stored entry to put back; the update's own answer decides the route's"""
    manager = _manager()
    manager.get_item.return_value = None
    ledger = WriteLedger()

    with patch.object(isms_scale_helper, 'update_item_from_payload', return_value=None):
        isms_scale_helper.update_scale_entry(manager, IsmsImpact, IMPACT_ID, dict(STORED_IMPACT), False,
                                             IMPACT_LABEL, ledger)

    assert not ledger.entries


def test_a_basis_change_hands_the_ledger_to_the_follow_up() -> None:
    """The entry and the RiskAssessments are recorded by the manager, in the route's ledger"""
    manager = _manager()
    ledger = WriteLedger()

    isms_scale_helper.update_scale_entry(manager, IsmsImpact, IMPACT_ID, dict(STORED_IMPACT), True, IMPACT_LABEL,
                                         ledger)

    manager.update_with_follow_up.assert_called_once_with(IMPACT_ID, dict(STORED_IMPACT), ledger)
    manager.get_item.assert_not_called()


@pytest.mark.parametrize('action', list(IsmsWriteAction))
def test_the_route_ledger_names_the_action_and_the_entity(action: IsmsWriteAction) -> None:
    """The residue message is filled with the action's word and the entity's singular"""
    with patch.object(isms_scale_helper, 'undone_on_failure') as undone:
        isms_scale_helper.scale_write_ledger(action, IMPACT_LABEL)

    undone.assert_called_once_with(
        SCALE_WRITE_UNDO_INCOMPLETE_MSG.format(action=action.value, entity=IMPACT_LABEL.singular))
