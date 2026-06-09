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
Unit tests for the SpecialType REST routes

Each handler is unwrapped past its auth decorators and driven inside a Flask test_request_context
with the query string it reads. TypesManager and the response / schema collaborators are patched at
the route module path; only the route glue (parameter validation, status-code mapping, branch
selection) is exercised - no Mongo and no blueprint registration run
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager import TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.special_type_routes import (
    check_special_type_exist,
    get_special_types,
    get_special_type_schema,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.special_type_routes'

VALID_SPECIAL_TYPE: str = SpecialType.SUBNET.value
INVALID_SPECIAL_TYPE: str = 'NOT_A_SPECIAL_TYPE'

HTTP_BAD_REQUEST: int = 400
HTTP_SERVER_ERROR: int = 500


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / verify_api_access / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='mgr')
def fixture_mgr() -> MagicMock:
    """A MagicMock standing in for a TypesManager, returned by the patched ManagerProvider."""
    return MagicMock(spec=TypesManager)


@pytest.fixture(name='patched_manager_provider')
def fixture_patched_manager_provider(mgr: MagicMock) -> Any:
    """Patches ``ManagerProvider.get_manager`` at the route module path to return ``mgr``."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr) as provider:
        yield provider


# -------------------------------------------------------------------------------------------------------------------- #
#                                              check_special_type_exist                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def _call_exist(flask_app: Flask, query: str) -> Any:
    """Drives the unwrapped check_special_type_exist handler with the given query string."""
    with flask_app.test_request_context(f'/exist?{query}'):
        return _unwrap(check_special_type_exist)(request_user=MagicMock())


def test_exist_missing_param_maps_to_400(flask_app: Flask) -> None:
    """Omitting ``special_type`` aborts 400 before any manager lookup."""
    with pytest.raises(HTTPException) as exc_info:
        _call_exist(flask_app, '')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_exist_invalid_special_type_maps_to_400(flask_app: Flask) -> None:
    """A value that is not a known SpecialType aborts 400."""
    with pytest.raises(HTTPException) as exc_info:
        _call_exist(flask_app, f'special_type={INVALID_SPECIAL_TYPE}')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_exist_returns_manager_result(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A valid SpecialType returns the manager's existence flag via DefaultResponse."""
    del patched_manager_provider
    mgr.check_special_type_exists.return_value = True

    with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        _call_exist(flask_app, f'special_type={VALID_SPECIAL_TYPE}')

    response_ctor.assert_called_once_with(True)


def test_exist_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """An unexpected manager failure maps to HTTP 500."""
    del patched_manager_provider
    mgr.check_special_type_exists.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as exc_info:
        _call_exist(flask_app, f'special_type={VALID_SPECIAL_TYPE}')

    assert exc_info.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 get_special_types                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _call_get_types(flask_app: Flask, query: str) -> Any:
    """Drives the unwrapped get_special_types handler with the given query string."""
    with flask_app.test_request_context(f'/?{query}'):
        return _unwrap(get_special_types)(request_user=MagicMock())


def test_get_types_returns_all_when_not_available(flask_app: Flask, mgr: MagicMock) -> None:
    """Without ``available=true`` the full SpecialType set is returned and no distinct query runs."""
    with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        _call_get_types(flask_app, '')

    response_ctor.assert_called_once_with(SpecialType.get_special_types())
    mgr.get_distinct.assert_not_called()


def test_get_types_returns_unused_when_available(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """With ``available=true`` only the SpecialTypes not yet assigned are returned."""
    del patched_manager_provider
    mgr.get_distinct.return_value = [VALID_SPECIAL_TYPE]

    with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        _call_get_types(flask_app, 'available=true')

    mgr.get_distinct.assert_called_once()
    returned = response_ctor.call_args.args[0]
    assert VALID_SPECIAL_TYPE not in returned


def test_get_types_unexpected_error_maps_to_500(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """An unexpected failure resolving the unused types maps to HTTP 500."""
    del patched_manager_provider
    mgr.get_distinct.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as exc_info:
        _call_get_types(flask_app, 'available=true')

    assert exc_info.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_special_type_schema                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def _call_schema(flask_app: Flask, query: str) -> Any:
    """Drives the unwrapped get_special_type_schema handler with the given query string."""
    with flask_app.test_request_context(f'/schema?{query}'):
        return _unwrap(get_special_type_schema)(request_user=MagicMock())


def test_schema_missing_param_maps_to_400(flask_app: Flask) -> None:
    """Omitting ``special_type`` aborts 400."""
    with pytest.raises(HTTPException) as exc_info:
        _call_schema(flask_app, '')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_schema_invalid_special_type_maps_to_400(flask_app: Flask) -> None:
    """A value that is not a known SpecialType aborts 400."""
    with pytest.raises(HTTPException) as exc_info:
        _call_schema(flask_app, f'special_type={INVALID_SPECIAL_TYPE}')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_schema_returns_provider_schema(flask_app: Flask) -> None:
    """A valid SpecialType returns the schema produced by SchemaProvider via DefaultResponse."""
    sentinel_schema = {'fields': []}

    with patch(f'{ROUTE_PATH}.SchemaProvider') as provider_cls, \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        provider_cls.return_value.get_schema.return_value = sentinel_schema
        _call_schema(flask_app, f'special_type={VALID_SPECIAL_TYPE}')

    response_ctor.assert_called_once_with(sentinel_schema)


def test_schema_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """An unexpected failure building the schema maps to HTTP 500."""
    with patch(f'{ROUTE_PATH}.SchemaProvider') as provider_cls:
        provider_cls.return_value.get_schema.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as exc_info:
            _call_schema(flask_app, f'special_type={VALID_SPECIAL_TYPE}')

    assert exc_info.value.code == HTTP_SERVER_ERROR
