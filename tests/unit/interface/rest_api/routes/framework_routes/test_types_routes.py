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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_routes

Each route handler is unwrapped past its auth / validation / parse decorators and driven inside a
Flask test_request_context. TypesManager (and the other managers) are patched via ManagerProvider;
the route helpers (verify_type_is_unique, get_type_or_404, guard_location_field_removal, ...) and
the response factories are patched at the route module path, so only the route glue - status-code
mapping, branch selection and the order of helper/manager calls - is exercised. No Mongo and no
blueprint registration run
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, BadRequest, NotFound

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerInsertError,
    TypesManagerDeleteError,
    TypesManagerIterationError,
    TypesManagerUpdateError,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_routes import (
    insert_cmdb_type,
    get_cmdb_types,
    get_cmdb_types_overview,
    get_cmdb_type,
    count_objects_of_cmdb_type,
    get_location_field_usage_of_cmdb_type,
    get_selectable_as_parent_usage_of_cmdb_type,
    update_cmdb_type,
    delete_cmdb_type,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_routes'

TYPE_PUBLIC_ID: int = 7

SAMPLE_TYPE_DICT: dict[str, Any] = {'public_id': TYPE_PUBLIC_ID, 'name': 't', 'label': 'T'}

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500


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
    """A single MagicMock returned for every ManagerType the routes request.

    Not spec'd to a single manager class: some handlers (e.g. get_cmdb_types_overview) read
    methods from the Types, Objects and Users managers, all routed here through ManagerProvider.
    """
    return MagicMock()


@pytest.fixture(name='patched_manager_provider')
def fixture_patched_manager_provider(mgr: MagicMock) -> Any:
    """Patches ``ManagerProvider.get_manager`` at the route module path to return ``mgr``."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr) as provider:
        yield provider


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  insert_cmdb_type                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertCmdbType:
    """``insert_cmdb_type`` validates uniqueness, inserts, re-reads, and wires special types."""

    @staticmethod
    def _call(flask_app: Flask, data: dict[str, Any]) -> Any:
        with flask_app.test_request_context('/', method='POST'):
            return _unwrap(insert_cmdb_type)(data=data, request_user=SimpleNamespace(public_id=1))

    def test_returns_created_type_and_stamps_author(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The created type + id reach InsertSingleResponse, and author_id is stamped before insert."""
        del patched_manager_provider
        mgr.insert_type.return_value = TYPE_PUBLIC_ID
        mgr.get_type.return_value = dict(SAMPLE_TYPE_DICT)

        with patch(f'{ROUTE_PATH}.verify_type_is_unique'), patch(f'{ROUTE_PATH}.InsertSingleResponse') as response_ctor:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        stamped = mgr.insert_type.call_args.args[0]
        assert 'author_id' in stamped and 'creation_time' in stamped
        response_ctor.assert_called_once_with(mgr.get_type.return_value, TYPE_PUBLIC_ID)

    def test_returns_404_when_created_type_not_found(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A missing post-insert read aborts 404."""
        del patched_manager_provider
        mgr.insert_type.return_value = TYPE_PUBLIC_ID
        mgr.get_type.return_value = None

        with patch(f'{ROUTE_PATH}.verify_type_is_unique'), pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_NOT_FOUND

    def test_uniqueness_rejection_propagates(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A rejection from verify_type_is_unique aborts before any insert."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.verify_type_is_unique', side_effect=BadRequest()), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_BAD_REQUEST
        mgr.insert_type.assert_not_called()

    def test_special_type_triggers_wiring(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A created type carrying a special_type runs handle_special_types and re-reads."""
        del patched_manager_provider
        mgr.insert_type.return_value = TYPE_PUBLIC_ID
        mgr.get_type.return_value = {**SAMPLE_TYPE_DICT, 'special_type': 'SUBNET'}

        with patch(f'{ROUTE_PATH}.verify_type_is_unique'), \
             patch(f'{ROUTE_PATH}.InsertSingleResponse'), \
             patch(f'{ROUTE_PATH}.handle_special_types') as wiring:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        wiring.assert_called_once()

    def test_insert_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A TypesManagerInsertError maps to HTTP 400."""
        del patched_manager_provider
        mgr.insert_type.side_effect = TypesManagerInsertError('bad')

        with patch(f'{ROUTE_PATH}.verify_type_is_unique'), pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception maps to HTTP 500."""
        del patched_manager_provider
        mgr.insert_type.side_effect = RuntimeError('boom')

        with patch(f'{ROUTE_PATH}.verify_type_is_unique'), pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_cmdb_types                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbTypes:
    """``get_cmdb_types`` iterates and serializes, surfacing iteration errors as 400."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/'):
            return _unwrap(get_cmdb_types)(params=MagicMock(), request_user=MagicMock())

    def test_serializes_iteration_results(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The serialized rows and total are handed to GetMultiResponse."""
        del patched_manager_provider
        mgr.iterate.return_value = SimpleNamespace(results=[SAMPLE_TYPE_DICT], total=1)

        with patch(f'{ROUTE_PATH}.prepare_builder_parameters'), \
             patch(f'{ROUTE_PATH}.CmdbType') as cmdb_type, \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            cmdb_type.to_json.side_effect = lambda row: row
            self._call(flask_app)

        assert response_ctor.call_args.args[0] == [SAMPLE_TYPE_DICT]

    def test_iteration_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A TypesManagerIterationError maps to HTTP 400."""
        del patched_manager_provider
        mgr.iterate.side_effect = TypesManagerIterationError('bad')

        with patch(f'{ROUTE_PATH}.prepare_builder_parameters'), pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, patched_manager_provider: Any,
    ) -> None:
        """Any other exception maps to HTTP 500."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.prepare_builder_parameters', side_effect=RuntimeError('boom')), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                             get_cmdb_types_overview                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbTypesOverview:
    """``get_cmdb_types_overview`` composes {type_data, user_data} items from types + user lookup."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/overview'):
            return _unwrap(get_cmdb_types_overview)(params=MagicMock(), request_user=MagicMock())

    def test_builds_overview_items(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Per-type overview items are built and handed to GetMultiResponse."""
        del patched_manager_provider
        mgr.iterate.return_value = SimpleNamespace(results=[SAMPLE_TYPE_DICT], total=1)
        sentinel_items = [{'item': 1}]

        with patch(f'{ROUTE_PATH}.prepare_builder_parameters'), \
             patch(f'{ROUTE_PATH}.CmdbType') as cmdb_type, \
             patch(f'{ROUTE_PATH}.build_types_overview_items', return_value=sentinel_items) as builder, \
             patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
            cmdb_type.to_json.side_effect = lambda row: row
            self._call(flask_app)

        builder.assert_called_once()
        assert response_ctor.call_args.args[0] is sentinel_items

    def test_iteration_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A TypesManagerIterationError maps to HTTP 400."""
        del patched_manager_provider
        mgr.iterate.side_effect = TypesManagerIterationError('bad')

        with patch(f'{ROUTE_PATH}.prepare_builder_parameters'), pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   get_cmdb_type                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCmdbType:
    """``get_cmdb_type`` returns the document via get_type_or_404, mapping manager errors."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/7'):
            return _unwrap(get_cmdb_type)(public_id=TYPE_PUBLIC_ID, request_user=MagicMock())

    def test_returns_document(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """The fetched document is handed to GetSingleResponse."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_or_404', return_value=SAMPLE_TYPE_DICT), \
             patch(f'{ROUTE_PATH}.GetSingleResponse') as response_ctor:
            self._call(flask_app)

        assert response_ctor.call_args.args[0] == SAMPLE_TYPE_DICT

    def test_not_found_propagates(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """A 404 raised by get_type_or_404 propagates unchanged."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_or_404', side_effect=NotFound()), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_NOT_FOUND

    def test_get_error_maps_to_400(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """A TypesManagerGetError maps to HTTP 400."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_or_404', side_effect=TypesManagerGetError('x')), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                              count_objects_of_cmdb_type                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCountObjectsOfCmdbType:
    """``count_objects_of_cmdb_type`` counts objects of a type, honouring the active-only flag."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/count_objects/7'):
            return _unwrap(count_objects_of_cmdb_type)(public_id=TYPE_PUBLIC_ID, request_user=MagicMock())

    def test_counts_all_objects(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """Without the active-only flag, the count query has no 'active' key and the count is returned."""
        del patched_manager_provider
        mgr.count_documents.return_value = 5

        with patch(f'{ROUTE_PATH}.fetch_only_active_objects', return_value=False), \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app)

        assert 'active' not in mgr.count_documents.call_args.args[0]
        response_ctor.assert_called_once_with(5)

    def test_active_only_adds_active_filter(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """With the active-only flag the count query carries active=True."""
        del patched_manager_provider
        mgr.count_documents.return_value = 2

        with patch(f'{ROUTE_PATH}.fetch_only_active_objects', return_value=True), \
             patch(f'{ROUTE_PATH}.DefaultResponse'):
            self._call(flask_app)

        assert mgr.count_documents.call_args.args[0]['active'] is True

    def test_get_error_maps_to_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """An ObjectsManagerGetError maps to HTTP 400."""
        del patched_manager_provider
        mgr.count_documents.side_effect = ObjectsManagerGetError('x')

        with patch(f'{ROUTE_PATH}.fetch_only_active_objects', return_value=False), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                       get_location_field_usage_of_cmdb_type                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLocationFieldUsage:
    """``get_location_field_usage_of_cmdb_type`` reports the objects still using the location field."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/location_field_usage/7'):
            return _unwrap(get_location_field_usage_of_cmdb_type)(
                public_id=TYPE_PUBLIC_ID, request_user=MagicMock(),
            )

    def test_returns_usage_payload(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """The in_use flag, count and object public_ids are returned via DefaultResponse."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=MagicMock()), \
             patch(f'{ROUTE_PATH}.build_location_usage_payload',
                   return_value={'in_use': True, 'count': 2, 'object_public_ids': [1, 2]}), \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app)

        payload = response_ctor.call_args.args[0]
        assert payload['in_use'] is True
        assert payload['count'] == 2
        assert payload['object_public_ids'] == [1, 2]

    def test_objects_error_maps_to_400(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """An ObjectsManagerGetError maps to HTTP 400."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=MagicMock()), \
             patch(f'{ROUTE_PATH}.build_location_usage_payload', side_effect=ObjectsManagerGetError('x')), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                   get_selectable_as_parent_usage_of_cmdb_type                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSelectableAsParentUsage:
    """``get_selectable_as_parent_usage_of_cmdb_type`` reports whether objects of the type are placed."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/selectable_as_parent_usage/7'):
            return _unwrap(get_selectable_as_parent_usage_of_cmdb_type)(
                public_id=TYPE_PUBLIC_ID, request_user=MagicMock(),
            )

    def test_returns_usage_payload(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """The in_use flag, count and object public_ids are returned via DefaultResponse."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=MagicMock()), \
             patch(f'{ROUTE_PATH}.build_location_usage_payload',
                   return_value={'in_use': True, 'count': 2, 'object_public_ids': [1, 2]}), \
             patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
            self._call(flask_app)

        payload = response_ctor.call_args.args[0]
        assert payload['in_use'] is True
        assert payload['count'] == 2
        assert payload['object_public_ids'] == [1, 2]

    def test_objects_error_maps_to_400(self, flask_app: Flask, patched_manager_provider: Any) -> None:
        """An ObjectsManagerGetError maps to HTTP 400."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=MagicMock()), \
             patch(f'{ROUTE_PATH}.build_location_usage_payload', side_effect=ObjectsManagerGetError('x')), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  update_cmdb_type                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateCmdbType:
    """``update_cmdb_type`` guards immutable/destructive changes, updates, then re-reads."""

    @staticmethod
    def _call(flask_app: Flask, data: dict[str, Any]) -> Any:
        with flask_app.test_request_context('/7', method='PUT'):
            return _unwrap(update_cmdb_type)(
                public_id=TYPE_PUBLIC_ID, data=data, request_user=SimpleNamespace(public_id=1),
            )

    @staticmethod
    def _patches() -> Any:
        """Patches the helper chain the happy path runs through; returns the patch context managers."""
        return [
            patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=SimpleNamespace(special_type=None)),
            patch(f'{ROUTE_PATH}.CmdbType'),
            patch(f'{ROUTE_PATH}.special_type_is_unchanged', return_value=True),
            patch(f'{ROUTE_PATH}.guard_location_field_removal'),
            patch(f'{ROUTE_PATH}.guard_selectable_as_parent_change'),
            patch(f'{ROUTE_PATH}.compute_removed_global_templates', return_value=(set(), {})),
            patch(f'{ROUTE_PATH}.apply_type_update_side_effects'),
        ]

    def test_returns_reread_document(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """After the update, the re-read final document is handed to UpdateSingleResponse."""
        del patched_manager_provider
        final_doc = {**SAMPLE_TYPE_DICT, 'label': 'updated'}
        # the post-update re-reads: the hydrated type for the side effects, then the final document
        mgr.get_type_instance.return_value = SimpleNamespace(special_type=None, public_id=TYPE_PUBLIC_ID)
        mgr.get_type.return_value = final_doc

        with patch(f'{ROUTE_PATH}.UpdateSingleResponse') as response_ctor:
            for ctx in self._patches():
                ctx.start()
            try:
                self._call(flask_app, dict(SAMPLE_TYPE_DICT))
            finally:
                patch.stopall()

        response_ctor.assert_called_once_with(final_doc)

    def test_update_pins_public_id_to_the_url(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A forged body public_id is overwritten with the URL id before the type is persisted."""
        del patched_manager_provider
        final_doc = {**SAMPLE_TYPE_DICT, 'label': 'updated'}
        # the post-update re-reads: the hydrated type for the side effects, then the final document
        mgr.get_type_instance.return_value = SimpleNamespace(special_type=None, public_id=TYPE_PUBLIC_ID)
        mgr.get_type.return_value = final_doc
        forged_payload: dict[str, Any] = {**SAMPLE_TYPE_DICT, 'public_id': 999}

        with patch(f'{ROUTE_PATH}.UpdateSingleResponse'):
            for ctx in self._patches():
                ctx.start()
            try:
                self._call(flask_app, forged_payload)
            finally:
                patch.stopall()

        # The body public_id (999) was pinned back to the URL id before from_data / persist
        assert forged_payload['public_id'] == TYPE_PUBLIC_ID

    def test_special_type_change_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Changing the special_type property aborts 400 before the update."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=SimpleNamespace(special_type='OLD')), \
             patch(f'{ROUTE_PATH}.enforce_special_type_license'), \
             patch(f'{ROUTE_PATH}.CmdbType'), \
             patch(f'{ROUTE_PATH}.special_type_is_unchanged', return_value=False), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_BAD_REQUEST
        mgr.update_type.assert_not_called()

    def test_location_removal_guard_propagates(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A 400 from guard_location_field_removal propagates and no update runs."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=SimpleNamespace(special_type=None)), \
             patch(f'{ROUTE_PATH}.CmdbType'), \
             patch(f'{ROUTE_PATH}.special_type_is_unchanged', return_value=True), \
             patch(f'{ROUTE_PATH}.guard_location_field_removal', side_effect=BadRequest()), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_BAD_REQUEST
        mgr.update_type.assert_not_called()

    def test_selectable_as_parent_guard_propagates(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A 400 from guard_selectable_as_parent_change propagates and no update runs."""
        del patched_manager_provider

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=SimpleNamespace(special_type=None)), \
             patch(f'{ROUTE_PATH}.CmdbType'), \
             patch(f'{ROUTE_PATH}.special_type_is_unchanged', return_value=True), \
             patch(f'{ROUTE_PATH}.guard_location_field_removal'), \
             patch(f'{ROUTE_PATH}.guard_selectable_as_parent_change', side_effect=BadRequest()), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_BAD_REQUEST
        mgr.update_type.assert_not_called()

    def test_update_error_maps_to_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """A TypesManagerUpdateError maps to HTTP 400."""
        del patched_manager_provider
        mgr.update_type.side_effect = TypesManagerUpdateError('x')

        with patch(f'{ROUTE_PATH}.get_type_instance_or_404', return_value=SimpleNamespace(special_type=None)), \
             patch(f'{ROUTE_PATH}.CmdbType'), \
             patch(f'{ROUTE_PATH}.special_type_is_unchanged', return_value=True), \
             patch(f'{ROUTE_PATH}.guard_location_field_removal'), \
             patch(f'{ROUTE_PATH}.guard_selectable_as_parent_change'), \
             patch(f'{ROUTE_PATH}.compute_removed_global_templates', return_value=(set(), {})), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app, dict(SAMPLE_TYPE_DICT))

        assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  delete_cmdb_type                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteCmdbType:
    """``delete_cmdb_type`` checks deletability, deletes, then runs the followup cleanup chain."""

    @staticmethod
    def _call(flask_app: Flask) -> Any:
        with flask_app.test_request_context('/7', method='DELETE'):
            return _unwrap(delete_cmdb_type)(public_id=TYPE_PUBLIC_ID, request_user=MagicMock())

    def test_deletes_and_runs_followup(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """A deletable type is deleted, the followup runs, and the pre-delete doc is returned."""
        del patched_manager_provider
        mgr.get_type.return_value = dict(SAMPLE_TYPE_DICT)

        with patch(f'{ROUTE_PATH}.verify_type_deletable'), \
             patch(f'{ROUTE_PATH}.type_deletion_followup') as followup, \
             patch(f'{ROUTE_PATH}.DeleteSingleResponse') as response_ctor:
            self._call(flask_app)

        mgr.delete_type.assert_called_once_with(TYPE_PUBLIC_ID)
        followup.assert_called_once()
        response_ctor.assert_called_once_with(mgr.get_type.return_value)

    def test_not_deletable_propagates_without_delete(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A 400 from verify_type_deletable propagates and no delete is attempted."""
        del patched_manager_provider
        mgr.get_type.return_value = dict(SAMPLE_TYPE_DICT)

        with patch(f'{ROUTE_PATH}.verify_type_deletable', side_effect=BadRequest()), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST
        mgr.delete_type.assert_not_called()

    def test_delete_error_maps_to_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """A TypesManagerDeleteError maps to HTTP 400."""
        del patched_manager_provider
        mgr.get_type.return_value = dict(SAMPLE_TYPE_DICT)
        mgr.delete_type.side_effect = TypesManagerDeleteError('x')

        with patch(f'{ROUTE_PATH}.verify_type_deletable'), pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_report_count_error_maps_to_400(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A BaseManagerGetError (report counting) maps to HTTP 400."""
        del patched_manager_provider
        mgr.get_type.return_value = dict(SAMPLE_TYPE_DICT)

        with patch(f'{ROUTE_PATH}.verify_type_deletable', side_effect=BaseManagerGetError('x')), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_unexpected_error_maps_to_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """Any other exception maps to HTTP 500."""
        del patched_manager_provider
        mgr.get_type.return_value = dict(SAMPLE_TYPE_DICT)

        with patch(f'{ROUTE_PATH}.verify_type_deletable', side_effect=RuntimeError('boom')), \
             pytest.raises(HTTPException) as exc_info:
            self._call(flask_app)

        assert exc_info.value.code == HTTP_SERVER_ERROR
