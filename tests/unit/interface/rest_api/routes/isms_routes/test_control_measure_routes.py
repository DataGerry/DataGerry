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
Unit tests for the bulk-delete route of cmdb ... isms_routes.control_measure_routes

Pure tests: no Mongo, no blueprint registration. The handler is unwrapped from its decorator chain
and driven against a MagicMock ControlMeasureManager (resolved via a patched ManagerProvider), with
the response factory patched at the route module path. Only the route's own orchestration is
exercised - the used/unused partition, that in-use ids are never deleted, that only actually-removed
ids are reported, and the manager-error -> HTTP status mapping.
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.errors.manager import BaseManagerDeleteError
from cmdb.interface.rest_api.routes.isms_routes.control_measure_routes import delete_many_isms_control_measures

from cmdb.errors.manager.control_measure_manager import (
    CONTROL_MEASURE_MANAGER_ERRORS,
    ControlMeasureManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.isms_routes.control_measure_routes'

CONTROL_ID_A: int = 101
CONTROL_ID_B: int = 102
CONTROL_ID_C: int = 103
MISSING_ID: int = 999

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
    """A mock ControlMeasureManager the route resolves via ManagerProvider."""
    manager = MagicMock(name='control_measure_manager')
    manager.exceptions = CONTROL_MEASURE_MANAGER_ERRORS
    # Every requested id is stored except MISSING_ID
    manager.find.side_effect = lambda criteria: [
        {'public_id': public_id} for public_id in sorted(criteria['public_id']['$in'])
        if public_id != MISSING_ID
    ]

    return manager


@pytest.fixture(name='patched_provider')
def fixture_patched_provider(manager: MagicMock) -> Any:
    """Patches ``ManagerProvider.get_manager`` to return the mock manager."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager) as p:
        yield p


class TestDeleteManyControlMeasures:
    """``delete_many_isms_control_measures`` deletes the unused targets and reports the still-used ones."""

    @staticmethod
    def _call(flask_app: Flask, public_ids: str) -> Any:
        """Drives the unwrapped handler inside a DELETE request context."""
        with flask_app.test_request_context('/', method='DELETE'):
            return _unwrap(delete_many_isms_control_measures)(public_ids=public_ids, request_user=MagicMock())

    def test_deletes_unused_and_reports_in_use(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """In-use ids are left untouched and reported; unused ids are deleted."""
        del patched_provider
        manager.get_used_control_measure_ids.side_effect = lambda ids: {CONTROL_ID_B} & set(ids)

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{CONTROL_ID_A},{CONTROL_ID_B},{CONTROL_ID_C}')

        # the in-use control is never deleted
        # the whole requested batch drives the single used-check query
        first_check = manager.get_used_control_measure_ids.call_args_list[0]
        assert first_check.args == ([CONTROL_ID_A, CONTROL_ID_B, CONTROL_ID_C],)
        manager.delete_many.assert_called_once_with({'public_id': {'$in': [CONTROL_ID_A, CONTROL_ID_C]}})
        # and the response splits deleted vs still-in-use
        response_cls.assert_called_once_with({'successfully': [CONTROL_ID_A, CONTROL_ID_C], 'in_use': [CONTROL_ID_B]})

    def test_non_existent_ids_are_not_reported_as_deleted(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """An id the read does not find is neither deleted nor reported."""
        del patched_provider
        manager.get_used_control_measure_ids.return_value = set()

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{CONTROL_ID_A},{MISSING_ID}')

        response_cls.assert_called_once_with({'successfully': [CONTROL_ID_A], 'in_use': []})

    def test_all_in_use_deletes_nothing(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """When every requested id is in use, nothing is deleted and all are reported."""
        del patched_provider
        manager.get_used_control_measure_ids.return_value = {CONTROL_ID_A, CONTROL_ID_B}

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{CONTROL_ID_A},{CONTROL_ID_B}')

        manager.delete_many.assert_not_called()
        response_cls.assert_called_once_with({'successfully': [], 'in_use': [CONTROL_ID_A, CONTROL_ID_B]})

    def test_invalid_id_aborts_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A non-integer id in the list is rejected 400 by extract_public_ids."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, f'{CONTROL_ID_A},not-an-int')

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_used_lookup_error_maps_to_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A ControlMeasureManagerGetError from the used-check surfaces as 400."""
        del patched_provider
        manager.get_used_control_measure_ids.side_effect = ControlMeasureManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(CONTROL_ID_A))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_delete_error_maps_to_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A ControlMeasureManagerDeleteError from a delete surfaces as 400."""
        del patched_provider
        manager.get_used_control_measure_ids.return_value = set()
        manager.delete_many.side_effect = BaseManagerDeleteError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(CONTROL_ID_A))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A generic exception surfaces as 500."""
        del patched_provider
        manager.get_used_control_measure_ids.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(CONTROL_ID_A))

        assert excinfo.value.code == HTTP_SERVER_ERROR
