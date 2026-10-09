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
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes import (
    get_cmdb_locations,
    get_cmdb_location_tree_roots,
    get_cmdb_location_tree_children,
    get_cmdb_location_tree_path,
    search_cmdb_location_tree,
    get_cmdb_location,
    get_cmdb_location_for_object,
    get_cmdb_location_parent,
    get_cmdb_children,
    move_cmdb_location_for_object,
    move_cmdb_locations,
    location_blueprint,
)
from cmdb.models.location_model.location_constants import RootLocationDefault

from cmdb.errors.manager.locations_manager import (
    LocationsManagerGetError,
    LocationsManagerUpdateError,
    LocationsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'

LOCATION_PUBLIC_ID: int = 7
OBJECT_ID: int = 42
PARENT_ID: int = 3
MISSING_OBJECT_ID: int = 9999
TOTAL_LOCATIONS: int = 2

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

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

    The locations manager returns a realistic node dict rather than a bare MagicMock, because the move
    routes read the node itself.

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
#                                                  retired write routes                                               #
# -------------------------------------------------------------------------------------------------------------------- #
RETIRED_ROUTES: list[tuple[str, str]] = [
    ('/', 'POST'),
    ('/update_location', 'PUT'),
    ('/update_location', 'PATCH'),
    ('/<int:object_id>/object', 'DELETE'),
]
WRITE_METHODS: set[str] = {'POST', 'PUT', 'PATCH', 'DELETE'}
MOVE_ROUTES: set[str] = {'/<int:object_id>/parent', '/parents'}


class TestRetiredWriteRoutes:
    """The blueprint's only writes are the two moves: no create, update or delete route is registered."""

    @staticmethod
    def _registered(flask_app: Flask) -> set[tuple[str, str]]:
        """Every (rule, method) the blueprint registers, prefix stripped."""
        flask_app.register_blueprint(location_blueprint, url_prefix='/locations')

        return {(rule.rule.removeprefix('/locations') or '/', method)
                for rule in flask_app.url_map.iter_rules() if rule.endpoint.startswith('locations.')
                for method in rule.methods}

    @pytest.mark.parametrize('rule, method', RETIRED_ROUTES, ids=['create', 'update-put', 'update-patch', 'delete'])
    def test_the_route_is_not_registered(self, flask_app: Flask, rule: str, method: str) -> None:
        """Gone from the URL map"""
        assert (rule, method) not in self._registered(flask_app)

    def test_the_moves_are_the_only_writes(self, flask_app: Flask) -> None:
        """Any write rule left is one of the two moves"""
        writes: set[str] = {rule for rule, method in self._registered(flask_app) if method in WRITE_METHODS}

        assert writes == MOVE_ROUTES
