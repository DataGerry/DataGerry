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
Functional coverage for GET /object_relations/tabs/<object_id>

Verifies the route returns the ``{'results': [...]}`` relation-tab envelope (one descriptor per
(relation_id, role) with role-oriented label/icon/color + count) and maps manager errors to 400 / 500.
Who may read the tabs is pinned in ``test_functional_object_relation_read_acl``.
"""
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

TABS_URL: str = '/object_relations/tabs'

RELATION_ID: int = 96501
OBJECT_TYPE_ID: int = 96502
MAIN_OBJ: int = 96511
CHILD_OBJ: int = 96512
PARENT_OBJ: int = 96513
EMPTY_OBJ: int = 96514
OR_IDS: list[int] = [96521, 96522, 96523]


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a relation definition, MAIN_OBJ + its type, and its object relations, cleaning up around each test."""
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({'public_id': RELATION_ID})
        object_relations.delete_many({'public_id': {'$in': OR_IDS}})
        types.delete_many({'public_id': OBJECT_TYPE_ID})
        objects.delete_many({'public_id': {'$in': [MAIN_OBJ, EMPTY_OBJ]}})

    def _or(public_id: int, parent: int, child: int) -> dict[str, Any]:
        return {'public_id': public_id, 'relation_id': RELATION_ID,
                'relation_parent_id': parent, 'relation_child_id': child}

    _purge()
    relations.insert_one({
        'public_id': RELATION_ID,
        'relation_name_parent': 'Hosts', 'relation_name_child': 'Hosted On',
        'relation_icon_parent': 'fas fa-server', 'relation_icon_child': 'fas fa-network-wired',
        'relation_color_parent': '#111111', 'relation_color_child': '#222222',
    })
    types.insert_one(make_type_doc(OBJECT_TYPE_ID, 'rel-tabs-type'))
    # The route reads the tab's own object before answering its tabs
    objects.insert_many([
        {'public_id': object_id, 'type_id': OBJECT_TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'fields': []}
        for object_id in (MAIN_OBJ, EMPTY_OBJ)
    ])
    object_relations.insert_many([
        _or(OR_IDS[0], MAIN_OBJ, CHILD_OBJ),
        _or(OR_IDS[1], MAIN_OBJ, CHILD_OBJ),
        _or(OR_IDS[2], PARENT_OBJ, MAIN_OBJ),
    ])
    yield
    _purge()


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestRelationTabsRoute:
    """GET /object_relations/tabs/<object_id> returns the relation-tab descriptors."""

    def test_returns_results_envelope(self, rest_api) -> None:
        """The route returns a results list with a parent tab (count 2) and a child tab (count 1)."""
        response = rest_api.get(f'{TABS_URL}/{MAIN_OBJ}')

        assert response.status_code == HTTPStatus.OK
        results = response.get_json()['results']
        by_role = {tab['role']: tab for tab in results}
        assert by_role['parent']['count'] == 2
        assert by_role['parent']['label'] == 'Hosts'
        assert by_role['parent']['relation_id'] == RELATION_ID
        assert by_role['child']['count'] == 1

    def test_object_without_relations_returns_empty(self, rest_api) -> None:
        """An object with no relations returns an empty results list."""
        response = rest_api.get(f'{TABS_URL}/{EMPTY_OBJ}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []

    def test_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerIterationError surfaces as 400."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_relation_tabs',
                            _raiser(ObjectRelationsManagerIterationError('boom')))

        assert rest_api.get(f'{TABS_URL}/{MAIN_OBJ}').status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error surfaces as 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_relation_tabs', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{TABS_URL}/{MAIN_OBJ}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised inside the handler keeps its status instead of becoming a 500."""
        def _abort_418(*_args, **_kwargs):
            abort(HTTPStatus.IM_A_TEAPOT)

        monkeypatch.setattr(ObjectRelationsManager, 'get_relation_tabs', _abort_418)

        assert rest_api.get(f'{TABS_URL}/{MAIN_OBJ}').status_code == HTTPStatus.IM_A_TEAPOT
