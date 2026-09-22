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
Functional matrix: which manager failure becomes which HTTP status on ``/objects``

One subject, kept apart from the routes' behaviour because it is asserted differently - each test
makes a manager raise and then pins the status the route answers. The value of the matrix is its
completeness, so it reads as a table rather than as a story: read routes first, then the writes and
the deletes
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerIterationError,
    ObjectsManagerDeleteError,
    ObjectsManagerUpdateError,
    ObjectsManagerInsertError,
)
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.security import AccessDeniedError

from tests.functional.framework.objects.objects_route_helpers import (
    BULK_OBJECT_IDS,
    MISSING_OBJECT_ID,
    NAME_FIELD,
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_UPDATE,
    ORIGINAL_VALUE,
    ROUTE_URL,
    TYPE_ID,
    UPDATED_VALUE,
    drop_object,
    insert_object_doc,
    object_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

def _abort_418(*_args, **_kwargs):
    """Aborts with a status no handler maps, proving HTTPExceptions pass through untouched."""
    abort(HTTPStatus.IM_A_TEAPOT)


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """Each route maps its manager exceptions to the documented HTTP status codes."""

    # ---- READ ---- #
    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError from iterate maps the list route to 400."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from iterate maps the list route to 500."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_count_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from count_documents maps the count route to 400."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count').status_code == HTTPStatus.BAD_REQUEST

    def test_count_for_type_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from count_documents maps the count-for-type route to 500."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_single_get_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError from get_object maps the single-get route to 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.FORBIDDEN

    def test_native_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from get_object maps the native route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/native/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_state_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from get_object maps the state-get route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/state/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_references_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError while resolving the referenced object maps to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/references/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_mds_reference_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError from get_object maps the single MDS-reference route to 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/mds_reference').status_code == HTTPStatus.FORBIDDEN

    # ---- GROUP ---- #
    def test_group_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError from group_objects_by_value maps the group route to 400."""
        monkeypatch.setattr(ObjectsManager, 'group_objects_by_value', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.BAD_REQUEST

    def test_group_types_lookup_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while resolving the groups' types maps the group route to 400."""
        monkeypatch.setattr(
            ObjectsManager, 'group_objects_by_value', lambda *_a, **_k: [{'_id': TYPE_ID, 'count': 1, 'result': {}}]
        )
        monkeypatch.setattr(TypesManager, 'get_types_lookup', _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.BAD_REQUEST

    # ---- WRITE / DELETE ---- #
    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError raised inside the update pipeline maps PUT to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_OBJECT_ID}', json=object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from the delete target lookup maps DELETE to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_many_delete_error_returns_500(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """An ObjectsManagerDeleteError during a bulk delete maps to 500."""
        insert_object_doc(database_manager, database_name, BULK_OBJECT_IDS[0], 'x')
        monkeypatch.setattr(ObjectsManager, 'delete_object', _raiser(ObjectsManagerDeleteError('boom')))
        monkeypatch.setattr(ObjectsManager, 'delete_objects_from_risk_assessment_cascade', lambda *_a, **_k: None)

        try:
            response = rest_api.delete(f'{ROUTE_URL}/delete/{BULK_OBJECT_IDS[0]}')
            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            drop_object(database_manager, database_name, BULK_OBJECT_IDS[0])


class TestErrorMappingWriteAndDelete:
    """Per-route exception handlers for the write / delete routes map to the right status codes."""

    def test_insert_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerInsertError from insert_object maps POST to 400."""
        monkeypatch.setattr(ObjectsManager, 'insert_object', _raiser(ObjectsManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError from insert_object maps POST to 403."""
        monkeypatch.setattr(ObjectsManager, 'insert_object', _raiser(AccessDeniedError('nope')))

        response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_single_get_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from get_object maps the single-get route to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_mds_references_plural_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError maps the plural MDS-references route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/mds_references').status_code == HTTPStatus.BAD_REQUEST

    def test_references_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while resolving references maps to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/references/{MISSING_OBJECT_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_patch_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from the patch object lookup maps PATCH to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        response = rest_api.patch(f'{ROUTE_URL}/{MISSING_OBJECT_ID}', json={'fields': [{'name': 'a', 'value': 1}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError during patch maps PATCH to 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        response = rest_api.patch(f'{ROUTE_URL}/{MISSING_OBJECT_ID}', json={'fields': [{'name': 'a', 'value': 1}]})

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from the delete target lookup maps DELETE to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_state_update_error_returns_400(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """An ObjectsManagerUpdateError while toggling the state maps PUT /state to 400."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_UPDATE, 'x')
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(ObjectsManagerUpdateError('boom')))

        try:
            # seeded object is active=True, so sending False is a real state change that reaches update_object
            response = rest_api.put(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_UPDATE}', json=False)
            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            drop_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)


class TestReadRouteErrorMapping:
    """The remaining per-route exception handlers of the read routes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_GET, ORIGINAL_VALUE)
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_GET)

    def test_rendered_get_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError while reading maps the rendered GET to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_rendered_get_render_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """A renderer failure is reported as 'could not be rendered', not as a missing object."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes.CmdbMultiRender',
            _raiser(RuntimeError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised inside the list handler keeps its own status."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _abort_418)

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.IM_A_TEAPOT

    def test_total_count_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from count_documents maps GET /count to 400."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count').status_code == HTTPStatus.BAD_REQUEST

    def test_total_count_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from count_documents maps GET /count to 500."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_total_count_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """The count route re-raises an HTTPException instead of turning it into a 500."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _abort_418)

        assert rest_api.get(f'{ROUTE_URL}/count').status_code == HTTPStatus.IM_A_TEAPOT

    def test_type_count_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError maps GET /count/<type_id> to 400."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_type_count_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """The per-type count route re-raises an HTTPException too."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _abort_418)

        assert rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').status_code == HTTPStatus.IM_A_TEAPOT

    def test_native_get_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial on the native read is a 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_GET}').status_code == HTTPStatus.FORBIDDEN

    def test_native_get_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on the native read is a 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_GET}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_group_by_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from the grouping maps the dashboard route to 400."""
        monkeypatch.setattr(ObjectsManager, 'group_objects_by_value', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.BAD_REQUEST

    def test_group_by_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from the grouping maps the dashboard route to 500."""
        monkeypatch.setattr(ObjectsManager, 'group_objects_by_value', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_mds_reference_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError maps the single MDS reference route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/mds_reference').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_mds_reference_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the single MDS reference route to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/mds_reference').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_mds_references_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial in the batch route is a 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/mds_references').status_code \
            == HTTPStatus.FORBIDDEN

    def test_mds_references_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error in the batch route is a 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/mds_references').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_references_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError from references() maps the route to 400."""
        monkeypatch.setattr(ObjectsManager, 'references', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/references/{OBJECT_ID_FOR_GET}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_references_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial on the reference route is a 403."""
        monkeypatch.setattr(ObjectsManager, 'references', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/references/{OBJECT_ID_FOR_GET}').status_code \
            == HTTPStatus.FORBIDDEN

    def test_state_get_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial on the state read is a 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_GET}').status_code == HTTPStatus.FORBIDDEN

    def test_state_get_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on the state read is a 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_GET}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR


class TestWriteAndDeleteErrorMapping:
    """The remaining per-route exception handlers of the write / delete routes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the target object and drops it afterwards.

        MISSING_OBJECT_ID is dropped too: the insert tests below post it, and the read-back one really
        does store it - leaving it behind would make every later 'missing object' test find one.
        """
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_UPDATE, ORIGINAL_VALUE)
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)
        drop_object(database_manager, database_name, MISSING_OBJECT_ID)

    def _payload(self) -> dict[str, Any]:
        """The full-object payload the PUT route validates."""
        return object_payload(OBJECT_ID_FOR_UPDATE, UPDATED_VALUE)

    # ---- insert ---- #
    def test_insert_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError while normalising the payload maps POST to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_new_object_public_id', _raiser(ObjectsManagerGetError('boom')))

        payload = object_payload(MISSING_OBJECT_ID, 'x')
        del payload['public_id']

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps POST to 500."""
        monkeypatch.setattr(ObjectsManager, 'insert_object', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=object_payload(MISSING_OBJECT_ID, 'x')).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_unreadable_creation_returns_500(self, rest_api, monkeypatch) -> None:
        """The object IS stored, so a failing read-back is a 500 - not a 404 claiming it is missing."""
        original = ObjectsManager.get_object
        calls = {'count': 0}

        def _second_read_missing(self, *args, **kwargs):
            calls['count'] += 1

            return None if calls['count'] > 1 else original(self, *args, **kwargs)

        monkeypatch.setattr(ObjectsManager, 'get_object', _second_read_missing)

        response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- update ---- #
    def test_update_write_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerUpdateError maps PUT to 400."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(ObjectsManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}', json=self._payload()).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial maps PUT to 403."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.put(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}', json=self._payload()).status_code \
            == HTTPStatus.FORBIDDEN

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps PUT to 500."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}', json=self._payload()).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- patch ---- #
    def test_patch_write_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerUpdateError maps PATCH to 400."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(ObjectsManagerUpdateError('boom')))

        response = rest_api.patch(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}',
            json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps PATCH to 500."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(RuntimeError('boom')))

        response = rest_api.patch(
            f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}',
            json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- state ---- #
    def test_state_put_missing_object_returns_404(self, rest_api) -> None:
        """Toggling the state of a non-existent object is a 404."""
        assert rest_api.put(f'{ROUTE_URL}/state/{MISSING_OBJECT_ID}', json=False).status_code \
            == HTTPStatus.NOT_FOUND

    def test_state_put_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError maps the state toggle to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_UPDATE}', json=False).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_state_put_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial maps the state toggle to 403."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.put(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_UPDATE}', json=False).status_code \
            == HTTPStatus.FORBIDDEN

    def test_state_put_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the state toggle to 500."""
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_UPDATE}', json=False).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- delete ---- #
    def test_delete_missing_object_returns_404(self, rest_api) -> None:
        """Deleting a non-existent object is a 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial on the delete is a 403 - it used to fall through to a 500 (regression)."""
        monkeypatch.setattr(ObjectsManager, 'delete_with_follow_up', _raiser(AccessDeniedError('nope')))

        assert rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}').status_code == HTTPStatus.FORBIDDEN

    def test_delete_manager_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerDeleteError maps the delete to 500."""
        monkeypatch.setattr(ObjectsManager, 'delete_with_follow_up', _raiser(ObjectsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_reference_scrub_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A failure while removing the references to the deleted object is a 500."""
        monkeypatch.setattr(
            ObjectsManager, 'delete_all_object_references', _raiser(ObjectsManagerUpdateError('boom')),
        )

        assert rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_many_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An ACL denial on the bulk delete is a 403 - it used to be a 500 (regression)."""
        monkeypatch.setattr(ObjectsManager, 'delete_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.delete(f'{ROUTE_URL}/delete/{OBJECT_ID_FOR_UPDATE}').status_code \
            == HTTPStatus.FORBIDDEN

    def test_delete_many_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError while reading the targets maps the bulk delete to 400."""
        monkeypatch.setattr(ObjectsManager, 'find', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/delete/{OBJECT_ID_FOR_UPDATE}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_delete_many_manager_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerDeleteError maps the bulk delete to 500."""
        monkeypatch.setattr(ObjectsManager, 'delete_object', _raiser(ObjectsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/delete/{OBJECT_ID_FOR_UPDATE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_many_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the bulk delete to 500."""
        monkeypatch.setattr(ObjectsManager, 'find', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/delete/{OBJECT_ID_FOR_UPDATE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR
