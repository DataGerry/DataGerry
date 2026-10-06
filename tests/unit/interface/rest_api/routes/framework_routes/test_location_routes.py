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
from contextlib import ExitStack
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, BadRequest, Forbidden

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes import (
    insert_cmdb_location,
    get_cmdb_locations,
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
from cmdb.models.location_model.location_constants import RootLocationDefault

from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LINKED_OBJECT_TYPE_MISMATCH_MSG,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import PlacementTarget
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
OTHER_TYPE_ID: int = 12
MISSING_OBJECT_ID: int = 9999
TOTAL_LOCATIONS: int = 2
RESOLVED_NAME: str = 'resolved-name'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

INSERT_PAYLOAD: dict[str, Any] = {'object_id': OBJECT_ID, 'parent': PARENT_ID, 'type_id': TYPE_ID, 'name': 'srv'}
# The object the routes read before they write; a sentinel, since the read itself is patched
LINKED_OBJECT: MagicMock = MagicMock(name='linked_object')
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

    The locations manager returns a realistic node dict rather than a bare MagicMock, because the move /
    delete routes read the node itself.

    RACK_MOUNTS is resolved too: those routes refuse to move a Rack member out of its rack by hand, and
    the guard asks the mounts manager whether the object is one. It answers None - not a member - so an
    ordinary move is not refused. `ManagerProvider.get_manager` is a classmethod, so patching it through
    the route module patches it for the rack guard as well.
    """
    locations_manager = MagicMock(name='locations_manager')
    locations_manager.get_location_for_object.return_value = {'public_id': 1, 'object_id': 1, 'parent': 1}

    rack_mounts_manager = MagicMock(name='rack_mounts_manager')
    rack_mounts_manager.get_mount_of_object.return_value = None

    return {
        ManagerType.TYPES: MagicMock(name='types_manager'),
        ManagerType.LOCATIONS: locations_manager,
        ManagerType.OBJECTS: MagicMock(name='objects_manager'),
        ManagerType.RACK_MOUNTS: rack_mounts_manager,
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
    """
    ``insert_cmdb_location`` reads and authorizes the object (READ + UPDATE), validates the placement, then writes

    The object read, the placement check, the rack guard and the rack reconcile are patched at the route
    module, so each test drives one branch of the route's own sequence
    """

    @staticmethod
    def _call(flask_app: Flask, data: dict[str, Any], request_user: Any = None) -> Any:
        """Drives the unwrapped handler inside a POST request context."""
        with flask_app.test_request_context('/', method='POST'):
            return _unwrap(insert_cmdb_location)(data=data, request_user=request_user or MagicMock())

    @staticmethod
    def _object_type() -> MagicMock:
        """The linked object's own type."""
        object_type = MagicMock(name='object_type', public_id=TYPE_ID, label='Server', selectable_as_parent=True)
        object_type.get_icon.return_value = 'fas fa-server'
        return object_type

    def _patched(self, object_type: MagicMock | None = None, **overrides: Any) -> dict[str, Any]:
        """The patches of the route's collaborators, each overridable by name."""
        object_type = object_type or self._object_type()
        patches: dict[str, Any] = {
            'read_placeable_object': patch(
                f'{ROUTE_PATH}.read_placeable_object', return_value=PlacementTarget(LINKED_OBJECT, object_type),
            ),
            'validate_location_placement': patch(
                f'{ROUTE_PATH}.validate_location_placement',
                return_value=PlacementTarget(LINKED_OBJECT, object_type),
            ),
            'resolve_location_name': patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME),
            'guard_rack_location_change': patch(f'{ROUTE_PATH}.guard_rack_location_change'),
            'reconcile_object_rack_membership': patch(f'{ROUTE_PATH}.reconcile_object_rack_membership'),
            'DefaultResponse': patch(f'{ROUTE_PATH}.DefaultResponse'),
        }
        patches.update(overrides)
        return patches

    def _run(self, flask_app: Flask, data: dict[str, Any], patches: dict[str, Any],
             request_user: Any = None) -> dict[str, MagicMock]:
        """Runs the route under `patches`; answers the started mocks by name."""
        with ExitStack() as stack:
            started: dict[str, MagicMock] = {name: stack.enter_context(cm) for name, cm in patches.items()}
            self._call(flask_app, data, request_user)

        return started

    def test_the_object_is_read_through_the_callers_acl(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A node carries its object's summary and writes its field: read and authorized with the caller, first"""
        del patched_provider
        request_user = MagicMock(name='request_user')

        started = self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(), request_user)

        started['read_placeable_object'].assert_called_once_with(OBJECT_ID, managers[ManagerType.OBJECTS], request_user)

    def test_a_denied_object_writes_nothing(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The read's 403 is the answer; no node and no field are written"""
        del patched_provider
        denied = patch(f'{ROUTE_PATH}.read_placeable_object', side_effect=Forbidden())

        with pytest.raises(Forbidden):
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(read_placeable_object=denied))

        managers[ManagerType.LOCATIONS].insert_location.assert_not_called()
        managers[ManagerType.OBJECTS].set_location_field_for_objects.assert_not_called()

    def test_the_placement_is_validated_for_the_object(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The same check as a move: location field, parent exists, selectable, no cycle"""
        del patched_provider

        started = self._run(flask_app, dict(INSERT_PAYLOAD), self._patched())

        started['validate_location_placement'].assert_called_once_with(
            LINKED_OBJECT, PARENT_ID, managers[ManagerType.OBJECTS], managers[ManagerType.LOCATIONS],
            started['read_placeable_object'].return_value.object_type,
        )

    def test_an_invalid_placement_writes_nothing(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The placement check's 400 is the answer"""
        del patched_provider
        invalid = patch(f'{ROUTE_PATH}.validate_location_placement', side_effect=BadRequest())

        with pytest.raises(BadRequest):
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(validate_location_placement=invalid))

        managers[ManagerType.LOCATIONS].insert_location.assert_not_called()

    def test_the_node_carries_the_objects_own_type(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Label, icon and selectable come from the object's type, and the name from the resolver"""
        del patched_provider
        managers[ManagerType.LOCATIONS].insert_location.return_value = LOCATION_PUBLIC_ID

        started = self._run(flask_app, dict(INSERT_PAYLOAD), self._patched())

        written = managers[ManagerType.LOCATIONS].insert_location.call_args.args[0]
        assert written == {
            'object_id': OBJECT_ID, 'parent': PARENT_ID, 'type_id': TYPE_ID, 'type_label': 'Server',
            'type_icon': 'fas fa-server', 'type_selectable': True, 'name': RESOLVED_NAME,
        }
        started['DefaultResponse'].assert_called_once_with(LOCATION_PUBLIC_ID)

    def test_the_name_is_resolved_from_the_object_read(self, flask_app: Flask, patched_provider: Any) -> None:
        """The resolver gets the object the route read - it reads nothing itself"""
        del patched_provider
        request_user = MagicMock(name='request_user')

        started = self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(), request_user)

        started['resolve_location_name'].assert_called_once_with(
            INSERT_PAYLOAD['name'], LINKED_OBJECT, request_user,
        )

    def test_the_type_id_may_be_omitted(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The object names its type; the body need not"""
        del patched_provider
        payload: dict[str, Any] = {key: value for key, value in INSERT_PAYLOAD.items() if key != 'type_id'}

        self._run(flask_app, payload, self._patched())

        assert managers[ManagerType.LOCATIONS].insert_location.call_args.args[0]['type_id'] == TYPE_ID

    def test_another_type_id_is_a_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A body naming a type the object does not have is refused, naming both"""
        del patched_provider
        payload: dict[str, Any] = {**INSERT_PAYLOAD, 'type_id': OTHER_TYPE_ID}

        with pytest.raises(BadRequest) as excinfo:
            self._run(flask_app, payload, self._patched())

        assert excinfo.value.description == LINKED_OBJECT_TYPE_MISMATCH_MSG.format(
            object_id=OBJECT_ID, object_type_id=TYPE_ID, type_id=OTHER_TYPE_ID,
        )
        managers[ManagerType.LOCATIONS].insert_location.assert_not_called()

    def test_the_object_location_field_is_pointed_at_the_parent(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The other half of the mirror: the object's location field holds the node's parent"""
        del patched_provider

        self._run(flask_app, dict(INSERT_PAYLOAD), self._patched())

        managers[ManagerType.OBJECTS].set_location_field_for_objects.assert_called_once_with([OBJECT_ID], PARENT_ID)

    def test_the_rack_rules_run_around_the_write(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The rack guard before, the membership reconcile after"""
        del patched_provider
        request_user = MagicMock(name='request_user')

        started = self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(), request_user)

        started['guard_rack_location_change'].assert_called_once_with(
            request_user, OBJECT_ID, PARENT_ID, managers[ManagerType.LOCATIONS],
        )
        started['reconcile_object_rack_membership'].assert_called_once()

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

    def test_objects_get_error_maps_to_400(self, flask_app: Flask, patched_provider: Any) -> None:
        """An ``ObjectsManagerGetError`` from the object read maps to HTTP 400."""
        del patched_provider
        failing = patch(f'{ROUTE_PATH}.read_placeable_object', side_effect=ObjectsManagerGetError('boom'))

        with pytest.raises(HTTPException) as excinfo:
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(read_placeable_object=failing))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_types_get_error_maps_to_400(self, flask_app: Flask, patched_provider: Any) -> None:
        """A ``TypesManagerGetError`` - the rack reconcile reads types - is translated to HTTP 400."""
        del patched_provider
        failing = patch(f'{ROUTE_PATH}.reconcile_object_rack_membership',
                        side_effect=TypesManagerGetError('lookup failed'))

        with pytest.raises(HTTPException) as excinfo:
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(reconcile_object_rack_membership=failing))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_insert_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerInsertError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].insert_location.side_effect = LocationsManagerInsertError('write failed')

        with pytest.raises(HTTPException) as excinfo:
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched())

        assert excinfo.value.code == HTTP_BAD_REQUEST
        managers[ManagerType.OBJECTS].set_location_field_for_objects.assert_not_called()

    def test_field_write_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An ``ObjectsManagerUpdateError`` from the mirror write is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.OBJECTS].set_location_field_for_objects.side_effect = ObjectsManagerUpdateError('x')

        with pytest.raises(HTTPException) as excinfo:
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched())

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(self, flask_app: Flask, patched_provider: Any) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        failing = patch(f'{ROUTE_PATH}.read_placeable_object', side_effect=RuntimeError('boom'))

        with pytest.raises(HTTPException) as excinfo:
            self._run(flask_app, dict(INSERT_PAYLOAD), self._patched(read_placeable_object=failing))

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_cmdb_locations                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbLocations:
    """``get_cmdb_locations`` answers the canonical documents of the page, mapping failures to 400/500."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_locations)(params=MagicMock(), request_user=MagicMock())

    def test_answers_the_documents_the_read_returned(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """
        The documents go into the envelope as they are read - no model per row

        The manager normalises them (``to_location_document``), so the route neither hydrates a
        CmdbLocation nor converts one back.
        """
        del patched_provider
        documents = [{'public_id': 1}, {'public_id': 2}]
        managers[ManagerType.LOCATIONS].iterate_location_documents.return_value = (documents, TOTAL_LOCATIONS)
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}), \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app)

        assert response_ctor.call_args.args[0] is documents
        assert response_ctor.call_args.kwargs['total'] == TOTAL_LOCATIONS
        assert result is sentinel_response

    def test_iteration_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerIterationError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].iterate_location_documents.side_effect = LocationsManagerIterationError(
            'bad pipeline')

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
        managers[ManagerType.LOCATIONS].iterate_location_documents.side_effect = RuntimeError('boom')

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

    def test_missing_parent_answers_none(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """
        A dangling parent reference answers 200 with None, like an object with no location at all

        Aborting 404 would give the one outcome "there is no parent" two encodings and
        reported a data-integrity problem as if the object did not exist.
        """
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = {'parent': PARENT_ID}
        managers[ManagerType.LOCATIONS].get_location.return_value = None

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app, OBJECT_ID)

        response_ctor.assert_called_once_with(None)

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
    """``get_cmdb_children`` returns the direct child locations as canonical documents."""

    @staticmethod
    def _call(flask_app: Flask, object_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_children)(object_id=object_id, request_user=MagicMock())

    def test_answers_with_the_child_documents(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Direct children are read by parent public_id as canonical documents, no model round trip."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = {'public_id': LOCATION_PUBLIC_ID}
        managers[ManagerType.LOCATIONS].get_child_location_documents.return_value = ['child1', 'child2']
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, OBJECT_ID)

        managers[ManagerType.LOCATIONS].get_child_location_documents.assert_called_once_with(LOCATION_PUBLIC_ID)
        response_ctor.assert_called_once_with(['child1', 'child2'])
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
        managers[ManagerType.LOCATIONS].get_child_location_documents.assert_not_called()

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
        """The root's direct child documents are passed to build_location_level, then wrapped."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_child_location_documents.return_value = ['loc1', 'loc2']
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.build_location_level', return_value=['node1', 'node2']) as build_level, \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app)

        managers[ManagerType.LOCATIONS].get_child_location_documents.assert_called_once_with(
            RootLocationDefault.PUBLIC_ID
        )
        build_level.assert_called_once_with(['loc1', 'loc2'], managers[ManagerType.LOCATIONS])
        response_ctor.assert_called_once_with(['node1', 'node2'])
        assert result is sentinel_response

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_child_location_documents.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_child_location_documents.side_effect = RuntimeError('boom')

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
        """Child documents are read by the location's public_id and passed to build_location_level."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_child_location_documents.return_value = ['loc1']
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.build_location_level', return_value=['node1']) as build_level, \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, LOCATION_PUBLIC_ID)

        managers[ManagerType.LOCATIONS].get_child_location_documents.assert_called_once_with(LOCATION_PUBLIC_ID)
        build_level.assert_called_once_with(['loc1'], managers[ManagerType.LOCATIONS])
        response_ctor.assert_called_once_with(['node1'])
        assert result is sentinel_response

    def test_get_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A ``LocationsManagerGetError`` is translated to HTTP 400."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_child_location_documents.side_effect = LocationsManagerGetError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, LOCATION_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_child_location_documents.side_effect = RuntimeError('boom')

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

    def test_the_object_is_read_through_the_callers_acl(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The answer echoes the node, whose name is the object's summary: the object is read with the caller"""
        del patched_provider
        managers[ManagerType.LOCATIONS].get_location_for_object.return_value = SAMPLE_LOCATION_DICT
        request_user = MagicMock(name='request_user')

        with patch(f'{ROUTE_PATH}.read_placeable_object',
                   return_value=PlacementTarget(LINKED_OBJECT, MagicMock(name='object_type'))) as read, \
             patch(f'{ROUTE_PATH}.resolve_location_name', return_value=RESOLVED_NAME) as resolve, \
             patch(f'{ROUTE_PATH}.validate_object_location_change'), \
             patch(f'{ROUTE_PATH}.UpdateSingleResponse'), \
             flask_app.test_request_context('/update_location', method='PUT'):
            _unwrap(update_cmdb_location_for_object)(data=dict(UPDATE_PAYLOAD), request_user=request_user)

        read.assert_called_once_with(OBJECT_ID, managers[ManagerType.OBJECTS], request_user)
        resolve.assert_called_once_with(UPDATE_PAYLOAD['name'], LINKED_OBJECT, request_user)

    def test_a_denied_object_writes_nothing(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """The read's 403 comes first: neither the node nor the object's field is written"""
        del patched_provider

        with patch(f'{ROUTE_PATH}.read_placeable_object', side_effect=Forbidden()), pytest.raises(Forbidden):
            self._call(flask_app, dict(UPDATE_PAYLOAD))

        managers[ManagerType.LOCATIONS].update_location.assert_not_called()
        managers[ManagerType.OBJECTS].set_location_field_for_objects.assert_not_called()

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
        del managers, patched_provider

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.move_object_location') as move:
            self._call(flask_app, OBJECT_ID, {'parent': 0})

        assert move.call_args.args[1] is None

    def test_manager_error_maps_to_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A LocationsManager error from the move is translated to HTTP 400."""
        del managers, patched_provider

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
        del managers, patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_ids': OBJECT_ID, 'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_empty_object_ids_aborts_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """An empty object_ids list is rejected 400."""
        del managers, patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_ids': [], 'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_non_integer_ids_abort_400(
        self, flask_app: Flask, managers: dict[ManagerType, MagicMock], patched_provider: Any,
    ) -> None:
        """A non-integer id in the list is rejected 400."""
        del managers, patched_provider

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, {'object_ids': ['not-an-int'], 'parent': PARENT_ID})

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_validates_all_targets_then_moves_each(
        self, flask_app: Flask, patched_provider: Any,
    ) -> None:
        """
        The whole batch is validated in ONE call up front, then each target is moved

        The pre-flight calls the batched validator rather than the single-object one per object - the
        ``validate_object_location_moves``, called once with every id, so the shared reads happen once.
        """
        del patched_provider
        validated = {1: MagicMock(), 2: MagicMock()}

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.validate_object_location_moves', return_value=validated) as validate_moves, \
             patch(f'{ROUTE_PATH}.move_object_location') as move:
            self._call(flask_app, {'object_ids': [1, 2], 'parent': PARENT_ID})

        validate_moves.assert_called_once()
        assert validate_moves.call_args.args[0] == [1, 2]
        assert move.call_count == 2

    def test_each_move_gets_its_own_pre_validated_type(
        self, flask_app: Flask, patched_provider: Any,
    ) -> None:
        """The type the batch validator resolved for an object is the one handed to its move."""
        del patched_provider
        first_type, second_type = MagicMock(name='type-1'), MagicMock(name='type-2')

        with patch(f'{ROUTE_PATH}.DefaultResponse'), \
             patch(f'{ROUTE_PATH}.validate_object_location_moves',
                   return_value={1: first_type, 2: second_type}), \
             patch(f'{ROUTE_PATH}.move_object_location') as move:
            self._call(flask_app, {'object_ids': [1, 2], 'parent': PARENT_ID})

        assert [call.args[-1] for call in move.call_args_list] == [first_type, second_type]


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
