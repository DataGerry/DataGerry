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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes

Each handler is unwrapped past its decorator chain and driven inside a Flask test_request_context;
ManagerProvider is patched at the route module path. No Mongo. These pin the route glue around the
audit fixes: the missing-object 404s (state / references), the orphaned-type skip in the group
route, and the per-target id used in the bulk-update not-found message
"""
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes import (
    get_cmdb_object_state,
    get_cmdb_object_references,
    get_cmdb_object_mds_references,
    group_cmdb_objects_by_type_id,
    insert_cmdb_object,
    update_cmdb_object,
    delete_cmdb_object,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes'

MISSING_ID: int = 9999


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / validate / parse / protect / verify / insert_request_user)."""
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
    """A single MagicMock returned for every ManagerType the routes request."""
    return MagicMock()


@pytest.fixture(name='patched_manager_provider')
def fixture_patched_manager_provider(mgr: MagicMock) -> Any:
    """Patches ManagerProvider.get_manager at the route module path to return mgr."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr):
        yield


# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_cmdb_object_state (bug #1)                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbObjectState:
    """A missing object yields 404 - the null check runs before CmdbObject.from_data."""

    def test_missing_object_returns_404(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """get_object returning None aborts 404 instead of crashing from_data into a 500."""
        del patched_manager_provider
        mgr.get_object.return_value = None

        with flask_app.test_request_context(f'/state/{MISSING_ID}'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_cmdb_object_state)(public_id=MISSING_ID, request_user=SimpleNamespace(public_id=1))

        assert exc_info.value.code == 404
        # from_data must not be reached for a missing object
        mgr.get_object.assert_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                        get_cmdb_object_references (bug #1)                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbObjectReferences:
    """A missing referenced object yields 404 before from_data is called."""

    def test_missing_object_returns_404(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """get_object returning None aborts 404 rather than passing None into from_data."""
        del patched_manager_provider
        mgr.get_object.return_value = None
        params = SimpleNamespace(optional={}, filter={}, limit=0, skip=0, sort='public_id', order=1)

        with flask_app.test_request_context(f'/references/{MISSING_ID}'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_cmdb_object_references)(
                    public_id=MISSING_ID, params=params, request_user=SimpleNamespace(public_id=1),
                )

        assert exc_info.value.code == 404
        mgr.references.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                   group_cmdb_objects_by_type_id (bug #3)                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupObjectsByTypeId:
    """Groups whose Type no longer exists are skipped instead of crashing on a None type."""

    def test_orphaned_group_is_skipped(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A group whose type resolves to None is omitted; a valid group is enriched and returned."""
        del patched_manager_provider
        mgr.group_objects_by_value.return_value = [{'_id': 1, 'count': 3}, {'_id': 2, 'count': 1}]
        # type_id 1 is orphaned (absent from the lookup), type_id 2 resolves to a real type
        mgr.get_types_lookup.return_value = {2: SimpleNamespace(label='Server', ci_explorer_color='#fff')}

        with patch(f'{ROUTE_PATH}.fetch_only_active_objects', return_value=False), \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            with flask_app.test_request_context('/group/type_id'):
                _unwrap(group_cmdb_objects_by_type_id)(value='type_id', request_user=SimpleNamespace(public_id=1))

        result_arg = response_ctor.call_args.args[0]
        assert len(result_arg) == 1
        assert result_arg[0]['_id'] == 2
        assert result_arg[0]['label'] == 'Server'


# -------------------------------------------------------------------------------------------------------------------- #
#                                       update_cmdb_object message (bug #5)                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateCmdbObjectNotFoundMessage:
    """The bulk-update not-found abort references the per-target id, not the path public_id."""

    def test_missing_target_message_uses_obj_id(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """When a listed objectID is missing, the 404 message names that id."""
        del patched_manager_provider
        mgr.get_object.return_value = None
        path_id, target_id = 1, 4242

        with flask_app.test_request_context(
            f'/{path_id}', method='PUT', json={'fields': []}, query_string={'objectIDs': [target_id]},
        ):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(update_cmdb_object)(
                    public_id=path_id, data={'fields': []}, request_user=SimpleNamespace(public_id=1),
                )

        assert exc_info.value.code == 404
        assert str(target_id) in exc_info.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                   get_cmdb_object_mds_references message (B3)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMdsReferencesMissingIdMessage:
    """A missing id in the objectIDs list yields a 404 naming that id, not the path public_id."""

    def test_missing_id_message_uses_object_id(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """When a requested objectID is missing, the 404 message references that id."""
        del patched_manager_provider
        mgr.get_object.return_value = None
        path_id, target_id = 5, 4242

        with flask_app.test_request_context(
            f'/{path_id}/mds_references', query_string={'objectIDs': str(target_id)},
        ):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(get_cmdb_object_mds_references)(public_id=path_id, request_user=SimpleNamespace(public_id=1))

        assert exc_info.value.code == 404
        assert str(target_id) in exc_info.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                     delete_cmdb_object get-error mapping (B5)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteCmdbObjectGetErrorMapping:
    """A get failure resolving the delete target maps to 400, aligned with the sibling delete routes."""

    def test_get_error_returns_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """ObjectsManagerGetError while fetching the target aborts 400 (previously 500)."""
        del patched_manager_provider
        mgr.get_object.side_effect = ObjectsManagerGetError("boom")

        with flask_app.test_request_context(f'/{MISSING_ID}', method='DELETE'):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cmdb_object)(public_id=MISSING_ID, request_user=SimpleNamespace(public_id=1))

        assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                              insert_cmdb_object config-item sync (off-by-one regression)                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertCmdbObjectSyncsPostInsertCount:
    """In cloud mode the synced config-item count includes the just-created object (no off-by-one)."""

    def test_synced_count_is_recomputed_after_the_insert(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The count sent to the portal is the POST-insert total, not the pre-insert limit-check count."""
        del patched_manager_provider
        flask_app.cloud_mode = True

        # First call = pre-insert limit check (5); second call = post-insert recount (6, the correct total)
        mgr.count_documents.side_effect = [5, 6]
        mgr.insert_object.return_value = 111
        mgr.get_object.return_value = {'public_id': 111, 'type_id': 1, 'fields': []}

        request_user = SimpleNamespace(public_id=1, is_config_item_limit_reached=lambda count: False)

        built_object = ({'type_id': 1, 'fields': []}, MagicMock())

        with flask_app.test_request_context('/', method='POST', json={'type_id': 1, 'fields': []}):
            with patch(f'{ROUTE_PATH}.build_new_object_data', return_value=built_object), \
                 patch(f'{ROUTE_PATH}.guard_object_write_license'), \
                 patch(f'{ROUTE_PATH}.enforce_object_invariants', return_value=[]), \
                 patch(f'{ROUTE_PATH}.sync_select_field_options'), \
                 patch(f'{ROUTE_PATH}.handle_notify_webhooks'), \
                 patch(f'{ROUTE_PATH}.handle_create_object_log'), \
                 patch(f'{ROUTE_PATH}.CmdbObject') as cmdb_object, \
                 patch(f'{ROUTE_PATH}.handle_sync_config_item_count') as sync:
                cmdb_object.from_data.return_value = SimpleNamespace(has_fields_of_type=lambda field_type: False)

                _unwrap(insert_cmdb_object)(request_user=request_user)

        # Off-by-one guard: the buggy version forwarded the pre-insert 5; the fix forwards the post-insert 6
        sync.assert_called_once_with(request_user, 6)
        assert mgr.count_documents.call_count == 2
