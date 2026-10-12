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
Functional tests of a CmdbRelation's technical name: unique, and letters, digits, '_' and '-' only

A create or an update naming a name another relation holds is refused with a 400 naming it - by the route's check,
and by the unique index when two writes race past it. A relation keeps its own name on an update. A name the shape
rule refuses is a 400 on create and when it changes; one stored before the rule stays saveable while it is kept
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.interface.rest_api.routes.relation_routes import relation_structure_helper
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    RELATION_NAME_SHAPE_MESSAGE,
    RELATION_NAME_TAKEN_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/relations/'
PARENT_TYPE_ID: int = 79201
CHILD_TYPE_ID: int = 79202
HOLDER_ID: int = 79211
OTHER_ID: int = 79212
LEGACY_ID: int = 79213
NAMES: list[str] = ['name-rule-holder', 'name-rule-other', 'name rule legacy', 'name-rule-new']
HOLDER, OTHER, LEGACY, NEW = NAMES


def _payload(name: str) -> dict[str, Any]:
    """A relation write body."""
    return {
        'relation_name': name, 'relation_name_parent': 'is-parent-of', 'relation_name_child': 'is-child-of',
        'parent_type_ids': [PARENT_TYPE_ID], 'child_type_ids': [CHILD_TYPE_ID], 'sections': [], 'fields': [],
    }


@pytest.fixture(name='relations', autouse=True)
def fixture_relations(database_manager: MongoDatabaseManager, database_name: str):
    """Two relations and one stored before the shape rule, over two seeded types, behind the unique name index"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)

    def _purge() -> None:
        relations.delete_many({RelationKey.RELATION_NAME.value: {'$in': NAMES}})
        types.delete_many({'public_id': {'$in': [PARENT_TYPE_ID, CHILD_TYPE_ID]}})

    _purge()
    # The session builds no declared index; this one is what decides a race
    had_index: bool = RelationKey.RELATION_NAME.value in relations.index_information()
    database_manager.create_indexes(CmdbRelation.COLLECTION, database_name, CmdbRelation.get_index_keys())
    types.insert_many([{'public_id': type_id, 'name': f'name-rule-type-{type_id}', 'label': 'T'}
                       for type_id in (PARENT_TYPE_ID, CHILD_TYPE_ID)])
    relations.insert_many([_payload(name) | {'public_id': public_id}
                           for public_id, name in ((HOLDER_ID, HOLDER), (OTHER_ID, OTHER), (LEGACY_ID, LEGACY))])
    yield relations
    _purge()

    if not had_index:
        relations.drop_index(RelationKey.RELATION_NAME.value)


def _name_of(relations, public_id: int) -> str:
    """The stored name of one relation."""
    return relations.find_one({'public_id': public_id})[RelationKey.RELATION_NAME.value]


class TestUnique:
    """Another relation's name"""

    def test_a_create_naming_a_held_name_is_400(self, rest_api, relations) -> None:
        """Nothing is written"""
        response = rest_api.post(ROUTE_URL, json=_payload(HOLDER))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == RELATION_NAME_TAKEN_MESSAGE.format(name=HOLDER)
        assert relations.count_documents({RelationKey.RELATION_NAME.value: HOLDER}) == 1

    def test_an_update_onto_a_held_name_is_400(self, rest_api, relations) -> None:
        """The stored name stays"""
        response = rest_api.put(f'{ROUTE_URL}{OTHER_ID}', json=_payload(HOLDER))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == RELATION_NAME_TAKEN_MESSAGE.format(name=HOLDER)
        assert _name_of(relations, OTHER_ID) == OTHER

    def test_an_update_keeping_its_own_name_is_saved(self, rest_api) -> None:
        """The holder is the relation itself"""
        assert rest_api.put(f'{ROUTE_URL}{HOLDER_ID}', json=_payload(HOLDER)).status_code == HTTPStatus.ACCEPTED

    def test_another_case_is_another_name(self, rest_api, relations) -> None:
        """Compared exactly"""
        response = rest_api.post(ROUTE_URL, json=_payload(HOLDER.upper()))

        assert response.status_code == HTTPStatus.CREATED
        relations.delete_one({'public_id': response.get_json()['result_id']})

    @pytest.mark.parametrize('method', ['post', 'put'])
    def test_the_index_decides_a_race_with_the_same_400(self, rest_api, relations, monkeypatch, method: str) -> None:
        """The check is skipped, as if the other write landed after it"""
        monkeypatch.setattr(relation_structure_helper, 'abort_if_taken', lambda *_args, **_kwargs: None)
        url = ROUTE_URL if method == 'post' else f'{ROUTE_URL}{OTHER_ID}'

        response = getattr(rest_api, method)(url, json=_payload(HOLDER))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == RELATION_NAME_TAKEN_MESSAGE.format(name=HOLDER)
        assert relations.count_documents({RelationKey.RELATION_NAME.value: HOLDER}) == 1


class TestShape:
    """Letters, digits, '_' and '-'"""

    def test_a_create_with_a_space_is_400(self, rest_api, relations) -> None:
        """Named in the message"""
        response = rest_api.post(ROUTE_URL, json=_payload('name rule new'))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == RELATION_NAME_SHAPE_MESSAGE.format(name='name rule new')
        assert relations.count_documents({RelationKey.RELATION_NAME.value: 'name rule new'}) == 0

    def test_a_stored_name_the_rule_refuses_stays_saveable(self, rest_api) -> None:
        """Kept as it is"""
        assert rest_api.put(f'{ROUTE_URL}{LEGACY_ID}', json=_payload(LEGACY)).status_code == HTTPStatus.ACCEPTED

    def test_changing_it_is_judged(self, rest_api, relations) -> None:
        """To a usable name, or not at all"""
        refused = rest_api.put(f'{ROUTE_URL}{LEGACY_ID}', json=_payload(f'{LEGACY}!'))
        renamed = rest_api.put(f'{ROUTE_URL}{LEGACY_ID}', json=_payload(NEW))

        assert refused.status_code == HTTPStatus.BAD_REQUEST
        assert renamed.status_code == HTTPStatus.ACCEPTED
        assert _name_of(relations, LEGACY_ID) == NEW
