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
Unit tests for the bulk-delete route of cmdb ... isms_routes.risk_routes

Pure tests: no Mongo, no blueprint registration. The handler is unwrapped from its decorator chain
and driven against a MagicMock RiskManager (resolved via a patched ManagerProvider), with the
response factory patched at the route module path. Only the route's own orchestration is exercised -
that it forwards the parsed ids to the batched cascade and packs the returned (ids, ra_count,
cma_count) into the response, plus the manager-error -> HTTP mapping.
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.isms_routes.risk_routes import delete_many_isms_risks

from cmdb.errors.manager.risk_manager import RiskManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.isms_routes.risk_routes'

RISK_ID_A: int = 401
RISK_ID_B: int = 402

HTTP_BAD_REQUEST: int = 400
HTTP_SERVER_ERROR: int = 500


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / protect / verify_api_access / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='manager')
def fixture_manager() -> MagicMock:
    """A mock RiskManager the route resolves via ManagerProvider."""
    return MagicMock(name='risk_manager')


@pytest.fixture(name='patched_provider')
def fixture_patched_provider(manager: MagicMock) -> Any:
    """Patches ``ManagerProvider.get_manager`` to return the mock manager."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager) as p:
        yield p


class TestDeleteManyRisks:
    """``delete_many_isms_risks`` forwards the batch to the cascade and reports ids + cascade counts."""

    @staticmethod
    def _call(flask_app: Flask, public_ids: str) -> Any:
        """Drives the unwrapped handler inside a DELETE request context."""
        with flask_app.test_request_context('/', method='DELETE'):
            return _unwrap(delete_many_isms_risks)(public_ids=public_ids, request_user=MagicMock())

    def test_reports_deleted_ids_and_cascade_counts(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """The deleted Risk ids (sorted) and the RA / CMA cascade counts are returned via DefaultResponse."""
        del patched_provider
        manager.delete_many_with_follow_up.return_value = ([RISK_ID_B, RISK_ID_A], 4, 7)

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{RISK_ID_A},{RISK_ID_B}')

        manager.delete_many_with_follow_up.assert_called_once_with([RISK_ID_A, RISK_ID_B])
        response_cls.assert_called_once_with({
            'successfully': [RISK_ID_A, RISK_ID_B],
            'deleted_risk_assessments': 4,
            'deleted_control_measure_assignments': 7,
        })

    def test_invalid_id_aborts_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A non-integer id in the list is rejected 400 by extract_public_ids."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, f'{RISK_ID_A},not-an-int')

        assert excinfo.value.code == HTTP_BAD_REQUEST
        manager.delete_many_with_follow_up.assert_not_called()

    def test_delete_error_maps_to_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A RiskManagerDeleteError from the cascade surfaces as 400."""
        del patched_provider
        manager.delete_many_with_follow_up.side_effect = RiskManagerDeleteError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(RISK_ID_A))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A generic exception surfaces as 500."""
        del patched_provider
        manager.delete_many_with_follow_up.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(RISK_ID_A))

        assert excinfo.value.code == HTTP_SERVER_ERROR
