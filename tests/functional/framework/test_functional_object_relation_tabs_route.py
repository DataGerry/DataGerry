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
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

TABS_URL: str = '/object_relations/tabs'

RELATION_ID: int = 96501
MAIN_OBJ: int = 96511
CHILD_OBJ: int = 96512
PARENT_OBJ: int = 96513
OR_IDS: list[int] = [96521, 96522, 96523]


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a relation definition + object relations for MAIN_OBJ, cleaning up around each test."""
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({'public_id': RELATION_ID})
        object_relations.delete_many({'public_id': {'$in': OR_IDS}})

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
        response = rest_api.get(f'{TABS_URL}/96599')

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
