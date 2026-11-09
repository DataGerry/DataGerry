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
Functional tests for the search and list routes over a stored object without a public_id

Only a damaged database holds one (every write path sets a public_id; the unique index admits one document without
it). Measured before the fix: a term it matched answered 500 on `POST /search/`, `GET /search/quick/count/` and the
object list's `?search=` when the id was missing, and a null id made every object with an empty reference field
count as a match. Now the search bar's count is right, and a route that has to READ the damaged object as an object
still refuses - its log naming the document's _id, so it can be found and repaired
"""
import json
import logging
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest
from bson import ObjectId
from pymongo.collection import Collection

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.framework.search.search_constants import SearchResultKey
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SEARCH_URL: str = '/search/'
QUICK_COUNT_URL: str = '/search/quick/count/'
OBJECTS_URL: str = '/objects/'

TYPE_ID: int = 88960
TARGET_ID: int = 88961
REFERRER_ID: int = 88962
UNSET_REFERENCE_ID: int = 88963   # an empty reference field - what a null id would match

TARGET_TERM: str = 'Router-F445'
STRAY_TERM: str = 'stray-f445'
STRAY_DOCUMENT_ID: str = '65f0c0ffee0000000000f445'
STRAY_FORMS: list[str] = ['missing', 'null']


def _object(public_id: int | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A stored CmdbObject document of the module's type."""
    return {
        'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': rows,
    }


@pytest.fixture(name='stray', params=STRAY_FORMS)
def _stray(request: pytest.FixtureRequest, database_manager: MongoDatabaseManager,
           database_name: str) -> Iterator[Collection]:
    """Seeds the type, three sound objects and the damaged document in the requested form; removes all after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'type_id': TYPE_ID})

    damaged: dict[str, Any] = _object(None, [{'name': 'hostname', 'value': STRAY_TERM, 'type': 'text'}])
    damaged['_id'] = ObjectId(STRAY_DOCUMENT_ID)

    if request.param == 'missing':
        del damaged['public_id']

    _purge()
    types.insert_one(make_type_doc(TYPE_ID, 'without-public-id-routes'))
    objects.insert_many([
        _object(TARGET_ID, [{'name': 'hostname', 'value': TARGET_TERM, 'type': 'text'}]),
        _object(REFERRER_ID, [{'name': 'uplink', 'value': TARGET_ID, 'type': 'ref'}]),
        _object(UNSET_REFERENCE_ID, [{'name': 'uplink', 'value': None, 'type': 'ref'}]),
        damaged,
    ])
    yield objects
    _purge()


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    """Everything logged at ERROR, as one text."""
    return '\n'.join(record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR)


@pytest.mark.usefixtures('stray')
class TestTheSearchBarCount:
    """GET /search/quick/count/ counts without reading the objects as objects"""

    def test_a_term_it_matches_counts_it_alone(self, rest_api) -> None:
        """Before: 500 for a missing id, the empty reference field counted along for a null one"""
        response = rest_api.get(f'{QUICK_COUNT_URL}?searchValue={STRAY_TERM}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['total'] == 1

    def test_a_sound_term_counts_the_target_and_its_referrer(self, rest_api) -> None:
        """The damaged document neither breaks nor widens an unrelated term"""
        response = rest_api.get(f'{QUICK_COUNT_URL}?searchValue={TARGET_TERM}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['total'] == len([TARGET_ID, REFERRER_ID])


@pytest.mark.usefixtures('stray')
class TestTheFullSearch:
    """POST /search/ reads every hit as an object"""

    def test_a_sound_term_is_answered(self, rest_api) -> None:
        """A term the damaged document does not match is answered as without it"""
        body: str = json.dumps([{'searchText': TARGET_TERM, 'searchForm': 'text'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[SearchResultKey.TOTAL_RESULTS.value] == len([TARGET_ID, REFERRER_ID])

    def test_a_term_it_matches_is_refused_naming_it(self, rest_api, caplog: pytest.LogCaptureFixture) -> None:
        """It is a hit, and it cannot be read - refused, never silently dropped; the log names the document"""
        body: str = json.dumps([{'searchText': STRAY_TERM, 'searchForm': 'text'}])

        with caplog.at_level(logging.ERROR):
            response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert STRAY_DOCUMENT_ID in _logged(caplog)


@pytest.mark.usefixtures('stray')
class TestTheObjectList:
    """GET /objects/ reads every row as an object"""

    @pytest.mark.parametrize('search', ['', f'&search={STRAY_TERM}'], ids=['plain', 'search'])
    def test_a_page_that_reaches_it_is_refused_naming_it(
            self, rest_api, caplog: pytest.LogCaptureFixture, search: str) -> None:
        """With or without a search: the type's list holds it - refused as before, the log naming it now"""
        with caplog.at_level(logging.ERROR):
            response = rest_api.get(f'{OBJECTS_URL}?filter={{"type_id": {TYPE_ID}}}{search}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert STRAY_DOCUMENT_ID in _logged(caplog)

    def test_a_page_that_does_not_reach_it_is_answered(self, rest_api) -> None:
        """The damage is confined to the listings it appears in"""
        response = rest_api.get(f'{OBJECTS_URL}?filter={{"public_id": {TARGET_ID}}}')

        assert response.status_code == HTTPStatus.OK
        assert [row['public_id'] for row in response.get_json()['results']] == [TARGET_ID]
