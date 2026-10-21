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
Functional coverage for the DocapiTemplate write contract, through POST and PUT /docapi/template/

Pinned:

  - the frontend's whole DocTemplate passes both routes, and a create -> read -> update round trip keeps it
  - a malformed body is a 400 naming the reason, where several were a 500: no name, not an object, an update
    without an integer id
  - a value of the wrong type is refused and nothing is stored, where it used to break every later render
  - names the by-name route could not address are refused
  - the server owns the identity on create and the author on both routes: an update keeps the stored author
  - the routes' error tails are the shared decorators: a manager failure keeps its 400, anything else is the
    generic 500, and a list the server stopped on its time budget is a 503
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.manager import DocapiTemplatesManager
from cmdb.manager.license_manager.license_service import LicenseService

from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager.docapi_templates_manager import (
    DocapiTemplatesManagerIterationError,
    DocapiTemplatesManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CRUD_URL: str = '/docapi/template'
LIST_URL: str = '/docs/template'
NAME_PREFIX: str = 'tpl-write-contract-'
ADMIN_ID: int = 1
CLIENT_AUTHOR_ID: int = 555
CLIENT_PUBLIC_ID: int = 987001
QUERY_TIME_LIMIT_MS: int = 10


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The document generator is licensed"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='templates')
def fixture_templates(database_manager: MongoDatabaseManager, database_name: str):
    """The template collection, purged of this module's templates before and after"""
    collection = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
    collection.delete_many({'name': {'$regex': f'^{NAME_PREFIX}'}})
    yield collection
    collection.delete_many({'name': {'$regex': f'^{NAME_PREFIX}'}})


def _body(suffix: str, **overrides: Any) -> dict[str, Any]:
    """The DocTemplate the frontend's builder sends, every block normalised"""
    section: dict[str, Any] = {'activated': True, 'content': '<p>{{ root.public_id }}</p>', 'config': {'height': 40}}
    body: dict[str, Any] = {
        'public_id': CLIENT_PUBLIC_ID, 'name': f'{NAME_PREFIX}{suffix}', 'label': 'Write contract',
        'author_id': CLIENT_AUTHOR_ID, 'active': True, 'description': '', 'template_data': '<h1>x</h1>',
        'template_style': '', 'template_type': 'DEFAULT', 'template_parameters': {'type': 7}, 'header': section,
        'footer': dict(section), 'table_of_contents': {'activated': False, 'config': {'level0': {}}},
        'cover_page': {'activated': False, 'content': '', 'config': {}},
        'page_config': {'margin': {'margin-top': 10, 'margin-bottom': 10, 'margin-left': 8, 'margin-right': 8}},
    }
    body.update(overrides)

    return body


def _create(rest_api, suffix: str, **overrides: Any) -> int:
    """Creates a template and answers its public_id"""
    response = rest_api.post(f'{CRUD_URL}/', json=_body(suffix, **overrides))
    assert response.status_code == HTTPStatus.OK, response.get_json()

    return response.get_json()


@pytest.mark.usefixtures('templates')
class TestCreate:
    """POST /docapi/template/"""

    def test_the_frontends_body_is_stored_with_server_owned_identity_and_author(self, rest_api, templates) -> None:
        """The client's public_id and author are dropped, the counter and the request user stamped"""
        public_id = _create(rest_api, 'create')

        stored = templates.find_one({'public_id': public_id})
        assert public_id != CLIENT_PUBLIC_ID
        assert stored['author_id'] == ADMIN_ID
        assert stored['header'] == _body('create')['header']

    @pytest.mark.parametrize('body', [None, [1], 'text'], ids=['null', 'list', 'string'])
    def test_a_body_that_is_no_object_is_a_400(self, rest_api, body: Any) -> None:
        """A list used to answer 500"""
        assert rest_api.post(f'{CRUD_URL}/', json=body).status_code == HTTPStatus.BAD_REQUEST

    def test_a_body_without_name_is_a_400_naming_it(self, rest_api) -> None:
        """It used to answer 500"""
        body = _body('nameless')
        del body['name']

        response = rest_api.post(f'{CRUD_URL}/', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'name' in response.get_json()['message']

    @pytest.mark.parametrize(('key', 'value'), [
        ('template_data', 5), ('header', 'x'), ('template_type', 'BOGUS'), ('template_parameters', 'x'),
        ('active', 'yes'), ('page_config', 'x'), ('footer', {'config': {'height': 'tall'}}),
    ])
    def test_a_wrongly_typed_value_is_refused_and_nothing_stored(
        self, rest_api, templates, key: str, value: Any,
    ) -> None:
        """Each used to be stored, and every later render of the template answered 500 (active: 'deactivated')"""
        response = rest_api.post(f'{CRUD_URL}/', json=_body(f'typed-{key}', **{key: value}))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert key in response.get_json()['message']
        assert templates.count_documents({'name': f'{NAME_PREFIX}typed-{key}'}) == 0

    @pytest.mark.parametrize('name', ['', '   ', f'{NAME_PREFIX}a/b', 7])
    def test_an_unaddressable_name_is_refused(self, rest_api, name: Any) -> None:
        """The by-name route - the builder's availability check - could not reach it"""
        assert rest_api.post(f'{CRUD_URL}/', json=_body('x', name=name)).status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.usefixtures('templates')
class TestUpdate:
    """PUT /docapi/template/"""

    def test_a_round_trip_keeps_the_template(self, rest_api) -> None:
        """Read it, send it back as the builder does: stored and answered unchanged"""
        public_id = _create(rest_api, 'round-trip')
        stored = rest_api.get(f'{CRUD_URL}/{public_id}').get_json()

        response = rest_api.put(f'{CRUD_URL}/', json=stored)

        assert response.status_code == HTTPStatus.OK
        assert rest_api.get(f'{CRUD_URL}/{public_id}').get_json() == stored

    def test_the_stored_author_is_kept(self, rest_api, templates) -> None:
        """The client's author_id used to be stored"""
        public_id = _create(rest_api, 'author')
        body = {**rest_api.get(f'{CRUD_URL}/{public_id}').get_json(), 'author_id': CLIENT_AUTHOR_ID}

        response = rest_api.put(f'{CRUD_URL}/', json=body)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['author_id'] == ADMIN_ID
        assert templates.find_one({'public_id': public_id})['author_id'] == ADMIN_ID

    @pytest.mark.parametrize('public_id', ['missing', None, 'x'])
    def test_an_update_without_an_integer_id_is_a_400(self, rest_api, public_id: Any) -> None:
        """Missing or 'x' used to answer 500"""
        body = _body('no-id', public_id=public_id)

        if public_id == 'missing':
            del body['public_id']

        response = rest_api.put(f'{CRUD_URL}/', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'public_id' in response.get_json()['message']

    def test_a_list_body_is_a_400(self, rest_api) -> None:
        """It used to answer 500"""
        assert rest_api.put(f'{CRUD_URL}/', json=[1]).status_code == HTTPStatus.BAD_REQUEST

    def test_a_wrongly_typed_value_is_refused_and_nothing_changes(self, rest_api, templates) -> None:
        """page_config 'x' used to be stored"""
        public_id = _create(rest_api, 'typed-update')
        before = templates.find_one({'public_id': public_id}, {'_id': 0})
        body = {**rest_api.get(f'{CRUD_URL}/{public_id}').get_json(), 'page_config': 'x'}

        assert rest_api.put(f'{CRUD_URL}/', json=body).status_code == HTTPStatus.BAD_REQUEST
        assert templates.find_one({'public_id': public_id}, {'_id': 0}) == before


@pytest.mark.usefixtures('templates')
class TestTheErrorTails:
    """The shared decorators answer what the hand-written tails did"""

    def test_a_manager_failure_keeps_its_400(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """The update's typed arm, now a table"""
        public_id = _create(rest_api, 'manager-failure')
        body = rest_api.get(f'{CRUD_URL}/{public_id}').get_json()

        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise DocapiTemplatesManagerUpdateError('boom')

        monkeypatch.setattr(DocapiTemplatesManager, 'update_template', _fail)
        response = rest_api.put(f'{CRUD_URL}/', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == 'Could not update the template!'

    def test_anything_else_is_the_generic_500(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unnamed error reaches handle_route_errors"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError('boom')

        monkeypatch.setattr(DocapiTemplatesManager, 'get_template', _fail)

        assert rest_api.get(f'{CRUD_URL}/1').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_list_stopped_on_its_time_budget_is_a_503(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """The list route's hand-written time-limit arm moved onto the decorator"""
        timeout = DocumentQueryTimeLimitError('operation exceeded time limit', QUERY_TIME_LIMIT_MS)
        error = DocapiTemplatesManagerIterationError(timeout)
        error.__cause__ = timeout

        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise error

        monkeypatch.setattr(DocapiTemplatesManager, 'get_templates', _fail)

        assert rest_api.get(f'{LIST_URL}').status_code == HTTPStatus.SERVICE_UNAVAILABLE
