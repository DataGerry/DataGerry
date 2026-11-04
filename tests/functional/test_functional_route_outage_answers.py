# DataGerry - OpenSource Enterprise CMDB
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
Functional tests: routes answer a temporary database failure with the app's 503 / 423, never their own 500 / 400

The license routes, the SpecialType list, the ObjectGroup and Relation lists, the report count of a type and the
object import's type lookup each caught ``Exception`` around their work, so a lost connection or a lock timeout became
the route's own 500 - or, for the import, a 400 that tells a client not to retry. The failure is raised at the
manager (or service) the route calls; the route's ``handle_route_errors`` then leaves it to the app's handlers. An
unexpected error still answers each route's own 500, worded as it always was. The search's parameters are refused
400 by shape now that its catch-all is gone - a payload that is no JSON, no list, or a list of non-objects
"""
import io
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.framework.search.search_constants import (
    SEARCH_PARAMETER_NOT_AN_OBJECT_MESSAGE,
    SEARCH_PARAMETERS_NOT_A_LIST_MESSAGE,
    SEARCH_PARAMETERS_NOT_JSON_MESSAGE,
)
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.manager.relations_manager import RelationsManager
from cmdb.manager.reports_manager import ReportsManager
from cmdb.manager.types_manager import TypesManager
from cmdb.interface.rest_api.routes.cmdb_license import license_routes
from cmdb.interface.rest_api.routes.importer_routes import importer_object_routes
# -------------------------------------------------------------------------------------------------------------------- #

TRANSIENT_ANSWERS: list[tuple[type[Exception], HTTPStatus]] = [
    (DocumentNetworkError, HTTPStatus.SERVICE_UNAVAILABLE),
    (DocumentLockTimeoutError, HTTPStatus.LOCKED),
]
TRANSIENT_IDS: list[str] = ['network-503', 'lock-423']
REPORT_TYPE_ID: int = 5
CURRENT_LICENSE_URL: str = '/license/current'
SPECIAL_TYPES_URL: str = '/special_types/?available=true'
OBJECT_GROUPS_URL: str = '/object_groups/'
RELATIONS_URL: str = '/relations/'
REPORT_COUNT_URL: str = f'/reports/{REPORT_TYPE_ID}/count_reports_of_type'
IMPORT_URL: str = '/import/object/'
PARSE_URL: str = '/import/object/parse/'
SEARCH_URL: str = '/search/'


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Object groups sit behind a licensed prefix - every feature licensed"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


def _raise(failure: Exception) -> Any:
    """A stand-in that raises ``failure`` whatever it is called with"""
    def _stub(*_args: Any, **_kwargs: Any) -> Any:
        raise failure

    return _stub


# Each GET route: where its failure is raised, and the 500 it answers for an unexpected error - worded as before
GET_ROUTES: dict[str, tuple[Any, str, str]] = {
    CURRENT_LICENSE_URL: (license_routes, 'request_license_state',
                          'An internal server error occured while retrieving the current license!'),
    SPECIAL_TYPES_URL: (TypesManager, 'get_distinct',
                        'An internal server error occured while retrieving SpecialTypes!'),
    OBJECT_GROUPS_URL: (ObjectGroupsManager, 'iterate_items',
                        'An internal server error occured while retrieving the ObjectGroups!'),
    RELATIONS_URL: (RelationsManager, 'iterate',
                    'An internal server error occured while iterating Relations!'),
    REPORT_COUNT_URL: (ReportsManager, 'count_documents',
                       'An internal server error occured while retrieving the number of Reports for Type with ID: '
                       f'{REPORT_TYPE_ID}!'),
}


def _fail(monkeypatch: pytest.MonkeyPatch, url: str, failure: Exception) -> None:
    """Makes the call the route at ``url`` depends on raise ``failure``"""
    owner, name, _message = GET_ROUTES[url]
    monkeypatch.setattr(owner, name, _raise(failure))


class TestTheGetRoutesLetAnOutageThrough:
    """GET /license/current, /special_types/?available=true, /object_groups/, /relations/, the report count"""

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    @pytest.mark.parametrize('url', list(GET_ROUTES))
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, url: str,
                                                    error: type[Exception], status: HTTPStatus) -> None:
        """Try again later - not an internal error"""
        _fail(monkeypatch, url, error('database unavailable'))

        assert rest_api.get(url).status_code == status

    @pytest.mark.parametrize('url', list(GET_ROUTES))
    def test_an_unexpected_error_keeps_its_500(self, rest_api, monkeypatch, url: str) -> None:
        """Worded as before"""
        _fail(monkeypatch, url, RuntimeError('a bug'))

        response = rest_api.get(url)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == GET_ROUTES[url][2]


class TestRemovingTheLicense:
    """DELETE /license/current"""

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, error: type[Exception],
                                                    status: HTTPStatus) -> None:
        """Try again later"""
        monkeypatch.setattr(license_routes, 'request_license_service', _raise(error('database unavailable')))

        assert rest_api.delete(CURRENT_LICENSE_URL).status_code == status

    def test_an_unexpected_error_keeps_its_500(self, rest_api, monkeypatch) -> None:
        """Worded as before"""
        monkeypatch.setattr(license_routes, 'request_license_service', _raise(RuntimeError('a bug')))

        response = rest_api.delete(CURRENT_LICENSE_URL)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == 'An internal server error occured while removing the license!'


class TestTheObjectImportTypeLookup:
    """POST /import/object/ - the type read used to answer an outage 400 'Could not import objects!'"""

    @staticmethod
    def _post(rest_api) -> Any:
        """A well-formed import of one CSV row into type 1"""
        return rest_api.post(IMPORT_URL, content_type='multipart/form-data', data={
            'file': (io.BytesIO(b'name\nx\n'), 'import.csv'),
            'file_format': 'csv',
            'parser_config': json.dumps({}),
            'importer_config': json.dumps({'type_id': 1}),
        })

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, error: type[Exception],
                                                    status: HTTPStatus) -> None:
        """Not a 400: the request was fine"""
        monkeypatch.setattr(TypesManager, 'get_type', _raise(error('database unavailable')))

        assert self._post(rest_api).status_code == status

    def test_an_unexpected_error_keeps_its_400(self, rest_api, monkeypatch) -> None:
        """The resolution's own answer is unchanged"""
        monkeypatch.setattr(TypesManager, 'get_type', _raise(RuntimeError('a bug')))

        response = self._post(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == 'Could not import objects!'


class TestParsingAnImportFile:
    """POST /import/object/parse/ - a parser error is the file's 400, an outage is not"""

    @staticmethod
    def _post(rest_api) -> Any:
        """A CSV file to parse"""
        return rest_api.post(PARSE_URL, content_type='multipart/form-data', data={
            'file': (io.BytesIO(b'name\nx\n'), 'import.csv'), 'file_format': 'csv',
        })

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, error: type[Exception],
                                                    status: HTTPStatus) -> None:
        """Not 'Could not parse the provided file'"""
        monkeypatch.setattr(importer_object_routes, 'generate_parsed_output', _raise(error('database unavailable')))

        assert self._post(rest_api).status_code == status

    def test_a_parser_error_stays_the_files_400(self, rest_api, monkeypatch) -> None:
        """Unchanged"""
        monkeypatch.setattr(importer_object_routes, 'generate_parsed_output', _raise(ValueError('bad row')))

        response = self._post(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == 'Could not parse the provided file with the given configuration!'


class TestTheSearchParameterShape:
    """GET /search/?query= - refused 400 by shape, each naming what it got"""

    @pytest.mark.parametrize('query, message', [
        ('{broken', SEARCH_PARAMETERS_NOT_JSON_MESSAGE),
        ('5', SEARCH_PARAMETERS_NOT_A_LIST_MESSAGE.format(kind='int')),
        ('{"searchText": "x"}', SEARCH_PARAMETERS_NOT_A_LIST_MESSAGE.format(kind='dict')),
        ('"text"', SEARCH_PARAMETERS_NOT_A_LIST_MESSAGE.format(kind='str')),
        ('["x"]', SEARCH_PARAMETER_NOT_AN_OBJECT_MESSAGE.format(position=0, kind='str')),
        ('[{"searchText": "x", "searchForm": "text"}, 5]',
         SEARCH_PARAMETER_NOT_AN_OBJECT_MESSAGE.format(position=1, kind='int')),
    ], ids=['no-json', 'number', 'non-empty-object', 'string', 'list-of-strings', 'second-entry-a-number'])
    def test_an_unusable_payload_is_refused(self, rest_api, query: str, message: str) -> None:
        """400 with the reason - not the old catch-all's 'unexpected error'"""
        response = rest_api.get(SEARCH_URL, query_string={'query': query})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == message

    @pytest.mark.parametrize('query', [json.dumps([{'searchText': 'x', 'searchForm': 'text'}]), '[]', '{}'],
                             ids=['a-list-of-objects', 'empty-list', 'empty-object'])
    def test_a_usable_payload_still_searches(self, rest_api, query: str) -> None:
        """The shape check lets a list of objects through - and both spellings of no parameters"""
        assert rest_api.get(SEARCH_URL, query_string={'query': query}).status_code == HTTPStatus.OK
