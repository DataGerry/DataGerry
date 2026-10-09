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
Unit tests for the Automation create's building blocks in oc_scheduler_helper

``record_remote_create`` against a real WriteLedger: the undo deletes the remote object, and the ledger's residue
reports exactly what the remote service did not acknowledge. ``require_portal_registration`` turns the portal's False
into an error. ``read_automation_body`` refuses an incomplete body before anything is written
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.write_ledger import WriteLedger
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcAutomationMessage
from cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_helper import (
    read_automation_body,
    record_remote_create,
    require_portal_registration,
)
from cmdb.errors.dg_service_portal import DgServicePortalError, DgServicePortalSaveError
# -------------------------------------------------------------------------------------------------------------------- #

SERVICE: str = 'OpenCelium'
DESCRIPTION: str = 'connection 10'


class TestRecordRemoteCreate:
    """A remote object undone by deleting it, verified by the delete's own answer"""

    def test_the_undo_deletes_the_object(self) -> None:
        """An acknowledged delete leaves no residue"""
        ledger, delete = WriteLedger(), MagicMock(return_value=True)
        record_remote_create(ledger, SERVICE, DESCRIPTION, delete)

        assert not ledger.undo()
        delete.assert_called_once_with()

    def test_nothing_runs_until_the_undo(self) -> None:
        """Recording is not deleting"""
        delete = MagicMock(return_value=True)
        record_remote_create(WriteLedger(), SERVICE, DESCRIPTION, delete)

        delete.assert_not_called()

    @pytest.mark.parametrize('delete', [MagicMock(return_value=False), MagicMock(side_effect=RuntimeError('down'))],
                             ids=['refused', 'raised'])
    def test_an_unacknowledged_delete_is_residue_naming_the_object(self, delete: MagicMock) -> None:
        """The residue names the service and the object - what the 500 hands the caller"""
        ledger = WriteLedger()
        record_remote_create(ledger, SERVICE, DESCRIPTION, delete)

        residue: list[dict[str, Any]] = [item.to_json() for item in ledger.undo()]

        assert len(residue) == 1
        assert SERVICE in str(residue[0]) and DESCRIPTION in str(residue[0])

    def test_several_creates_are_undone_newest_first(self) -> None:
        """The order the delete route uses: the scheduler before its connection"""
        ledger, calls = WriteLedger(), []
        record_remote_create(ledger, SERVICE, 'connection 10', lambda: calls.append('connection') or True)
        record_remote_create(ledger, SERVICE, 'scheduler 5', lambda: calls.append('scheduler') or True)

        assert not ledger.undo()
        assert calls == ['scheduler', 'connection']


class TestRequirePortalRegistration:
    """The portal's bool, made into an error"""

    def test_an_acknowledged_registration_passes(self) -> None:
        """True carries on"""
        assert require_portal_registration(True, DESCRIPTION) is None

    def test_a_refused_registration_raises_naming_it(self) -> None:
        """A portal error the route maps to its 500; the message names what was not registered"""
        with pytest.raises(DgServicePortalSaveError) as exc_info:
            require_portal_registration(False, DESCRIPTION)

        assert isinstance(exc_info.value, DgServicePortalError)
        assert DESCRIPTION in str(exc_info.value)


class TestReadAutomationBody:
    """Everything the create reads is checked before it writes"""

    @pytest.fixture(name='request_context', autouse=True)
    def fixture_request_context(self):
        """abort needs an application context"""
        with BaseCmdbApp(__name__).app_context():
            yield

    def test_a_complete_body_is_returned_in_its_parts(self) -> None:
        """The connection and the scheduler, as sent"""
        connection, scheduler = {'title': 'conn'}, {'title': 'sched'}

        assert read_automation_body({'connection': connection, 'scheduler': scheduler}) == (connection, scheduler)

    @pytest.mark.parametrize(('body', 'message'), [
        ({'connection': {'title': 'c'}, 'scheduler': {}}, None),
        ({'connection': {'title': 'c'}, 'scheduler': {'title': ''}}, OcAutomationMessage.NO_SCHEDULER_TITLE.value),
        ({'connection': {'title': ''}, 'scheduler': {'title': 's'}}, OcAutomationMessage.NO_CONNECTION_TITLE.value),
        ({'connection': {'x': 1}, 'scheduler': {'title': 's'}}, OcAutomationMessage.NO_CONNECTION_TITLE.value),
        (None, None),
        (['not', 'an', 'object'], None),
    ], ids=['empty-scheduler', 'blank-scheduler-title', 'blank-connection-title', 'no-connection-title', 'no-body',
            'list-body'])
    def test_an_incomplete_body_is_a_400(self, body: Any, message: str | None) -> None:
        """Before the connection exists"""
        with pytest.raises(HTTPException) as exc_info:
            read_automation_body(body)

        assert exc_info.value.code == 400
        if message:
            assert exc_info.value.description == message
