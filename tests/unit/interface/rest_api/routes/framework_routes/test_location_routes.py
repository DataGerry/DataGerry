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
Unit tests for the CmdbLocation REST route handlers

Each handler is unwrapped past its auth / validation / collection-parameter decorators and
driven inside a Flask test_request_context, with the LocationsManager / TypesManager /
ObjectsManager (resolved via a patched ManagerProvider) and the response factories / helpers
patched at the route module path. No Mongo and no blueprint registration runs - only the
route glue (manager-call ordering, branch selection, and status-code mapping to 400/404/500)
is exercised.
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, BadRequest

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes import (
    insert_cmdb_location,
    get_cmdb_locations,
    get_cmdb_locations_tree,
    get_cmdb_location_tree_roots,
    get_cmdb_location_tree_children,
    get_cmdb_location_tree_path,
    search_cmdb_location_tree,
    get_cmdb_location,
    get_cmdb_location_for_object,
    get_cmdb_location_parent,
    get_cmdb_children,
    update_cmdb_location_for_object,
    move_cmdb_location_for_object,
    move_cmdb_locations,
    delete_cmdb_location_for_object,
)
from cmdb.database.predefined_data.predefined_data_constants import RootLocationDefault

from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.locations_manager import (
    LocationsManagerInsertError,
    LocationsManagerGetError,
    LocationsManagerUpdateError,
    LocationsManagerDeleteError,
    LocationsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'

LOCATION_PUBLIC_ID: int = 7
OBJECT_ID: int = 42
PARENT_ID: int = 3
TYPE_ID: int = 11
MISSING_OBJECT_ID: int = 9999
TOTAL_LOCATIONS: int = 2
RESOLVED_NAME: str = 'resolved-name'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

INSERT_PAYLOAD: dict[str, Any] = {'object_id': OBJECT_ID, 'parent': PARENT_ID, 'type_id': TYPE_ID, 'name': 'srv'}
UPDATE_PAYLOAD: dict[str, Any] = {'object_id': OBJECT_ID, 'parent': PARENT_ID, 'name': 'srv'}
SAMPLE_LOCATION_DICT: dict[str, Any] = {'public_id': LOCATION_PUBLIC_ID, 'object_id': OBJECT_ID, 'parent': PARENT_ID}


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / validate / protect / verify_api_access / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='managers')
def fixture_managers() -> dict[ManagerType, MagicMock]:
    """
    Separate mocks for each manager type the routes resolve via ManagerProvider.

    The locations manager returns a realistic node dict rather than a bare MagicMock: the move / delete
    routes now read `managed_by` off it (a feature-owned node may not be moved by hand), and on a MagicMock
    every key reads as truthy - which would make every move look feature-owned.
    """
    locations_manager = MagicMock(name='locations_manager')
    locations_manager.get_location_for_object.return_value = {'public_id': 1, 'object_id': 1, 'parent': 1}

    return {
        ManagerType.TYPES: MagicMock(name='types_manager'),
        ManagerType.LOCATIONS: locations_manager,
        ManagerType.OBJECTS: MagicMock(name='objects_manager'),
    }


@pytest.fixture(name='patched_provider')
def fixture_patched_provider(managers: dict[ManagerType, MagicMock]) -> Any:
    """Patches ``ManagerProvider.get_manager`` to return the per-type mock from ``managers``."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, user: managers[mtype]) as p:
        yield p


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 insert_cmdb_location                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertCmdbLocation:
    """``insert_cmdb_location`` validates the type, resolves the name, then inserts."""

    @staticmethod
    def _call(flask_app: Flask, data: dict[str, Any]) -> Any:
        """Drives the unwrapped handler inside a POST request context."""
        with flask_app.test_request_context('/', method='POST'):
            return _unwrap(insert_cmdb_location)(data=data, request_user=MagicMock())

    def test_inserts_with_resolved_name_and_type_metadata(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The happy path resolves the name, copies type metadata, and returns the new public_id."""
        del patched_provider
        managers[ManagerType.TYPES].get_type.return_value = {'public_id': TYPE_ID}
        managers[ManagerType.LOCATIONS].insert_location.return_value = LOCATION_PUBLIC_ID
        type_mock = MagicMock(label='Server', selectable_as_parent=True)
        type_mock.get_icon.return_value = 'fas fa-server'
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.CmdbType.from_data', return_value=type_mock), \
             patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME), \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, dict(INSERT_PAYLOAD))

        written = managers[ManagerType.LOCATIONS].insert_location.call_args.args[0]
        assert written['name'] == RESOLVED_NAME
        assert written['type_label'] == 'Server'
        response_ctor.assert_called_once_with(LOCATION_PUBLIC_ID)
        assert result is sentinel_response

    def test_missing_required_field_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A body missing a required id is a 400 (not a 500 from the generic handler)."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'parent': PARENT_ID, 'type_id': TYPE_ID})  # no object_id

        assert excinfo.value.code == HTTP_BAD_REQUEST
        managers[ManagerType.LOCATIONS].insert_location.assert_not_called()

    def test_malformed_required_field_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A non-integer id value is a 400 (not a 500 from the generic handler)."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_id': 'not-an-int', 'parent': PARENT_ID, 'type_id': TYPE_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST
        managers[ManagerType.LOCATIONS].insert_location.assert_not_called()

    def test_missing_type_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A type that cannot be found aborts 404 before any insert happens."""
        del patched_provider
        managers[ManagerType.TYPES].get_type.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(INSERT_PAYLOAD))

        assert excinfo.value.code == HTTP_NOT_FOUND
        managers[ManagerType.LOCATIONS].insert_location.assert_not_called()

    def test_types_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``TypesManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.TYPES].get_type.side_effect = TypesManagerGetError('lookup failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(INSERT_PAYLOAD))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_objects_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An ``ObjectsManagerGetError`` surfacing from name resolution maps to HTTP 400."""
        del patched_provider
        managers[ManagerType.TYPES].get_type.return_value = {'public_id': TYPE_ID}

        with patch(f'{ROUTE_PATH}.CmdbType.from_data', return_value=MagicMock()), \
             patch(f'{ROUTE_PATH}.resolve_location_name', side_effect=ObjectsManagerGetError('boom')):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, dict(INSERT_PAYLOAD))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_insert_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerInsertError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.TYPES].get_type.return_value = {'public_id': TYPE_ID}
        managers[ManagerType.LOCATIONS].insert_location.side_effect = LocationsManagerInsertError('write failed')

        with patch(f'{ROUTE_PATH}.CmdbType.from_data', return_value=MagicMock()), \
             patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, dict(INSERT_PAYLOAD))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.TYPES].get_type.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(INSERT_PAYLOAD))

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_cmdb_locations                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocations:
    """``get_cmdb_locations`` iterates and serializes each row, mapping failures to 400/500."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_locations)(params=MagicMock(), request_user=MagicMock())

    def test_serializes_each_row_via_to_json(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Every iterated row is serialized with ``CmdbLocation.to_json`` into the GetMultiResponse."""
        del patched_provider
        iteration_result = MagicMock(results=['raw1', 'raw2'], total=TOTAL_LOCATIONS)
        managers[ManagerType.LOCATIONS].iterate.return_value = iteration_result
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}), \
             patch(f'{ROUTE_PATH}.CmdbLocation.to_json', side_effect=lambda x: f'json-{x}'), \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app)

        assert response_ctor.call_args.args[0] == ['json-raw1', 'json-raw2']
        assert response_ctor.call_args.args[1] == TOTAL_LOCATIONS
        assert result is sentinel_response

    def test_iteration_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerIterationError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].iterate.side_effect = LocationsManagerIterationError('bad pipeline')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].iterate.side_effect = RuntimeError('boom')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                               get_cmdb_locations_tree                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocationsTree:
    """``get_cmdb_locations_tree`` delegates forest assembly to ``build_location_forest``."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/tree', method='GET'):
            return _unwrap(get_cmdb_locations_tree)(params=MagicMock(), request_user=MagicMock())

    def test_passes_serialized_rows_to_build_location_forest(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The to_json'd rows are handed to ``build_location_forest`` and its output is the response body."""
        del patched_provider
        iteration_result = MagicMock(results=['raw1'], total=TOTAL_LOCATIONS)
        managers[ManagerType.LOCATIONS].iterate.return_value = iteration_result
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}), \
             patch(f'{ROUTE_PATH}.CmdbLocation.to_json', side_effect=lambda x: f'json-{x}'), \
             patch(f'{ROUTE_PATH}.build_location_forest', return_value=['forest']) as forest_mock, \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app)

        forest_mock.assert_called_once_with(['json-raw1'])
        assert response_ctor.call_args.args[0] == ['forest']
        assert result is sentinel_response

    def test_iteration_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerIterationError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].iterate.side_effect = LocationsManagerIterationError('bad pipeline')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].iterate.side_effect = RuntimeError('boom')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_cmdb_location                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocation:
    """``get_cmdb_location`` returns the doc, 404s on miss and 400/500s on failure."""

    @staticmethod
    def _call(flask_app: Flask, public_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_location)(public_id=public_id, request_user=MagicMock())

    def test_returns_document(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A found document is wrapped in a DefaultResponse."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location.return_value = SAMPLE_LOCATION_DICT
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, LOCATION_PUBLIC_ID)

        response_ctor.assert_called_once_with(SAMPLE_LOCATION_DICT)
        assert result is sentinel_response

    def test_missing_location_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A missing id aborts 404."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location.side_effect = LocationsManagerGetError('lookup failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_cmdb_location_for_object                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocationForObject:
    """``get_cmdb_location_for_object`` returns the object's location or 404s on miss."""

    @staticmethod
    def _call(flask_app: Flask, object_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_location_for_object)(object_id=object_id, request_user=MagicMock())

    def test_returns_location(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A found location is wrapped in a DefaultResponse."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, OBJECT_ID)

        response_ctor.assert_called_once_with(SAMPLE_LOCATION_DICT)
        assert result is sentinel_response

    def test_missing_location_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An object with no location aborts 404."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, MISSING_OBJECT_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                               get_cmdb_location_parent                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocationParent:
    """``get_cmdb_location_parent`` resolves the object's location then its parent location."""

    @staticmethod
    def _call(flask_app: Flask, object_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_location_parent)(object_id=object_id, request_user=MagicMock())

    def test_returns_parent_location(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The parent referenced by the object's location is resolved and returned."""
        del patched_provider
        parent_doc = {'public_id': PARENT_ID}
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = {'parent': PARENT_ID}
        managers[ManagerType.LOCATIONS].get_location.return_value = parent_doc

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app, OBJECT_ID)

        managers[ManagerType.LOCATIONS].get_location.assert_called_once_with(PARENT_ID)
        response_ctor.assert_called_once_with(parent_doc)

    def test_no_location_returns_none_without_parent_lookup(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """When the object has no location the response carries None and no parent lookup runs."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = None

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app, OBJECT_ID)

        response_ctor.assert_called_once_with(None)
        managers[ManagerType.LOCATIONS].get_location.assert_not_called()

    def test_missing_parent_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A dangling parent reference (parent location not found) aborts 404."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = {'parent': PARENT_ID}
        managers[ManagerType.LOCATIONS].get_location.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_cmdb_children                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbChildren:
    """``get_cmdb_children`` returns the direct child locations serialized to dicts."""

    @staticmethod
    def _call(flask_app: Flask, object_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_children)(object_id=object_id, request_user=MagicMock())

    def test_serializes_each_child_via_to_json(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Direct children are fetched by parent public_id and serialized with ``to_json``."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = {'public_id': LOCATION_PUBLIC_ID}
        managers[ManagerType.LOCATIONS].get_locations_by.return_value = ['child1', 'child2']
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.CmdbLocation.to_json', side_effect=lambda x: f'json-{x}'), \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, OBJECT_ID)

        managers[ManagerType.LOCATIONS].get_locations_by.assert_called_once_with(parent=LOCATION_PUBLIC_ID)
        response_ctor.assert_called_once_with(['json-child1', 'json-child2'])
        assert result is sentinel_response

    def test_no_location_returns_empty_children(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An object with no location returns an empty children list without a children lookup."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = None

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app, OBJECT_ID)

        response_ctor.assert_called_once_with([])
        managers[ManagerType.LOCATIONS].get_locations_by.assert_not_called()

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_cmdb_location_tree_roots                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocationTreeRoots:
    """``get_cmdb_location_tree_roots`` returns the root's direct children as flagged tree nodes."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_location_tree_roots)(request_user=MagicMock())

    def test_fetches_root_children_and_builds_level(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The root's direct children are serialized and passed to build_location_level, then wrapped."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_by.return_value = ['loc1', 'loc2']
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.CmdbLocation.to_json', side_effect=lambda x: f'json-{x}'), \
             patch(f'{ROUTE_PATH}.build_location_level', return_value=['node1', 'node2']) as build_level, \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app)

        managers[ManagerType.LOCATIONS].get_locations_by.assert_called_once_with(parent=RootLocationDefault.PUBLIC_ID)
        build_level.assert_called_once_with(['json-loc1', 'json-loc2'], managers[ManagerType.LOCATIONS])
        response_ctor.assert_called_once_with(['node1', 'node2'])
        assert result is sentinel_response

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_by.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_by.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                        get_cmdb_location_tree_children                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocationTreeChildren:
    """``get_cmdb_location_tree_children`` returns a location's direct children as flagged tree nodes."""

    @staticmethod
    def _call(flask_app: Flask, public_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_location_tree_children)(public_id=public_id, request_user=MagicMock())

    def test_fetches_children_by_location_id_and_builds_level(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Children are fetched by the location's public_id and passed to build_location_level."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_by.return_value = ['loc1']
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.CmdbLocation.to_json', side_effect=lambda x: f'json-{x}'), \
             patch(f'{ROUTE_PATH}.build_location_level', return_value=['node1']) as build_level, \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, LOCATION_PUBLIC_ID)

        managers[ManagerType.LOCATIONS].get_locations_by.assert_called_once_with(parent=LOCATION_PUBLIC_ID)
        build_level.assert_called_once_with(['json-loc1'], managers[ManagerType.LOCATIONS])
        response_ctor.assert_called_once_with(['node1'])
        assert result is sentinel_response

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_by.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_by.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                            update_cmdb_location_for_object                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateCmdbLocationForObject:
    """``update_cmdb_location_for_object`` resolves the name then writes through the manager."""

    @staticmethod
    def _call(flask_app: Flask, data: dict[str, Any]) -> Any:
        """Drives the unwrapped handler inside a PUT request context."""
        with flask_app.test_request_context('/update_location', method='PUT'):
            return _unwrap(update_cmdb_location_for_object)(data=data, request_user=MagicMock())

    def test_updates_with_resolved_name(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The happy path resolves the name and forwards the params to ``update_location``."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT

        with patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME), \
             patch(f'{ROUTE_PATH}.UpdateSingleResponse'):
            self._call(flask_app, dict(UPDATE_PAYLOAD))

        managers[ManagerType.LOCATIONS].update_location.assert_called_once()
        written = managers[ManagerType.LOCATIONS].update_location.call_args.args[1]
        assert written['name'] == RESOLVED_NAME
        assert written['parent'] == PARENT_ID

    def test_mirrors_the_parent_onto_the_object_location_field(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The object's location field is set to the same parent as the node (no desync)."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT

        with patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME), \
             patch(f'{ROUTE_PATH}.validate_object_location_change'), \
             patch(f'{ROUTE_PATH}.UpdateSingleResponse'):
            self._call(flask_app, dict(UPDATE_PAYLOAD))

        managers[ManagerType.OBJECTS].set_location_field_for_objects.assert_called_once_with(
            [OBJECT_ID], PARENT_ID
        )

    def test_invalid_parent_placement_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A parent rejected by placement validation surfaces as 400 and nothing is written."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT

        with patch(f'{ROUTE_PATH}.validate_object_location_change', side_effect=BadRequest('bad parent')):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, dict(UPDATE_PAYLOAD))

        assert excinfo.value.code == HTTP_BAD_REQUEST
        managers[ManagerType.LOCATIONS].update_location.assert_not_called()

    def test_missing_required_field_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A body missing a required id is a 400 (not a 500 from the generic handler)."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'parent': PARENT_ID, 'name': 'srv'})  # no object_id

        assert excinfo.value.code == HTTP_BAD_REQUEST
        managers[ManagerType.LOCATIONS].update_location.assert_not_called()

    def test_missing_location_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A missing target location aborts 404 without writing."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(UPDATE_PAYLOAD))

        assert excinfo.value.code == HTTP_NOT_FOUND
        managers[ManagerType.LOCATIONS].update_location.assert_not_called()

    def test_objects_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An ``ObjectsManagerGetError`` from name resolution maps to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT

        with patch(f'{ROUTE_PATH}.resolve_location_name', side_effect=ObjectsManagerGetError('boom')):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, dict(UPDATE_PAYLOAD))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_update_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerUpdateError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT
        managers[ManagerType.LOCATIONS].update_location.side_effect = LocationsManagerUpdateError('write failed')

        with patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, dict(UPDATE_PAYLOAD))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(UPDATE_PAYLOAD))

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                             search_cmdb_location_tree                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSearchCmdbLocationTree:
    """``search_cmdb_location_tree`` reads the query, runs the name search and builds the forest."""

    @staticmethod
    def _call(flask_app: Flask, query: str) -> Any:
        """Drives the unwrapped handler inside a GET request context carrying ?query=."""
        with flask_app.test_request_context(f'/?query={query}', method='GET'):
            return _unwrap(search_cmdb_location_tree)(request_user=MagicMock())

    def test_searches_and_builds_pruned_forest(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The search result + its has-children set are handed to build_location_forest."""
        del patched_provider
        matches = [{'public_id': 5, 'name': 'rack', 'parent': 1}]
        managers[ManagerType.LOCATIONS].search_locations_with_ancestors.return_value = matches
        managers[ManagerType.LOCATIONS].get_parents_with_children.return_value = {5}

        with patch(f'{ROUTE_PATH}.build_location_forest', return_value=[{'public_id': 5}]) as forest, \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, 'rack')

        managers[ManagerType.LOCATIONS].search_locations_with_ancestors.assert_called_once_with('rack')
        # the node ids of the search result drive the has-children lookup
        managers[ManagerType.LOCATIONS].get_parents_with_children.assert_called_once_with([5])
        # the forest is built from the matches AND the has-children set
        forest.assert_called_once_with(matches, {5})
        response_cls.assert_called_once_with([{'public_id': 5}])

    def test_search_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` from the search is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].search_locations_with_ancestors.side_effect = \
            LocationsManagerGetError('search failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, 'rack')

        assert excinfo.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_cmdb_location_tree_path                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocationTreePath:
    """``get_cmdb_location_tree_path`` expands the tree to one location's ancestor path."""

    @staticmethod
    def _call(flask_app: Flask, public_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_location_tree_path)(public_id=public_id, request_user=MagicMock())

    def test_builds_forest_from_path_and_has_children_set(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The path rows + their has-children set are handed to build_location_forest."""
        del patched_provider
        path_rows = [{'public_id': 5, 'parent': 1}, {'public_id': LOCATION_PUBLIC_ID, 'parent': 5}]
        managers[ManagerType.LOCATIONS].get_locations_on_path_to.return_value = path_rows
        managers[ManagerType.LOCATIONS].get_parents_with_children.return_value = {5}
        forest_result = [{'public_id': 5}]

        with patch(f'{ROUTE_PATH}.build_location_forest', return_value=forest_result) as forest, \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_cls:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        managers[ManagerType.LOCATIONS].get_locations_on_path_to.assert_called_once_with(LOCATION_PUBLIC_ID)
        # the node ids of the path rows drive the has-children lookup
        managers[ManagerType.LOCATIONS].get_parents_with_children.assert_called_once_with([5, LOCATION_PUBLIC_ID])
        forest.assert_called_once_with(path_rows, {5})
        response_cls.assert_called_once_with(forest_result)

    def test_missing_location_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An unknown target (empty path) aborts 404 and never builds a forest."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_on_path_to.return_value = []

        with patch(f'{ROUTE_PATH}.build_location_forest') as forest:
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND
        forest.assert_not_called()

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` from the path lookup is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_on_path_to.side_effect = \
            LocationsManagerGetError('path failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A generic exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_locations_on_path_to.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                          move_cmdb_location_for_object                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMoveCmdbLocationForObject:
    """``move_cmdb_location_for_object`` normalizes the parent then delegates to move_object_location."""

    @staticmethod
    def _call(flask_app: Flask, object_id: int, body: dict[str, Any]) -> Any:
        """Drives the unwrapped handler inside a PATCH request context carrying the JSON body."""
        with flask_app.test_request_context('/', method='PATCH', json=body):
            return _unwrap(move_cmdb_location_for_object)(object_id=object_id, request_user=MagicMock())

    def test_moves_with_normalized_parent(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A positive parent is passed through to move_object_location with both managers."""
        del patched_provider

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.move_object_location') as move:
            self._call(flask_app, OBJECT_ID, {'parent': PARENT_ID})

        args = move.call_args.args
        assert args[0] == OBJECT_ID
        assert args[1] == PARENT_ID
        assert args[3] is managers[ManagerType.OBJECTS]
        assert args[4] is managers[ManagerType.LOCATIONS]

    def test_zero_parent_is_normalized_to_none(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A parent of 0 (no-parent sentinel) reaches move_object_location as None."""
        del patched_provider

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.move_object_location') as move:
            self._call(flask_app, OBJECT_ID, {'parent': 0})

        assert move.call_args.args[1] is None

    def test_manager_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A LocationsManager error from the move is translated to HTTP 400."""
        del patched_provider

        with patch(f'{ROUTE_PATH}.move_object_location', side_effect=LocationsManagerUpdateError('boom')):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, OBJECT_ID, {'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                               move_cmdb_locations                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMoveCmdbLocations:
    """``move_cmdb_locations`` guards the id list, validates every target, then moves each."""

    @staticmethod
    def _call(flask_app: Flask, body: dict[str, Any]) -> Any:
        """Drives the unwrapped bulk handler inside a PATCH request context carrying the JSON body."""
        with flask_app.test_request_context('/', method='PATCH', json=body):
            return _unwrap(move_cmdb_locations)(request_user=MagicMock())

    def test_non_list_object_ids_aborts_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A non-list object_ids body is rejected 400."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_ids': OBJECT_ID, 'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_empty_object_ids_aborts_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An empty object_ids list is rejected 400."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_ids': [], 'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_non_integer_ids_abort_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A non-integer id in the list is rejected 400."""
        del patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_ids': ['not-an-int'], 'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_validates_all_targets_then_moves_each(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Every target is validated up front, then each is moved with its pre-validated type."""
        del patched_provider

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.validate_object_location_move', return_value=MagicMock()) as validate_move, \
             patch(f'{ROUTE_PATH}.move_object_location') as move:
            self._call(flask_app, {'object_ids': [1, 2], 'parent': PARENT_ID})

        assert validate_move.call_count == 2
        assert move.call_count == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                            delete_cmdb_location_for_object                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteCmdbLocationForObject:
    """``delete_cmdb_location_for_object`` resolves the object's location then deletes it."""

    @staticmethod
    def _call(flask_app: Flask, object_id: int) -> Any:
        """Drives the unwrapped handler inside a DELETE request context."""
        with flask_app.test_request_context('/', method='DELETE'):
            return _unwrap(delete_cmdb_location_for_object)(object_id=object_id, request_user=MagicMock())

    def test_deletes_resolved_location_via_reparenting_helper(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The resolved location is handed to the re-parenting delete helper with both managers."""
        del patched_provider
        resolved = {'public_id': LOCATION_PUBLIC_ID, 'parent': PARENT_ID}
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = resolved

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.delete_location_with_reparenting', return_value=True) as reparent:
            self._call(flask_app, OBJECT_ID)

        reparent.assert_called_once_with(
            resolved, managers[ManagerType.LOCATIONS], managers[ManagerType.OBJECTS],
        )

    def test_missing_location_aborts_404(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A missing target location aborts 404 without deleting."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = None

        with patch(f'{ROUTE_PATH}.delete_location_with_reparenting') as reparent:
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, MISSING_OBJECT_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND
        reparent.assert_not_called()

    def test_delete_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerDeleteError`` from the helper is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = {
            'public_id': LOCATION_PUBLIC_ID, 'parent': PARENT_ID,
        }

        with patch(
            f'{ROUTE_PATH}.delete_location_with_reparenting',
            side_effect=LocationsManagerDeleteError('delete failed'),
        ):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, OBJECT_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR
