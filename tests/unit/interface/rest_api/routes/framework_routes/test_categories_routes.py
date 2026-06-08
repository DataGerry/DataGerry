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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.categories_routes

Each test unwraps the route handler past its auth / validation / collection-parameter
decorators and drives the bare function inside a Flask test_request_context, with
CategoriesManager and the response factories patched at the route module path. No Mongo
and no Flask blueprint registration runs - only the route-glue (status code mapping,
ordering of manager calls, branch selection between list-view and tree-view) is exercised.
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments,protected-access
from typing import Any, Callable
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager import CategoriesManager
from cmdb.interface.rest_api.routes.framework_routes.categories_constants import CategoryListView
from cmdb.interface.rest_api.routes.framework_routes.categories_routes import (
    insert_cmdb_category,
    get_cmdb_categories,
    get_cmdb_category,
    update_cmdb_category,
    delete_cmdb_category,
)

from cmdb.errors.manager.categories_manager import (
    CategoriesManagerInsertError,
    CategoriesManagerGetError,
    CategoriesManagerUpdateError,
    CategoriesManagerDeleteError,
    CategoriesManagerIterationError,
    CategoriesManagerTreeInitError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.categories_routes'

CATEGORY_PUBLIC_ID: int = 7
MISSING_CATEGORY_PUBLIC_ID: int = 9999
FOREIGN_PUBLIC_ID: int = 555
TOTAL_CATEGORIES: int = 2

SAMPLE_CATEGORY_DICT: dict[str, Any] = {'public_id': CATEGORY_PUBLIC_ID, 'name': 'c', 'label': 'C'}
PERSISTED_CATEGORY_DICT: dict[str, Any] = {**SAMPLE_CATEGORY_DICT, 'creation_time': 'srv-stamp'}
UPDATED_CATEGORY_DICT: dict[str, Any] = {**SAMPLE_CATEGORY_DICT, 'label': 'C-updated'}

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500


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


@pytest.fixture(name='mgr')
def fixture_mgr() -> MagicMock:
    """A MagicMock standing in for a CategoriesManager, returned by the patched ManagerProvider.

    ``validate_parent_assignment`` defaults to None (= assignment valid) so the write-path
    tests run through; guard tests override it with a rejection reason
    """
    manager = MagicMock(spec=CategoriesManager)
    manager.validate_parent_assignment.return_value = None

    return manager


@pytest.fixture(name='patched_manager_provider')
def fixture_patched_manager_provider(mgr: MagicMock) -> Any:
    """Patches ``ManagerProvider.get_manager`` at the route module path to return ``mgr``."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr) as provider:
        yield provider


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  insert_cmdb_category                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertCmdbCategory:
    """``insert_cmdb_category`` inserts then re-reads, surfacing manager errors as 400/404/500."""

    @staticmethod
    def _call(flask_app: Flask, data: dict[str, Any]) -> Any:
        """Drives the unwrapped handler inside a POST request context."""
        with flask_app.test_request_context('/', method='POST'):
            return _unwrap(insert_cmdb_category)(data=data, request_user=MagicMock())

    def test_returns_persisted_document_with_assigned_public_id(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The persisted (re-read) document and the new public_id are handed to InsertSingleResponse."""
        del patched_manager_provider
        mgr.insert_category.return_value = CATEGORY_PUBLIC_ID
        mgr.get_category.return_value = PERSISTED_CATEGORY_DICT
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.InsertSingleResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, dict(SAMPLE_CATEGORY_DICT))

        response_ctor.assert_called_once_with(PERSISTED_CATEGORY_DICT, CATEGORY_PUBLIC_ID)
        assert result is sentinel_response

    def test_stamps_creation_time_when_missing(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``data.setdefault('creation_time', now)`` runs before insert; the manager sees the stamp."""
        del patched_manager_provider
        mgr.insert_category.return_value = CATEGORY_PUBLIC_ID
        mgr.get_category.return_value = PERSISTED_CATEGORY_DICT
        payload = dict(SAMPLE_CATEGORY_DICT)
        assert 'creation_time' not in payload

        with patch(f'{ROUTE_PATH}.InsertSingleResponse'):
            self._call(flask_app, payload)

        stamped = mgr.insert_category.call_args.args[0]
        assert 'creation_time' in stamped

    def test_returns_404_when_post_insert_read_yields_none(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """If the manager loses the row between insert and re-read, the route aborts 404."""
        del patched_manager_provider
        mgr.insert_category.return_value = CATEGORY_PUBLIC_ID
        mgr.get_category.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_NOT_FOUND

    def test_invalid_parent_reference_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A rejection from ``validate_parent_assignment`` aborts 400 before any insert happens."""
        del patched_manager_provider
        mgr.validate_parent_assignment.return_value = 'parent does not exist'

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_BAD_REQUEST
        mgr.insert_category.assert_not_called()

    def test_insert_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerInsertError`` is translated to HTTP 400."""
        del patched_manager_provider
        mgr.insert_category.side_effect = CategoriesManagerInsertError('bad payload')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_get_error_during_reread_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A ``CategoriesManagerGetError`` raised on the re-read maps to HTTP 400."""
        del patched_manager_provider
        mgr.insert_category.return_value = CATEGORY_PUBLIC_ID
        mgr.get_category.side_effect = CategoriesManagerGetError('lookup failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_manager_provider
        mgr.insert_category.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_cmdb_categories                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbCategories:
    """``get_cmdb_categories`` picks the tree branch or the flat-list branch via ``CategoryListView``."""

    @staticmethod
    def _params(view: str) -> MagicMock:
        """Builds a CollectionParameters-shaped mock whose ``optional['view']`` is set."""
        params = MagicMock(name='collection_params')
        params.optional = {'view': view}

        return params

    @staticmethod
    def _call(flask_app: Flask, params: MagicMock) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_categories)(params=params, request_user=MagicMock())

    def test_tree_branch_serializes_via_category_tree_to_json(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``view=tree`` reads ``CategoriesManager.tree`` and serializes with ``CategoryTree.to_json``."""
        del patched_manager_provider
        sentinel_tree = MagicMock(name='category_tree')
        sentinel_tree.__len__.return_value = TOTAL_CATEGORIES
        mgr.tree = sentinel_tree
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.CategoryTree.to_json', return_value=['t1', 't2']) as to_json_mock, \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, self._params(CategoryListView.TREE.value))

        to_json_mock.assert_called_once_with(sentinel_tree)
        response_ctor.return_value.make_response.assert_called_once_with(pagination=False)
        assert response_ctor.call_args.args[0] == ['t1', 't2']
        assert response_ctor.call_args.args[1] == TOTAL_CATEGORIES
        assert result is sentinel_response

    def test_list_branch_iterates_and_serializes_each_row(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """For the default ``list`` view the route iterates and ``CmdbCategory.to_json`` runs per row."""
        del patched_manager_provider
        iteration_result = MagicMock(name='iteration_result')
        iteration_result.results = ['raw1', 'raw2']
        iteration_result.total = TOTAL_CATEGORIES
        mgr.iterate.return_value = iteration_result
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}), \
             patch(f'{ROUTE_PATH}.CmdbCategory.to_json', side_effect=lambda x: f'json-{x}'), \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, self._params(CategoryListView.LIST.value))

        assert response_ctor.call_args.args[0] == ['json-raw1', 'json-raw2']
        assert response_ctor.call_args.args[1] == TOTAL_CATEGORIES
        response_ctor.return_value.make_response.assert_called_once_with()
        assert result is sentinel_response

    def test_iteration_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerIterationError`` from ``iterate`` is translated to HTTP 400."""
        del patched_manager_provider
        mgr.iterate.side_effect = CategoriesManagerIterationError('bad pipeline')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, self._params(CategoryListView.LIST.value))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_tree_init_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerTreeInitError`` from the tree property is translated to HTTP 500."""
        del patched_manager_provider
        type(mgr).tree = property(lambda _self: (_ for _ in ()).throw(CategoriesManagerTreeInitError('bad tree')))

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, self._params(CategoryListView.TREE.value))

        assert excinfo.value.code == HTTP_SERVER_ERROR

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_manager_provider
        mgr.iterate.side_effect = RuntimeError('boom')

        with patch(f'{ROUTE_PATH}.BuilderParameters'), \
             patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
            with pytest.raises(HTTPException) as excinfo:
                self._call(flask_app, self._params(CategoryListView.LIST.value))

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_cmdb_category                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbCategory:
    """``get_cmdb_category`` returns the document, 404s on miss and 400s on manager failure."""

    @staticmethod
    def _call(flask_app: Flask, public_id: int) -> Any:
        """Drives the unwrapped handler inside a GET request context."""
        with flask_app.test_request_context('/', method='GET'):
            return _unwrap(get_cmdb_category)(public_id=public_id, request_user=MagicMock())

    def test_returns_document_via_get_single_response(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The found document is handed to GetSingleResponse with ``body`` reflecting the HTTP verb."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.GetSingleResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, CATEGORY_PUBLIC_ID)

        response_ctor.assert_called_once_with(SAMPLE_CATEGORY_DICT, body=False)
        assert result is sentinel_response

    def test_returns_404_when_id_not_present(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A missing id aborts 404 without invoking the response factory."""
        del patched_manager_provider
        mgr.get_category.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, MISSING_CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND

    def test_get_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerGetError`` from the manager maps to HTTP 400."""
        del patched_manager_provider
        mgr.get_category.side_effect = CategoriesManagerGetError('lookup failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_manager_provider
        mgr.get_category.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 update_cmdb_category                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateCmdbCategory:
    """``update_cmdb_category`` writes through the manager and returns the re-read document."""

    @staticmethod
    def _call(flask_app: Flask, public_id: int, data: dict[str, Any]) -> Any:
        """Drives the unwrapped handler inside a PUT request context."""
        with flask_app.test_request_context('/', method='PUT'):
            return _unwrap(update_cmdb_category)(public_id=public_id, data=data, request_user=MagicMock())

    def test_passes_dict_directly_to_update_category(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The route hands the dict straight to ``update_category`` - no ``CmdbCategory.from_data`` round-trip."""
        del patched_manager_provider
        mgr.get_category.side_effect = [SAMPLE_CATEGORY_DICT, UPDATED_CATEGORY_DICT]
        payload = dict(UPDATED_CATEGORY_DICT)

        with patch(f'{ROUTE_PATH}.UpdateSingleResponse'), \
             patch(f'{ROUTE_PATH}.CmdbCategory.from_data') as from_data_mock:
            self._call(flask_app, CATEGORY_PUBLIC_ID, payload)

        from_data_mock.assert_not_called()
        mgr.update_category.assert_called_once_with(CATEGORY_PUBLIC_ID, payload)

    def test_returns_reread_document_after_update(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The response carries the re-read document, not the request payload."""
        del patched_manager_provider
        mgr.get_category.side_effect = [SAMPLE_CATEGORY_DICT, UPDATED_CATEGORY_DICT]
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.UpdateSingleResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, CATEGORY_PUBLIC_ID, dict(UPDATED_CATEGORY_DICT))

        response_ctor.assert_called_once_with(UPDATED_CATEGORY_DICT)
        assert result is sentinel_response

    def test_returns_404_when_target_missing(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A missing target aborts 404 without invoking ``update_category``."""
        del patched_manager_provider
        mgr.get_category.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, MISSING_CATEGORY_PUBLIC_ID, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_NOT_FOUND
        mgr.update_category.assert_not_called()

    def test_payload_public_id_is_pinned_to_the_url(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A body carrying a different public_id cannot rewrite the document's identity."""
        del patched_manager_provider
        mgr.get_category.side_effect = [SAMPLE_CATEGORY_DICT, UPDATED_CATEGORY_DICT]
        payload = {**UPDATED_CATEGORY_DICT, 'public_id': FOREIGN_PUBLIC_ID}

        with patch(f'{ROUTE_PATH}.UpdateSingleResponse'):
            self._call(flask_app, CATEGORY_PUBLIC_ID, payload)

        written = mgr.update_category.call_args.args[1]
        assert written['public_id'] == CATEGORY_PUBLIC_ID

    def test_invalid_parent_assignment_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A rejection from ``validate_parent_assignment`` aborts 400 before any write happens."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        mgr.validate_parent_assignment.return_value = 'would create a cycle'

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_BAD_REQUEST
        mgr.update_category.assert_not_called()

    def test_get_error_on_preread_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerGetError`` from the pre-read maps to HTTP 400."""
        del patched_manager_provider
        mgr.get_category.side_effect = CategoriesManagerGetError('lookup failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_update_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerUpdateError`` from the write maps to HTTP 400."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        mgr.update_category.side_effect = CategoriesManagerUpdateError('write failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        mgr.update_category.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID, dict(SAMPLE_CATEGORY_DICT))

        assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 delete_cmdb_category                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteCmdbCategory:
    """``delete_cmdb_category`` detaches children FIRST, then deletes, and maps step failures to 400/500."""

    @staticmethod
    def _call(flask_app: Flask, public_id: int) -> Any:
        """Drives the unwrapped handler inside a DELETE request context."""
        with flask_app.test_request_context('/', method='DELETE'):
            return _unwrap(delete_cmdb_category)(public_id=public_id, request_user=MagicMock())

    def test_detach_runs_before_delete(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Children are detached BEFORE the category is removed (ordering pinned via mock_calls)."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT

        with patch(f'{ROUTE_PATH}.DeleteSingleResponse'):
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert mgr.method_calls == [
            call.get_category(CATEGORY_PUBLIC_ID),
            call.remove_category_as_parent(CATEGORY_PUBLIC_ID),
            call.delete_category(CATEGORY_PUBLIC_ID),
        ]

    def test_response_carries_predelete_document(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The response wraps the pre-read document so the client can observe what was removed."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        sentinel_response = MagicMock(name='wsgi_response')

        with patch(f'{ROUTE_PATH}.DeleteSingleResponse') as response_ctor:
            response_ctor.return_value.make_response.return_value = sentinel_response
            result = self._call(flask_app, CATEGORY_PUBLIC_ID)

        response_ctor.assert_called_once_with(raw=SAMPLE_CATEGORY_DICT)
        assert result is sentinel_response

    def test_returns_404_when_target_missing(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A missing target aborts 404 without touching detach / delete."""
        del patched_manager_provider
        mgr.get_category.return_value = None

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, MISSING_CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_NOT_FOUND
        mgr.remove_category_as_parent.assert_not_called()
        mgr.delete_category.assert_not_called()

    def test_get_error_on_preread_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """``CategoriesManagerGetError`` from the pre-read maps to HTTP 400."""
        del patched_manager_provider
        mgr.get_category.side_effect = CategoriesManagerGetError('lookup failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST

    def test_detach_failure_maps_to_400_with_no_delete_attempted(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Step 1 (detach) failure → 400, and ``delete_category`` is never reached."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        mgr.remove_category_as_parent.side_effect = CategoriesManagerUpdateError('detach failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_BAD_REQUEST
        mgr.delete_category.assert_not_called()

    def test_delete_failure_after_detach_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Step 2 (delete) failure after step 1 succeeded → 500 (children detached, parent intact)."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        mgr.delete_category.side_effect = CategoriesManagerDeleteError('delete failed')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR
        mgr.remove_category_as_parent.assert_called_once_with(CATEGORY_PUBLIC_ID)

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception is translated to HTTP 500."""
        del patched_manager_provider
        mgr.get_category.return_value = SAMPLE_CATEGORY_DICT
        mgr.remove_category_as_parent.side_effect = RuntimeError('boom')

        with pytest.raises(HTTPException) as excinfo:
            self._call(flask_app, CATEGORY_PUBLIC_ID)

        assert excinfo.value.code == HTTP_SERVER_ERROR
