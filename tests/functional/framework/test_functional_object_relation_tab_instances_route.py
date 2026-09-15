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
Functional coverage for GET /object_relations/tabs/<object_id>/instances

Verifies the paginated per-tab instances route: the {total, count, results} envelope, per-row
public_id / relation_id / field_values, the server-resolved counterpart (object_id + type_label +
icon + summary_line), a null counterpart when the other object is missing/hidden, pagination, the
required relation_id/role params, the pagination-parameter validation (an unbounded page and an
unusable sort direction are refused), and the manager-error mapping.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest
from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerIterationError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

BASE_URL: str = '/object_relations/tabs'

RELATION_ID: int = 96601
COUNTERPART_TYPE_ID: int = 96602
MAIN_OBJ: int = 96611
CHILD_OBJ: int = 96612      # seeded object -> counterpart resolves
PARENT_OBJ: int = 96613     # NOT seeded as an object -> counterpart is null
OR_IDS: list[int] = [96621, 96622, 96623]

CHILD_NAME: str = 'web-01'


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a relation def, a counterpart type + object, and object relations, cleaned up each test."""
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({'public_id': RELATION_ID})
        object_relations.delete_many({'public_id': {'$in': OR_IDS}})
        types.delete_many({'public_id': COUNTERPART_TYPE_ID})
        objects.delete_many({'public_id': CHILD_OBJ})

    def _or(public_id: int, parent: int, child: int) -> dict[str, Any]:
        return {'public_id': public_id, 'relation_id': RELATION_ID,
                'relation_parent_id': parent, 'relation_child_id': child,
                'field_values': [{'name': 'port', 'value': '443'}]}

    _purge()
    relations.insert_one({
        'public_id': RELATION_ID,
        'relation_name_parent': 'Hosts', 'relation_name_child': 'Hosted On',
        'relation_icon_parent': 'fas fa-server', 'relation_icon_child': 'fas fa-network-wired',
        'relation_color_parent': '#111111', 'relation_color_child': '#222222',
    })
    types.insert_one(make_type_doc(COUNTERPART_TYPE_ID, 'rel-counterpart-type'))
    objects.insert_one({
        'public_id': CHILD_OBJ, 'type_id': COUNTERPART_TYPE_ID, 'active': True, 'author_id': 1,
        'version': '1.0.0', 'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': 'dg-name', 'value': CHILD_NAME}],
    })
    object_relations.insert_many([
        _or(OR_IDS[0], MAIN_OBJ, CHILD_OBJ),
        _or(OR_IDS[1], MAIN_OBJ, CHILD_OBJ),
        _or(OR_IDS[2], PARENT_OBJ, MAIN_OBJ),
    ])
    yield
    _purge()


def _url(object_id: int, role: str, page: int = 1, limit: int = 10) -> str:
    """Builds the instances URL for a tab."""
    return f'{BASE_URL}/{object_id}/instances?relation_id={RELATION_ID}&role={role}&page={page}&limit={limit}'


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestTabInstancesRoute:
    """The instances route paginates a tab's object relations with resolved counterparts."""

    def test_parent_page_resolves_counterpart(self, rest_api) -> None:
        """A parent-role page returns total 2, one row, and the counterpart summary of the child object."""
        response = rest_api.get(_url(MAIN_OBJ, 'parent', page=1, limit=1))

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['total'] == 2
        assert body['count'] == 1
        row = body['results'][0]
        assert row['relation_id'] == RELATION_ID
        assert row['field_values'] == [{'name': 'port', 'value': '443'}]
        assert row['counterpart']['object_id'] == CHILD_OBJ
        assert row['counterpart']['type_label'] == 'rel-counterpart-type'
        assert row['counterpart']['summary_line'] == CHILD_NAME

    def test_pagination_second_page(self, rest_api) -> None:
        """The second page returns the other instance (no overlap with page 1)."""
        first = rest_api.get(_url(MAIN_OBJ, 'parent', page=1, limit=1)).get_json()['results'][0]
        second = rest_api.get(_url(MAIN_OBJ, 'parent', page=2, limit=1)).get_json()['results'][0]

        assert first['public_id'] != second['public_id']

    def test_child_role_counterpart_null_when_missing(self, rest_api) -> None:
        """A child-role row whose counterpart object does not exist returns counterpart null."""
        response = rest_api.get(_url(MAIN_OBJ, 'child'))

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['total'] == 1
        assert body['results'][0]['counterpart'] is None

    def test_missing_params_returns_400(self, rest_api) -> None:
        """Omitting relation_id / role is rejected with 400."""
        assert rest_api.get(f'{BASE_URL}/{MAIN_OBJ}/instances').status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{BASE_URL}/{MAIN_OBJ}/instances?relation_id={RELATION_ID}&role=bogus').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerIterationError surfaces as 400."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_relation_tab_instances',
                            _raiser(ObjectRelationsManagerIterationError('boom')))

        assert rest_api.get(_url(MAIN_OBJ, 'parent')).status_code == HTTPStatus.BAD_REQUEST


class TestTabInstancesPagination:
    """The route refuses pagination parameters it cannot serve, instead of guessing."""

    @pytest.mark.parametrize(
        'query',
        ['limit=0', 'limit=-1', 'limit=1001', 'limit=ten', 'page=0', 'page=none', 'order=5', 'order=desc'],
        ids=['limit-zero', 'limit-negative', 'limit-above-max', 'limit-word',
             'page-zero', 'page-word', 'order-unknown', 'order-word'],
    )
    def test_rejects_unusable_pagination(self, rest_api, query: str) -> None:
        """limit=0 used to mean 'no limit' and order=desc silently sorted ascending (regression)."""
        url = f'{BASE_URL}/{MAIN_OBJ}/instances?relation_id={RELATION_ID}&role=parent&{query}'

        assert rest_api.get(url).status_code == HTTPStatus.BAD_REQUEST

    def test_serves_a_descending_page(self, rest_api) -> None:
        """The documented descending direction reverses the page order."""
        ascending = rest_api.get(f'{_url(MAIN_OBJ, "parent")}&order=1').get_json()['results']
        descending = rest_api.get(f'{_url(MAIN_OBJ, "parent")}&order=-1').get_json()['results']

        assert [row['public_id'] for row in ascending] == list(
            reversed([row['public_id'] for row in descending]))

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error nobody anticipated surfaces as 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_relation_tab_instances', _raiser(RuntimeError('boom')))

        assert rest_api.get(_url(MAIN_OBJ, 'parent')).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised inside the handler keeps its status instead of becoming a 500."""
        def _abort_418(*_args, **_kwargs):
            abort(HTTPStatus.IM_A_TEAPOT)

        monkeypatch.setattr(ObjectRelationsManager, 'get_relation_tab_instances', _abort_418)

        assert rest_api.get(_url(MAIN_OBJ, 'parent')).status_code == HTTPStatus.IM_A_TEAPOT
