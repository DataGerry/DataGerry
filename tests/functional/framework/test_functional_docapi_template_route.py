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
Functional smoke for the ``/docapi/template`` REST routes

The document-generator feature is license-gated, so each test enables it by stubbing
``LicenseService.has_feature``. Covers the create round-trip, the list envelope, the 404s on a
missing id (get / update / delete), and the render 404 when the template is missing (get_template
must not crash on a missing id, or the route's guard is unreachable and the caller sees a 500).

Also pinned: a failed read is a 400 rather than a 404, and the update response is a JSON document rather
than a model repr. The one list, ``GET /docapi/template/``, also serves the object view's document picker:
``type_id`` matches ``template_parameters.type`` (a template whose parameters carry more keys still matches),
``active`` narrows by the flag, ``minimal`` answers ``{public_id, label}`` with the true total - and the
retired ``/docs/template`` and ``/docapi/template/by/<searchfilter>`` answer 404. The PDF render pipeline itself has its
own integration coverage; here only the route's own error mapping is.

The by-name read is a name-availability check rather than a fetch, so it answers 200 with ``null`` for
an unused name, rather than an error the frontend would have to read "free" off. The name is also
IMMUTABLE on update: a PUT carrying any other name than the stored one is a 400, even when that name
is free - which is what makes the availability check answer a lasting question.
"""
from http import HTTPStatus
from typing import Any
from urllib.parse import quote
import json
import re

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.manager import DocapiTemplatesManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerInsertError,
    DocapiTemplatesManagerGetError,
    DocapiTemplatesManagerIterationError,
    DocapiTemplatesManagerUpdateError,
    DocapiTemplatesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CRUD_URL: str = '/docapi/template'
LIST_URL: str = '/docapi/template/'
RETIRED_LIST_URL: str = '/docs/template'
RETIRED_SEARCHFILTER_URL: str = f"{CRUD_URL}/by/{quote(json.dumps({}))}"

TPL_ID_FOR_GET: int = 80001
TPL_ID_FOR_UPDATE: int = 80002
TPL_ID_FOR_DELETE: int = 80003
MISSING_TPL_ID: int = 80900
TPL_ID_FOR_PICKER: int = 80005
TPL_ID_INACTIVE: int = 80006
TPL_ID_EXTRA_PARAMETER: int = 80007
TPL_ID_WITHOUT_FLAG: int = 80008
PICKER_TYPE_ID: int = 80950
MISSING_OBJECT_ID: int = 80901

ALL_TPL_IDS: list[int] = [TPL_ID_FOR_GET, TPL_ID_FOR_UPDATE, TPL_ID_FOR_DELETE, TPL_ID_FOR_PICKER, TPL_ID_INACTIVE,
                          TPL_ID_EXTRA_PARAMETER, TPL_ID_WITHOUT_FLAG]
CREATE_TEMPLATE_NAME: str = 'tpl-functional-create'
UPDATED_TEMPLATE_DATA: str = '<p>updated</p>'


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
        """A missing template id returns 404, rather than get_template crashing on the None."""
        response = rest_api.get(f'{CRUD_URL}/{MISSING_TPL_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestUpdate:
    """PUT /docapi/template."""

    def test_update_existing_persists_change(self, rest_api,
                                            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PUT updates the template and the change is retrievable - on a MUTABLE property."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            payload = _template_payload(TPL_ID_FOR_UPDATE)
            payload['template_data'] = UPDATED_TEMPLATE_DATA

            response = rest_api.put(f'{CRUD_URL}/', json=payload)

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_UPDATE}')
            assert follow_up.get_json()['template_data'] == UPDATED_TEMPLATE_DATA
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent template returns 404, not a success-shaped response."""
        response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(MISSING_TPL_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestTheModelOnCmdbDao:
    """What the move onto CmdbDAO changes on the wire: an id sent as text, a document without `active`"""

    def test_an_update_naming_its_id_as_text_is_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The update schema wants the id as an integer - the model's own conversion is not reached"""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        try:
            payload = {**_template_payload(TPL_ID_FOR_UPDATE), 'public_id': str(TPL_ID_FOR_UPDATE),
                       'template_data': UPDATED_TEMPLATE_DATA}

            response = rest_api.put(f'{CRUD_URL}/', json=payload)

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert 'public_id' in response.get_json()['message']
            assert collection.find_one({'public_id': TPL_ID_FOR_UPDATE})['template_data'] != UPDATED_TEMPLATE_DATA
        finally:
            collection.delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_a_template_stored_without_active_reads_as_active(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """It answered `active: null`, which the builder's checkbox showed - and saved - as false"""
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        collection.insert_one({'public_id': TPL_ID_FOR_GET, 'name': f'tpl-{TPL_ID_FOR_GET}', 'template_data': '<p/>'})
        try:
            response = rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_GET}')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json()['active'] is True
        finally:
            collection.delete_one({'public_id': TPL_ID_FOR_GET})

    def test_an_undeclared_body_key_is_not_stored(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The routes build the template from the raw body; only the declared keys reach the document"""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        try:
            response = rest_api.put(f'{CRUD_URL}/', json={**_template_payload(TPL_ID_FOR_UPDATE), 'evil': 1})

            assert response.status_code == HTTPStatus.OK
            assert 'evil' not in collection.find_one({'public_id': TPL_ID_FOR_UPDATE})
        finally:
            collection.delete_one({'public_id': TPL_ID_FOR_UPDATE})


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
        """Deleting a non-existent template returns 404, not a success-shaped response."""
        response = rest_api.delete(f'{CRUD_URL}/{MISSING_TPL_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestFilteredReads:
    """GET /docapi/template/?minimal=true and GET /docapi/template/name/<name>."""

    def test_the_list_filter_finds_one_template(self, rest_api,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """The list's ?filter= narrows to the template asked for."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            search = quote(json.dumps({'public_id': TPL_ID_FOR_GET}))
            response = rest_api.get(f'{LIST_URL}?filter={search}')

            assert response.status_code == HTTPStatus.OK
            assert [row['public_id'] for row in response.get_json()['results']] == [TPL_ID_FOR_GET]
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})

    def test_minimal_returns_only_public_id_and_label(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """With minimal=true each row carries only public_id + label, not the full document."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            search = quote(json.dumps({'public_id': TPL_ID_FOR_GET}))
            response = rest_api.get(f'{LIST_URL}?filter={search}&minimal=true')

            assert response.status_code == HTTPStatus.OK
            rows = response.get_json()['results']
            assert rows == [{'public_id': TPL_ID_FOR_GET, 'label': 'Template'}]
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
        """Rendering a missing template returns 404."""
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

    def test_minimal_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerIterationError on the minimal list surfaces as 400 too."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_minimal_templates',
                            _raise(DocapiTemplatesManagerIterationError('boom')))

        assert rest_api.get(f'{LIST_URL}?minimal=true').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template',
                            _raise(DocapiTemplatesManagerGetError('boom')))

        assert rest_api.get(f'{CRUD_URL}/{MISSING_TPL_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_by_name_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A DocapiTemplatesManagerGetError on the name route surfaces as 400."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template_by_name',
                            _raise(DocapiTemplatesManagerGetError('boom')))

        assert rest_api.get(f'{CRUD_URL}/name/whatever').status_code == HTTPStatus.BAD_REQUEST

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


TPL_ID_FOR_NAME_CLASH: int = 80004
TAKEN_NAME: str = 'tpl-functional-taken'
UNUSED_NAME: str = 'tpl-functional-unused'


class TestNameIsImmutable:
    """The name is decided on CREATE; a PUT may not move it, whether or not the target is free."""

    def test_update_onto_a_taken_name_is_rejected(self, rest_api,
                                                  database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """
        Renaming onto a name another template carries is refused

        Before the uniqueness check landed, a PUT could produce two templates of the same name - after
        which the by-name route resolved one of them arbitrarily. Now the rename is refused outright.
        """
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        collection.insert_one(_template_payload(TPL_ID_FOR_NAME_CLASH, TAKEN_NAME))
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(TPL_ID_FOR_UPDATE, TAKEN_NAME))

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert collection.find_one({'public_id': TPL_ID_FOR_UPDATE})['name'] != TAKEN_NAME
        finally:
            collection.delete_many({'public_id': {'$in': [TPL_ID_FOR_NAME_CLASH, TPL_ID_FOR_UPDATE]}})

    def test_update_onto_an_unused_name_is_rejected(self, rest_api,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """A free target name is refused too - the name is immutable, not merely unique."""
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(TPL_ID_FOR_UPDATE, UNUSED_NAME))

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert collection.find_one({'public_id': TPL_ID_FOR_UPDATE})['name'] == f'tpl-{TPL_ID_FOR_UPDATE}'
            assert collection.count_documents({'name': UNUSED_NAME}) == 0
        finally:
            collection.delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_update_keeping_its_own_name_is_allowed(self, rest_api,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """The immutability check must not refuse a template its own name - every PUT resends it."""
        collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            payload = _template_payload(TPL_ID_FOR_UPDATE)
            payload['label'] = 'Renamed label'

            response = rest_api.put(f'{CRUD_URL}/', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert collection.find_one({'public_id': TPL_ID_FOR_UPDATE})['label'] == 'Renamed label'
        finally:
            collection.delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_update_response_is_the_template_document(self, rest_api,
                                                      database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
        """
        The response carries the template as a document

        Handing out the model instance itself only serialises by falling back to bson's default
        encoder.
        """
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(TPL_ID_FOR_UPDATE))

            body = response.get_json()
            assert isinstance(body, dict)
            assert body['public_id'] == TPL_ID_FOR_UPDATE
            assert body['name'] == f'tpl-{TPL_ID_FOR_UPDATE}'
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_UPDATE})


class TestUnusedNameIsOk:
    """The by-name read is the frontend's name-availability check, so a free name is a success."""

    def test_get_by_unused_name_returns_200_with_null(self, rest_api) -> None:
        """A name no template carries is 200 + null - it 404'd in between, forcing an error path."""
        response = rest_api.get(f'{CRUD_URL}/name/tpl-does-not-exist')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is None


def _insert_picker_template(database_manager: MongoDatabaseManager, database_name: str, public_id: int,
                            **overrides: Any) -> None:
    """Inserts a template rendered for PICKER_TYPE_ID, with the given keys replaced."""
    payload: dict[str, Any] = {**_template_payload(public_id), 'template_parameters': {'type': PICKER_TYPE_ID}}
    payload.update(overrides)
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).insert_one(payload)


@pytest.fixture(name='picker_templates')
def fixture_picker_templates(database_manager: MongoDatabaseManager, database_name: str):
    """
    Four templates for PICKER_TYPE_ID: active, deactivated, active with an extra parameter key, and one stored
    without the active key (which reads as active)
    """
    _insert_picker_template(database_manager, database_name, TPL_ID_FOR_PICKER, label='B picker')
    _insert_picker_template(database_manager, database_name, TPL_ID_INACTIVE, label='C inactive', active=False)
    _insert_picker_template(database_manager, database_name, TPL_ID_EXTRA_PARAMETER, label='A extra',
                            template_parameters={'type': PICKER_TYPE_ID, 'layout': 'wide'})
    _insert_picker_template(database_manager, database_name, TPL_ID_WITHOUT_FLAG, label='D unflagged')
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).update_one(
        {'public_id': TPL_ID_WITHOUT_FLAG}, {'$unset': {'active': ''}})
    yield
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': [TPL_ID_FOR_PICKER, TPL_ID_INACTIVE, TPL_ID_EXTRA_PARAMETER, TPL_ID_WITHOUT_FLAG]}})


def _listed_ids(response: Any) -> list[int]:
    """The public_ids of a list answer, in answer order."""
    return [row['public_id'] for row in response.get_json()['results']]


@pytest.mark.usefixtures('picker_templates')
class TestTemplateListParameters:
    """
    GET /docapi/template/ - type_id, active and minimal

    The object view's document picker asks ``?type_id=<id>&active=true&minimal=true&limit=0``: every active
    template of one type, as ``{public_id, label}``. The type is matched on ``template_parameters.type``
    """

    def test_the_picker_request_finds_the_active_templates_of_its_type(self, rest_api) -> None:
        """The deactivated template is left out - the render would refuse it; the unflagged one reads as active"""
        response = rest_api.get(f'{LIST_URL}?type_id={PICKER_TYPE_ID}&active=true&minimal=true&limit=0'
                                f'&sort=label&order=1')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == [
            {'public_id': TPL_ID_EXTRA_PARAMETER, 'label': 'A extra'},
            {'public_id': TPL_ID_FOR_PICKER, 'label': 'B picker'},
            {'public_id': TPL_ID_WITHOUT_FLAG, 'label': 'D unflagged'},
        ]

    def test_a_template_whose_parameters_carry_more_keys_still_matches(self, rest_api) -> None:
        """template_parameters.type is matched, not the whole template_parameters object"""
        response = rest_api.get(f'{LIST_URL}?type_id={PICKER_TYPE_ID}&limit=0')

        assert TPL_ID_EXTRA_PARAMETER in _listed_ids(response)

    @pytest.mark.parametrize('active, expected', [
        ('true', [TPL_ID_FOR_PICKER, TPL_ID_EXTRA_PARAMETER, TPL_ID_WITHOUT_FLAG]),
        ('false', [TPL_ID_INACTIVE]),
        (None, [TPL_ID_FOR_PICKER, TPL_ID_INACTIVE, TPL_ID_EXTRA_PARAMETER, TPL_ID_WITHOUT_FLAG]),
    ], ids=['active', 'deactivated', 'absent-both'])
    def test_active_narrows_by_the_flag(self, rest_api, active: str | None, expected: list[int]) -> None:
        """true = active (no stored flag included), false = only deactivated, absent = both"""
        active_param: str = '' if active is None else f'&active={active}'
        response = rest_api.get(f'{LIST_URL}?type_id={PICKER_TYPE_ID}{active_param}&limit=0&sort=public_id&order=1')

        assert _listed_ids(response) == expected

    def test_another_type_matches_nothing(self, rest_api) -> None:
        """No template is rendered for MISSING_TPL_ID as a type"""
        response = rest_api.get(f'{LIST_URL}?type_id={MISSING_TPL_ID}&limit=0')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []

    def test_minimal_pages_and_counts_like_the_full_list(self, rest_api) -> None:
        """One row on the page, the total of all matches, ordered by a key the projection drops"""
        response = rest_api.get(f'{LIST_URL}?type_id={PICKER_TYPE_ID}&minimal=true&limit=1&sort=name&order=-1')

        assert response.get_json()['results'] == [{'public_id': TPL_ID_WITHOUT_FLAG, 'label': 'D unflagged'}]
        assert response.headers['X-Total-Count'] == '4'

    def test_the_server_conditions_and_the_client_filter_both_apply(self, rest_api) -> None:
        """active=false ahead of a client filter asking for active templates: nothing is both"""
        client_filter: str = quote(json.dumps({'active': True}))
        response = rest_api.get(f'{LIST_URL}?type_id={PICKER_TYPE_ID}&active=false&filter={client_filter}')

        assert response.get_json()['results'] == []

    @pytest.mark.parametrize('type_id', ['abc', '0', '-1', '1.5', ''], ids=['text', 'zero', 'negative',
                                                                           'decimal', 'empty'])
    def test_a_type_id_that_is_not_a_positive_integer_is_refused_before_the_read(
        self, rest_api, monkeypatch, type_id: str,
    ) -> None:
        """400 naming the parameter; the manager is never asked"""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_templates', _raise(AssertionError('read')))

        response = rest_api.get(f'{LIST_URL}?type_id={type_id}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "'type_id'" in response.get_json()['message']

    @pytest.mark.parametrize('param', ['active', 'minimal'])
    def test_a_flag_that_is_not_true_or_false_is_refused(self, rest_api, param: str) -> None:
        """The API's one rule for flags"""
        assert rest_api.get(f'{LIST_URL}?{param}=yes').status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('url', [RETIRED_LIST_URL, RETIRED_SEARCHFILTER_URL], ids=['docs-list', 'searchfilter'])
    def test_the_retired_list_urls_are_gone(self, rest_api, url: str) -> None:
        """/docs/template and /docapi/template/by/<searchfilter> answer 404"""
        assert rest_api.get(url).status_code == HTTPStatus.NOT_FOUND


class TestHttpExceptionPassThrough:
    """An HTTPException from a collaborator keeps its own status on the routes that had no arm for it."""

    def test_list_keeps_the_status(self, rest_api, monkeypatch) -> None:
        """The list had no re-raise arm once, so an abort inside would have become a 500."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_templates', _raise(NotFound()))

        assert rest_api.get(LIST_URL).status_code == HTTPStatus.NOT_FOUND

    def test_minimal_list_keeps_the_status(self, rest_api, monkeypatch) -> None:
        """Same for the minimal list."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_minimal_templates', _raise(NotFound()))

        assert rest_api.get(f'{LIST_URL}?minimal=true').status_code == HTTPStatus.NOT_FOUND

    def test_by_name_keeps_the_status(self, rest_api, monkeypatch) -> None:
        """And for the by-name read."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template_by_name', _raise(NotFound()))

        assert rest_api.get(f'{CRUD_URL}/name/whatever').status_code == HTTPStatus.NOT_FOUND


class TestRenderErrorMapping:
    """The render route maps a failing render to a 500 rather than leaking it."""

    def test_render_failure_returns_500(self, rest_api, monkeypatch,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A renderer failure is reported as a server error naming both ids."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_GET)
        try:
            monkeypatch.setattr(
                'cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates'
                '.docapi_template_routes.DocApiRenderer',
                _raise(RuntimeError('boom')),
            )

            response = rest_api.get(f'{CRUD_URL}/{TPL_ID_FOR_GET}/render/{MISSING_OBJECT_ID}')

            assert response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_GET})


RENDER_TYPE_ID: int = 80011
RENDER_OBJECT_ID: int = 80012
RENDER_TPL_ID: int = 80013
RENDER_NAME_FIELD: str = 'dg-name'
PDF_MAGIC: bytes = b'%PDF'

# A rendered document is named like every other export: `<timestamp>_document_<template>-<object>.pdf`,
# built by cmdb.framework.exporter.export_filename_helper - so two renders never share a filename
RENDERED_FILENAME_PATTERN: str = (
    r'attachment; filename="\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}_document_render-'
    + str(RENDER_OBJECT_ID)
    + r'\.pdf"'
)

UNLABELLED_TPL_ID: int = 80014
UNLABELLED_FILENAME_PATTERN: str = (
    r'attachment; filename="\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}_document_tpl-no-label-'
    + str(RENDER_OBJECT_ID)
    + r'\.pdf"'
)


@pytest.fixture(name='renderable')
def fixture_renderable(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the type, object and template the render route needs, and removes them again."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    templates = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': RENDER_TYPE_ID})
        objects.delete_many({'public_id': RENDER_OBJECT_ID})
        templates.delete_many({'public_id': RENDER_TPL_ID})

    _purge()
    types.insert_one(make_type_doc(
        RENDER_TYPE_ID, 'docapi-render-type',
        fields=[{'type': 'text', 'name': RENDER_NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [RENDER_NAME_FIELD]}],
    ))
    objects.insert_one({
        'public_id': RENDER_OBJECT_ID, 'type_id': RENDER_TYPE_ID, 'active': True, 'author_id': 1,
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': RENDER_NAME_FIELD, 'value': 'Rendered Server'}],
    })
    templates.insert_one({
        'public_id': RENDER_TPL_ID,
        'name': 'tpl-functional-render',
        'label': 'Render',
        'active': True,
        'author_id': 1,
        'template_data': '<h1>{{ fields.dg_name }}</h1>',
        'template_style': '',
    })

    yield

    _purge()


class TestRenderHappyPath:
    """
    The render route really produces a PDF

    The pipeline itself is covered by test_integration_docapi_document_generation; what is asserted here
    is that the ROUTE wires it - the template, the object and the request user reach the renderer and the
    bytes come back as an attachment.
    """

    def test_render_returns_a_pdf_attachment(self, rest_api, renderable) -> None:
        """A real template + object render into a PDF the browser downloads."""
        del renderable

        response = rest_api.get(f'{CRUD_URL}/{RENDER_TPL_ID}/render/{RENDER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.mimetype == 'application/pdf'
        assert response.get_data().startswith(PDF_MAGIC)
        assert re.fullmatch(RENDERED_FILENAME_PATTERN, response.headers['Content-Disposition'])

    def test_a_template_without_a_label_is_named_by_its_name(
        self, rest_api, renderable, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The label is optional on the model, so the required unique name stands in for the filename."""
        del renderable
        templates = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
        templates.delete_many({'public_id': UNLABELLED_TPL_ID})
        templates.insert_one({
            'public_id': UNLABELLED_TPL_ID,
            'name': 'tpl-no-label',
            'active': True,
            'author_id': 1,
            'template_data': '<h1>{{ fields.dg_name }}</h1>',
            'template_style': '',
        })

        try:
            response = rest_api.get(f'{CRUD_URL}/{UNLABELLED_TPL_ID}/render/{RENDER_OBJECT_ID}')

            assert response.status_code == HTTPStatus.OK
            assert re.fullmatch(UNLABELLED_FILENAME_PATTERN, response.headers['Content-Disposition'])
        finally:
            templates.delete_many({'public_id': UNLABELLED_TPL_ID})

    def test_render_failure_returns_500(self, rest_api, renderable, monkeypatch) -> None:
        """A failing renderer is a 500 naming both ids, not a leaked traceback."""
        del renderable
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates'
            '.docapi_template_routes.DocApiRenderer',
            _raise(RuntimeError('boom')),
        )

        response = rest_api.get(f'{CRUD_URL}/{RENDER_TPL_ID}/render/{RENDER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestUnexpectedErrorMapping:
    """Every route reports an unmapped failure as a 500 rather than leaking it."""

    def test_create_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while inserting."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template_by_name', _raise(RuntimeError('boom')))

        response = rest_api.post(f'{CRUD_URL}/', json=_template_payload(TPL_ID_FOR_GET))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while iterating."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_templates', _raise(RuntimeError('boom')))

        assert rest_api.get(LIST_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_minimal_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while reading the minimal list."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_minimal_templates', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{LIST_URL}?minimal=true').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while reading one template."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{CRUD_URL}/{MISSING_TPL_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_by_name_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while reading by name."""
        monkeypatch.setattr(DocapiTemplatesManager, 'get_template_by_name', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{CRUD_URL}/name/whatever').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An unmapped failure while updating."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_UPDATE)
        try:
            monkeypatch.setattr(DocapiTemplatesManager, 'update_template', _raise(RuntimeError('boom')))

            response = rest_api.put(f'{CRUD_URL}/', json=_template_payload(TPL_ID_FOR_UPDATE))

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_UPDATE})

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An unmapped failure while deleting."""
        _insert_template_doc(database_manager, database_name, TPL_ID_FOR_DELETE)
        try:
            monkeypatch.setattr(DocapiTemplatesManager, 'delete_template', _raise(RuntimeError('boom')))

            response = rest_api.delete(f'{CRUD_URL}/{TPL_ID_FOR_DELETE}')

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)\
                .delete_one({'public_id': TPL_ID_FOR_DELETE})
