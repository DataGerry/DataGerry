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
Functional tests for "one relation links one ordered pair once", through the real REST app

``POST`` / ``PUT /object_relations/``: a second instance of a (relation, parent, child) is a 400 naming the pair and
nothing is written; the same parent with another child is another pair; an update may keep its own pair, and moving
onto another instance's pair is refused. When the pre-check is beaten by a concurrent write, the unique index
`relation_pair` refuses it and the route answers the same 400 - the index is built here, as the session builds none
"""
from http import HTTPStatus
from typing import Any

import pytest
from pymongo import ASCENDING, IndexModel

from cmdb.manager import ObjectRelationsManager
from cmdb.models.object_relation_model.object_relation_constants import OBJECT_RELATION_PAIR_INDEX
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import OBJECT_RELATION_PAIR_TAKEN_MESSAGE

from tests.functional.framework.test_functional_object_relation_endpoints import (  # pylint: disable=unused-import
    CHILD_ID,
    DECLARED_FIELD,
    PARENT_ID,
    RELATION_ID,
    ROUTE_URL,
    SECOND_CHILD_ID,
    _payload,
    fixture_instances,
)
# -------------------------------------------------------------------------------------------------------------------- #

PAIR_FIELDS: list[str] = ['relation_id', 'relation_parent_id', 'relation_child_id']


def _taken(child_id: int = CHILD_ID) -> str:
    """The 400 naming the pair"""
    return OBJECT_RELATION_PAIR_TAKEN_MESSAGE.format(relation_id=RELATION_ID, parent_id=PARENT_ID, child_id=child_id)


def _create(rest_api, child_id: int = CHILD_ID) -> Any:
    """POST one instance"""
    return rest_api.post(f'{ROUTE_URL}/', json=_payload(child_id=child_id))


def _count(instances, child_id: int = CHILD_ID) -> int:
    """Stored instances of the pair"""
    return instances.count_documents({'relation_id': RELATION_ID, 'relation_parent_id': PARENT_ID,
                                      'relation_child_id': child_id})


@pytest.fixture(name='pair_index')
def fixture_pair_index(instances):
    """The unique index the model declares, built for the test and dropped after"""
    instances.create_indexes([IndexModel([(field, ASCENDING) for field in PAIR_FIELDS],
                                         name=OBJECT_RELATION_PAIR_INDEX, unique=True)])
    yield
    instances.drop_index(OBJECT_RELATION_PAIR_INDEX)


class TestCreate:
    """POST /object_relations/"""

    def test_a_second_instance_of_the_pair_is_refused(self, rest_api, instances) -> None:
        """400 naming the pair; one stored"""
        assert _create(rest_api).status_code == HTTPStatus.CREATED

        response = _create(rest_api)

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _taken())
        assert _count(instances) == 1

    def test_the_same_parent_with_another_child_is_another_pair(self, rest_api, instances) -> None:
        """Both stored"""
        assert _create(rest_api).status_code == HTTPStatus.CREATED
        assert _create(rest_api, SECOND_CHILD_ID).status_code == HTTPStatus.CREATED

    def test_a_lost_race_is_the_same_400(self, rest_api, instances, pair_index, monkeypatch) -> None:
        """The pre-check sees nothing; the index refuses the write"""
        assert _create(rest_api).status_code == HTTPStatus.CREATED
        monkeypatch.setattr(ObjectRelationsManager, 'get_one_by', lambda *_args, **_kwargs: None)

        response = _create(rest_api)

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _taken())
        assert _count(instances) == 1


class TestUpdate:
    """PUT /object_relations/<id>"""

    def test_an_instance_keeps_its_own_pair(self, rest_api, instances) -> None:
        """Changing only its field values"""
        public_id: int = _create(rest_api).get_json()['result_id']
        body = _payload(field_values=[{'name': DECLARED_FIELD, 'value': 'cat6'}])

        assert rest_api.put(f'{ROUTE_URL}/{public_id}', json=body).status_code == HTTPStatus.ACCEPTED

    def test_moving_onto_another_instances_pair_is_refused(self, rest_api, instances) -> None:
        """400 naming the pair; the moved instance keeps its own"""
        assert _create(rest_api).status_code == HTTPStatus.CREATED
        other_id: int = _create(rest_api, SECOND_CHILD_ID).get_json()['result_id']

        response = rest_api.put(f'{ROUTE_URL}/{other_id}', json=_payload())

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _taken())
        assert instances.find_one({'public_id': other_id})['relation_child_id'] == SECOND_CHILD_ID

    def test_a_lost_race_is_the_same_400(self, rest_api, instances, pair_index, monkeypatch) -> None:
        """The pre-check sees nothing; the index refuses the update"""
        assert _create(rest_api).status_code == HTTPStatus.CREATED
        other_id: int = _create(rest_api, SECOND_CHILD_ID).get_json()['result_id']
        monkeypatch.setattr(ObjectRelationsManager, 'get_one_by', lambda *_args, **_kwargs: None)

        response = rest_api.put(f'{ROUTE_URL}/{other_id}', json=_payload())

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST, _taken())
        assert _count(instances) == 1
