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
Unit tests for the bulk-delete route of cmdb ... isms_routes.threat_routes

Pure tests: no Mongo, no blueprint registration. The handler is unwrapped from its decorator chain
and driven against a MagicMock ThreatManager (resolved via a patched ManagerProvider), with the
response factory patched at the route module path. Only the route's own orchestration is exercised -
the used/unused partition (via the shared bulk_delete_reporting_in_use helper), that in-use ids are
never deleted, that only actually-removed ids are reported, and the manager-error -> HTTP mapping.
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.isms_routes.threat_routes import delete_many_isms_threats

from cmdb.errors.manager.threat_manager import (
    ThreatManagerGetError,
    ThreatManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.isms_routes.threat_routes'

THREAT_ID_A: int = 301
THREAT_ID_B: int = 302
THREAT_ID_C: int = 303
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
    """A mock ThreatManager the route resolves via ManagerProvider."""
    return MagicMock(name='threat_manager')


@pytest.fixture(name='patched_provider')
def fixture_patched_provider(manager: MagicMock) -> Any:
    """Patches ``ManagerProvider.get_manager`` to return the mock manager."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager) as p:
        yield p


class TestDeleteManyThreats:
    """``delete_many_isms_threats`` deletes the unused targets and reports the still-used ones."""

    @staticmethod
    def _call(flask_app: Flask, public_ids: str) -> Any:
        """Drives the unwrapped handler inside a DELETE request context."""
        with flask_app.test_request_context('/', method='DELETE'):
            return _unwrap(delete_many_isms_threats)(public_ids=public_ids, request_user=MagicMock())

    def test_deletes_unused_and_reports_in_use(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """In-use ids are left untouched and reported; unused ids are deleted."""
        del patched_provider
        manager.get_used_threat_ids.return_value = {THREAT_ID_B}
        manager.delete_item.return_value = True

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{THREAT_ID_A},{THREAT_ID_B},{THREAT_ID_C}')

        # the whole requested batch drives the single used-check query
        manager.get_used_threat_ids.assert_called_once_with([THREAT_ID_A, THREAT_ID_B, THREAT_ID_C])
        deleted_calls = [call.args[0] for call in manager.delete_item.call_args_list]
        assert THREAT_ID_B not in deleted_calls
        assert sorted(deleted_calls) == [THREAT_ID_A, THREAT_ID_C]
        response_cls.assert_called_once_with({'successfully': [THREAT_ID_A, THREAT_ID_C], 'in_use': [THREAT_ID_B]})

    def test_non_existent_ids_are_not_reported_as_deleted(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """delete_item returning False (id did not exist) keeps that id out of the deleted list."""
        del patched_provider
        manager.get_used_threat_ids.return_value = set()
        manager.delete_item.side_effect = lambda public_id: public_id == THREAT_ID_A

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{THREAT_ID_A},{MISSING_ID}')

        response_cls.assert_called_once_with({'successfully': [THREAT_ID_A], 'in_use': []})

    def test_all_in_use_deletes_nothing(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """When every requested id is in use, nothing is deleted and all are reported."""
        del patched_provider
        manager.get_used_threat_ids.return_value = {THREAT_ID_A, THREAT_ID_B}

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, f'{THREAT_ID_A},{THREAT_ID_B}')

        manager.delete_item.assert_not_called()
        response_cls.assert_called_once_with({'successfully': [], 'in_use': [THREAT_ID_A, THREAT_ID_B]})

    def test_invalid_id_aborts_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A non-integer id in the list is rejected 400 by extract_public_ids."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, f'{THREAT_ID_A},not-an-int')

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_used_lookup_error_maps_to_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A ThreatManagerGetError from the used-check surfaces as 400."""
        del patched_provider
        manager.get_used_threat_ids.side_effect = ThreatManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(THREAT_ID_A))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_delete_error_maps_to_400(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A ThreatManagerDeleteError from a delete surfaces as 400."""
        del patched_provider
        manager.get_used_threat_ids.return_value = set()
        manager.delete_item.side_effect = ThreatManagerDeleteError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(THREAT_ID_A))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, manager: MagicMock, patched_provider: Any,
    ) -> None:
        """A generic exception surfaces as 500."""
        del patched_provider
        manager.get_used_threat_ids.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, str(THREAT_ID_A))

        assert excinfo.value.code == HTTP_SERVER_ERROR
