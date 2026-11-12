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
Functional tests: the `?projection=` parameter, through the real REST app

  - a projection of a shape it cannot have is a 400 naming the problem, on every list route - it was a 500 for a
    string, a number or a list of numbers, and an operator document was read as a keep
  - every projection the frontend sends to `GET /types/` answers exactly what the whole list answers, projected - the
    type list now reads it from MongoDB, which must not change the answer
  - a projection that drops a key still works on the type list
  - the object list keeps projecting its render keys (`ref-section.component.ts`, the ports overview, the selector)
"""
import json
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    PROJECTION_SHAPE_MESSAGE,
    PROJECTION_KEY_MESSAGE,
    PROJECTION_FLAG_MESSAGE,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_TYPE_ID: int = 93801
TYPE_IDS: list[int] = [FIRST_TYPE_ID, FIRST_TYPE_ID + 1]
OBJECT_ID: int = 93851
LIST_ROUTES: list[str] = ['/types/', '/users/', '/objects/']
SEEDED_TYPES: dict[str, Any] = {'public_id': {'$in': TYPE_IDS}}
TYPE_FILTER: str = json.dumps({'public_id': {'$in': TYPE_IDS}})
OBJECT_FILTER: str = json.dumps([{'$match': {'public_id': OBJECT_ID}}])
PARSE_FAILURE_PREFIX: str = 'Failed to parse the request parameters: '

BAD_PROJECTIONS: dict[str, tuple[str, str]] = {
    'string': ('"abc"', PROJECTION_SHAPE_MESSAGE),
    'number': ('5', PROJECTION_SHAPE_MESSAGE),
    'numbers': ('[1, 2]', PROJECTION_KEY_MESSAGE.format(key=1)),
    'operator': ('{"name": {"$slice": 1}}', PROJECTION_FLAG_MESSAGE.format(key='name', flag={'$slice': 1})),
    'two': ('{"name": 2}', PROJECTION_FLAG_MESSAGE.format(key='name', flag=2)),
}
FRONTEND_TYPE_PROJECTIONS: dict[str, Any] = {
    'type-builder': {'public_id': 1, 'name': 1, 'label': 1, 'render_meta': 1},
    'object-groups': ['public_id', 'label', 'name'],
    'graph-profile': {'public_id': 1, 'label': 1, 'name': 1},
    'port-type-catalog': {'public_id': 1},
}
REF_SECTION_PROJECTION: dict[str, int] = {
    'object_information': 1, 'type_information': 1, 'sections': 1, 'summary_line': 1, 'summaries': 1, 'fields': 1,
}


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Two types and one object of the first; removed again after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.delete_many(SEEDED_TYPES)
    objects.delete_many({'public_id': OBJECT_ID})
    types.insert_many([make_type_doc(public_id, f'projection-route-{public_id}') for public_id in TYPE_IDS])
    objects.insert_one({'public_id': OBJECT_ID, 'type_id': FIRST_TYPE_ID, 'active': True, 'author_id': 1,
                        'version': '1.0.0', 'fields': [{'name': 'dg-name', 'value': 'projected', 'type': 'text'}],
                        'multi_data_sections': []})
    yield
    types.delete_many(SEEDED_TYPES)
    objects.delete_many({'public_id': OBJECT_ID})


def _types(rest_api, projection: Any = None) -> list[dict[str, Any]]:
    """The seeded types as GET /types/ answers them"""
    query: dict[str, Any] = {'filter': TYPE_FILTER, 'limit': 0}

    if projection is not None:
        query['projection'] = json.dumps(projection)

    response = rest_api.get('/types/', query_string=query)

    assert response.status_code == HTTPStatus.OK

    return response.get_json()['results']


def _keep(document: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """The top-level keys of a whole answer the projection keeps"""
    return {key: document[key] for key in keys if key in document}


@pytest.mark.parametrize('route', LIST_ROUTES)
@pytest.mark.parametrize('value, message', list(BAD_PROJECTIONS.values()), ids=list(BAD_PROJECTIONS))
def test_a_projection_of_no_admitted_shape_is_a_400(rest_api, route: str, value: str, message: str) -> None:
    """Refused where the parameters are parsed, naming what is wrong"""
    response = rest_api.get(route, query_string={'projection': value})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == f'{PARSE_FAILURE_PREFIX}{message}'


@pytest.mark.parametrize('projection', list(FRONTEND_TYPE_PROJECTIONS.values()), ids=list(FRONTEND_TYPE_PROJECTIONS))
def test_a_frontend_type_projection_answers_what_the_whole_list_answers(rest_api, projection: Any) -> None:
    """Read from MongoDB now - the answer is the whole answer, trimmed"""
    keys: list[str] = list(projection)
    whole: list[dict[str, Any]] = _types(rest_api)

    assert _types(rest_api, projection) == [_keep(document, keys) for document in whole]


def test_a_projection_that_drops_a_key_still_works_on_the_type_list(rest_api) -> None:
    """Applied by the response, as before"""
    projected: list[dict[str, Any]] = _types(rest_api, {'fields': 0, 'acl': 0})

    assert [document['public_id'] for document in projected] == TYPE_IDS
    assert all('fields' not in document and 'acl' not in document and 'name' in document for document in projected)


def test_the_object_list_keeps_projecting_render_keys(rest_api) -> None:
    """The keys the frontend's reference section reads, none stored as such"""
    response = rest_api.get('/objects/', query_string={
        'filter': OBJECT_FILTER, 'view': 'render', 'projection': json.dumps(REF_SECTION_PROJECTION),
    })

    assert response.status_code == HTTPStatus.OK
    results: list[dict[str, Any]] = response.get_json()['results']
    assert len(results) == 1
    assert set(results[0]) <= set(REF_SECTION_PROJECTION)
    assert results[0]['object_information']['object_id'] == OBJECT_ID
