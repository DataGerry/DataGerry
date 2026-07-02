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
Functional smoke for the ``/docapi/template`` (and ``/docs/template``) REST routes

The document-generator feature is license-gated, so each test enables it by stubbing
``LicenseService.has_feature``. Covers the create round-trip, the list envelope, the 404s on a
missing id (get / update / delete), and the render 404 when the template is missing (regression:
this used to surface as a 500 because get_template crashed on a missing id and the route's
guard was unreachable). The PDF render pipeline itself is out of scope.
"""
from http import HTTPStatus
from typing import Any
from urllib.parse import quote
import json

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import DocapiTemplatesManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerInsertError,
    DocapiTemplatesManagerGetError,
    DocapiTemplatesManagerIterationError,
    DocapiTemplatesManagerUpdateError,
    DocapiTemplatesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CRUD_URL: str = '/docapi/template'
LIST_URL: str = '/docs/template'

TPL_ID_FOR_GET: int = 80001
TPL_ID_FOR_UPDATE: int = 80002
TPL_ID_FOR_DELETE: int = 80003
MISSING_TPL_ID: int = 80900
MISSING_OBJECT_ID: int = 80901

ALL_TPL_IDS: list[int] = [TPL_ID_FOR_GET, TPL_ID_FOR_UPDATE, TPL_ID_FOR_DELETE]
CREATE_TEMPLATE_NAME: str = 'tpl-functional-create'


@pytest.fixture(autouse=True)
def _enable_document_generator(monkeypatch: pytest.MonkeyPatch):
    """Stubs the license check so the document-generator routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


def _template_payload(public_id: int, name: str | None = None) -> dict[str, Any]:
    """Builds a DocapiTemplate request body."""
    return {
        'public_id': public_id,
        'name': name or f'tpl-{public_id}',
        'label': 'Template',
        'active': True,
        'template_data': '<p>{{ }}</p>',
    }


def _insert_template_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a DocapiTemplate doc directly via the collection, bypassing the POST route."""
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
        .insert_one(_template_payload(public_id))


@pytest.fixture(scope='module', autouse=True)
def _cleanup_templates_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test templates after the module's tests have run."""
    yield
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_TPL_IDS}})
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
        .delete_many({'name': CREATE_TEMPLATE_NAME})


class TestCreateAndList:
    """POST /docapi/template and GET /docs/template."""

    def test_creates_and_is_listed(self, rest_api,
                                   database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST creates a template that is then retrievable by its assigned public_id."""
        try:
            response = rest_api.post(f'{CRUD_URL}/', json={'name': CREATE_TEMPLATE_NAME, 'active': True})

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            created_id = response.get_json()
            follow_up = rest_api.get(f'{CRUD_URL}/{created_id}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_many({'name': CREATE_TEMPLATE_NAME})

    def test_duplicate_name_is_rejected(self, rest_api,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A second POST reusing an existing name is rejected with 400 and no duplicate is created."""
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        try:
            first = rest_api.post(f'{CRUD_URL}/', json={'name': CREATE_TEMPLATE_NAME, 'active': True})
            assert first.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

            duplicate = rest_api.post(f'{CRUD_URL}/', json={'name': CREATE_TEMPLATE_NAME, 'active': True})

            assert duplicate.status_code == HTTPStatus.BAD_REQUEST
            assert collection.count_documents({'name': CREATE_TEMPLATE_NAME}) == 1
        finally:
            collection.delete_many({'name': CREATE_TEMPLATE_NAME})

    def test_list_returns_results_envelope(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /docs/template returns a results envelope matching X-Total-Count."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            response = rest_api.get(LIST_URL)

            assert response.status_code == HTTPStatus.OK
            body = response.get_json()
            assert 'results' in body
            assert len(body['results']) == int(response.headers['X-Total-Count'])
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})


class TestGetSingle:
    """GET /docapi/template/<id>."""

    def test_get_existing_returns_template(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A known template id returns 200 with the matching template."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            response = rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_GET}')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json()['public_id'] == TPL_ID_FOR_GET
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})

    def test_get_missing_returns_404(self, rest_api) -> None:
        """A missing template id returns 404 (regression: get_template used to crash on None)."""
        response = rest_api.get(f'{CRUD_URL}/{MISSING_TPL_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestUpdate:
    """PUT /docapi/template."""

    def test_update_existing_persists_change(self, rest_api,
                                            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PUT updates the template and the change is retrievable."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            payload = _template_payload(TPL_ID_FOR_UPDATE, name='tpl-renamed')

            response = rest_api.put(f'{CRUD_URL}/', json=payload)

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_UPDATE}')
            assert follow_up.get_json()['name'] == 'tpl-renamed'
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent template returns 404 (regression: used to be success-shaped)."""
        response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(MISSING_TPL_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestDelete:
    """DELETE /docapi/template/<id>."""

    def test_delete_existing_removes_template(self, rest_api,
                                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE removes the template and a subsequent GET returns 404."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_DELETE)
        try:
            response = rest_api.delete(f'{CRUD_URL}/{TPL_ID_FOR_DELETE}')

            assert response.status_code == HTTPStatus.OK
            assert rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_DELETE})

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent template returns 404 (regression: used to be success-shaped)."""
        response = rest_api.delete(f'{CRUD_URL}/{MISSING_TPL_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestFilteredReads:
    """GET /docapi/template/by/<searchfilter> and GET /docapi/template/name/<name>."""

    def test_get_by_searchfilter_returns_matches(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """The searchfilter route returns the templates matching the JSON filter."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            search = quote(json.dumps({'public_id': TPL_ID_FOR_GET}))
            response = rest_api.get(f'{CRUD_URL}/by/{search}')

            assert response.status_code == HTTPStatus.OK
            assert len(response.get_json()) == 1
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})

    def test_get_by_name_returns_template(self, rest_api,
                                         database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The name route returns the template with the given name."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            response = rest_api.get(f"{CRUD_URL}/name/tpl-{TPL_ID_FOR_GET}")

            assert response.status_code == HTTPStatus.OK
            assert response.get_json()['public_id'] == TPL_ID_FOR_GET
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})


class TestRender:
    """GET /docapi/template/<id>/render/<object_id>."""

    def test_render_missing_template_returns_404(self, rest_api) -> None:
        """Rendering a missing template returns 404 (regression: previously a 500)."""
        response = rest_api.get(f'{CRUD_URL}/{MISSING_TPL_ID}/render/{MISSING_OBJECT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_render_missing_object_returns_404(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Rendering an existing template against a missing object returns 404."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            response = rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_GET}/render/{MISSING_OBJECT_ID}')

            assert response.status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_create_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(DocapiTemplatesManager, 'insert_template',
                            _raise(DocapiTemplatesManagerInsertError('boom')))

        response = rest_api.post(f'{CRUD_URL}/', json={'name': 'tpl-err', 'active': True})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_templates',
                            _raise(DocapiTemplatesManagerIterationError('boom')))

        assert rest_api.get(LIST_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_searchfilter_get_error_returns_404(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerGetError on the searchfilter route surfaces as 404."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_templates_by',
                            _raise(DocapiTemplatesManagerGetError('boom')))

        search = quote(json.dumps({'public_id': MISSING_TPL_ID}))
        assert rest_api.get(f'{CRUD_URL}/by/{search}').status_code == HTTPStatus.NOT_FOUND

    def test_get_single_manager_error_returns_404(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerGetError on get-single surfaces as 404."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template',
                            _raise(DocapiTemplatesManagerGetError('boom')))

        assert rest_api.get(f'{CRUD_URL}/{MISSING_TPL_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_by_name_manager_error_returns_404(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerGetError on the name route surfaces as 404."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template_by_name',
                            _raise(DocapiTemplatesManagerGetError('boom')))

        assert rest_api.get(f'{CRUD_URL}/name/whatever').status_code == HTTPStatus.NOT_FOUND

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DocapiTemplatesManagerUpdateError (template found) surfaces as 400."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        monkeypatch.setattr(DocapiTemplatesManager, 'update_template',
                            _raise(DocapiTemplatesManagerUpdateError('boom')))
        try:
            response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(TPL_ID_FOR_UPDATE))

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DocapiTemplatesManagerDeleteError (template found) surfaces as 400."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_DELETE)
        monkeypatch.setattr(DocapiTemplatesManager, 'delete_template',
                            _raise(DocapiTemplatesManagerDeleteError('boom')))
        try:
            assert rest_api.delete(f'{CRUD_URL}/{TPL_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_DELETE})
