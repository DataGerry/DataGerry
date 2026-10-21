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
Functional tests for what a CmdbObjectRelation write takes from its client, through the real REST app

``POST`` / ``PUT /object_relations/`` read both endpoints before anything is written:

  - an endpoint that does not exist - the reproduction that answered 201 - or that the caller may not read is a
    400, with one message for both
  - an endpoint of a type the relation does not allow on that side is a 400
  - the stored type ids are the endpoints' own, whatever the body sends
  - every field value names a field the relation declares, once
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE,
)
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.type_model import CmdbType

from tests.utils.ipam_doc_builders import make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/object_relations'

RELATION_ID: int = 97901
PARENT_TYPE_ID: int = 97911
CHILD_TYPE_ID: int = 97912
OTHER_TYPE_ID: int = 97913
# A child type the relation allows, whose ACL grants the test user's group nothing
PROTECTED_TYPE_ID: int = 97914

PARENT_ID: int = 97921
CHILD_ID: int = 97922
OTHER_TYPED_ID: int = 97923
PROTECTED_ID: int = 97924
SECOND_CHILD_ID: int = 97925
MISSING_ID: int = 97999
FORGED_TYPE_ID: int = 97998

STORED_RELATION_INSTANCE_ID: int = 97931
DECLARED_FIELD: str = 'cable'
UNDECLARED_FIELD: str = 'colour'
# A group the protected type's ACL grants READ - not the test user's
OTHER_GROUP_ID: str = '2'

ALL_TYPE_IDS: list[int] = [PARENT_TYPE_ID, CHILD_TYPE_ID, OTHER_TYPE_ID, PROTECTED_TYPE_ID]
ALL_OBJECTS: dict[int, int] = {
    PARENT_ID: PARENT_TYPE_ID, CHILD_ID: CHILD_TYPE_ID, OTHER_TYPED_ID: OTHER_TYPE_ID,
    PROTECTED_ID: PROTECTED_TYPE_ID, SECOND_CHILD_ID: CHILD_TYPE_ID,
}


@pytest.fixture(name='instances', autouse=True)
def fixture_instances(database_manager: MongoDatabaseManager, database_name: str):
    """The relation, its types and objects; the object relations the tests write are purged after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    instances = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': list(ALL_OBJECTS)}})
        relations.delete_many({'public_id': RELATION_ID})
        instances.delete_many({'relation_id': RELATION_ID})

    _purge()

    for type_id in ALL_TYPE_IDS:
        type_doc = make_type_doc(type_id, f'relation-endpoint-type-{type_id}')

        if type_id == PROTECTED_TYPE_ID:
            type_doc['acl'] = {'activated': True, 'groups': {'includes': {OTHER_GROUP_ID: ['READ']}}}

        types.insert_one(type_doc)

    objects.insert_many([make_object_doc(object_id, type_id, []) for object_id, type_id in ALL_OBJECTS.items()])
    relations.insert_one({
        'public_id': RELATION_ID,
        'relation_name': 'relation-endpoint-test',
        'parent_type_ids': [PARENT_TYPE_ID],
        'child_type_ids': [CHILD_TYPE_ID, PROTECTED_TYPE_ID],
        'fields': [{'type': 'text', 'name': DECLARED_FIELD, 'label': 'Cable'}],
    })
    yield instances
    _purge()


def _payload(parent_id: int = PARENT_ID, child_id: int = CHILD_ID, parent_type_id: int = PARENT_TYPE_ID,
             child_type_id: int = CHILD_TYPE_ID, field_values: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A complete object relation body"""
    return {
        'relation_id': RELATION_ID,
        'relation_parent_id': parent_id,
        'relation_parent_type_id': parent_type_id,
        'relation_child_id': child_id,
        'relation_child_type_id': child_type_id,
        'field_values': field_values if field_values is not None else [],
    }


def _store_instance(instances: Any) -> dict[str, Any]:
    """A stored instance between the parent and the child, bypassing the routes"""
    body = {**_payload(), 'public_id': STORED_RELATION_INSTANCE_ID, 'author_id': 1, 'creation_time': None}
    instances.insert_one(dict(body))

    return body


def _assert_refused(response: Any, *fragments: str) -> None:
    """A 400 whose message names every fragment"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()

    for fragment in fragments:
        assert fragment in response.get_json()['message']


class TestCreate:
    """POST /object_relations/"""

    def test_the_reproduction_is_refused(self, rest_api, instances) -> None:
        """Two objects that do not exist, with type ids outside the relation - stored with a 201 before"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(
            parent_id=MISSING_ID, child_id=MISSING_ID - 1, parent_type_id=FORGED_TYPE_ID, child_type_id=FORGED_TYPE_ID,
        ))

        _assert_refused(response, 'parent', str(MISSING_ID))
        assert instances.count_documents({'relation_id': RELATION_ID}) == 0

    def test_the_stored_types_are_the_endpoints_own(self, rest_api, instances) -> None:
        """A forged type id in the body is overwritten"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(
            parent_type_id=FORGED_TYPE_ID, child_type_id=FORGED_TYPE_ID,
            field_values=[{'name': DECLARED_FIELD, 'value': 'CAT6'}],
        ))

        assert response.status_code == HTTPStatus.CREATED
        stored = instances.find_one({'public_id': response.get_json()['result_id']})
        assert (stored['relation_parent_type_id'], stored['relation_child_type_id']) == (PARENT_TYPE_ID, CHILD_TYPE_ID)

    @pytest.mark.parametrize('parent_id, child_id, role, type_id', [
        (OTHER_TYPED_ID, CHILD_ID, 'parent', OTHER_TYPE_ID),
        (PARENT_ID, OTHER_TYPED_ID, 'child', OTHER_TYPE_ID),
        (CHILD_ID, PARENT_ID, 'parent', CHILD_TYPE_ID),
    ], ids=['parent-type-not-allowed', 'child-type-not-allowed', 'sides-swapped'])
    def test_a_type_the_side_does_not_allow_is_refused(self, rest_api, instances, parent_id: int, child_id: int,
                                                        role: str, type_id: int) -> None:
        """Per side, as the definition-update cascade judges"""
        _assert_refused(rest_api.post(f'{ROUTE_URL}/', json=_payload(parent_id=parent_id, child_id=child_id)),
                        role, f'Type with ID:{type_id}')
        assert instances.count_documents({'relation_id': RELATION_ID}) == 0

    def test_an_unreadable_endpoint_is_answered_like_a_missing_one(self, rest_api, instances) -> None:
        """The protected type's ACL grants the caller's group nothing"""
        unreadable = rest_api.post(f'{ROUTE_URL}/', json=_payload(child_id=PROTECTED_ID))
        missing = rest_api.post(f'{ROUTE_URL}/', json=_payload(child_id=MISSING_ID))

        _assert_refused(unreadable, 'child', str(PROTECTED_ID))
        assert unreadable.get_json()['message'] == missing.get_json()['message'].replace(
            str(MISSING_ID), str(PROTECTED_ID))
        assert instances.count_documents({'relation_id': RELATION_ID}) == 0

    def test_an_undeclared_field_value_is_refused(self, rest_api, instances) -> None:
        """Named in the answer"""
        _assert_refused(rest_api.post(f'{ROUTE_URL}/', json=_payload(
            field_values=[{'name': UNDECLARED_FIELD, 'value': 'red'}],
        )), UNDECLARED_FIELD)

    def test_a_repeated_field_value_is_refused(self, rest_api, instances) -> None:
        """One value per field"""
        _assert_refused(rest_api.post(f'{ROUTE_URL}/', json=_payload(field_values=[
            {'name': DECLARED_FIELD, 'value': 'a'}, {'name': DECLARED_FIELD, 'value': 'b'},
        ])), DECLARED_FIELD)

    def test_a_field_value_without_a_name_is_refused(self, rest_api, instances) -> None:
        """The schema's half"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(field_values=[{'value': 'a'}]))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestUpdate:
    """PUT /object_relations/<id> replaces both endpoints, so it is judged like a create"""

    def test_moving_onto_a_disallowed_type_is_refused(self, rest_api, instances) -> None:
        """And the stored instance keeps its endpoints"""
        body = _store_instance(instances)

        _assert_refused(rest_api.put(f'{ROUTE_URL}/{STORED_RELATION_INSTANCE_ID}',
                                     json={**body, 'relation_child_id': OTHER_TYPED_ID}), 'child')
        assert instances.find_one({'public_id': STORED_RELATION_INSTANCE_ID})['relation_child_id'] == CHILD_ID

    def test_moving_onto_another_allowed_object_restamps_its_type(self, rest_api, instances) -> None:
        """A forged type id beside it is overwritten"""
        body = _store_instance(instances)

        response = rest_api.put(f'{ROUTE_URL}/{STORED_RELATION_INSTANCE_ID}', json={
            **body, 'relation_child_id': SECOND_CHILD_ID, 'relation_child_type_id': FORGED_TYPE_ID,
        })

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = instances.find_one({'public_id': STORED_RELATION_INSTANCE_ID})
        assert (stored['relation_child_id'], stored['relation_child_type_id']) == (SECOND_CHILD_ID, CHILD_TYPE_ID)

    def test_an_undeclared_field_value_is_refused(self, rest_api, instances) -> None:
        """The update's field values are judged too"""
        body = _store_instance(instances)

        _assert_refused(rest_api.put(f'{ROUTE_URL}/{STORED_RELATION_INSTANCE_ID}', json={
            **body, 'field_values': [{'name': UNDECLARED_FIELD, 'value': 'red'}],
        }), UNDECLARED_FIELD)


class TestTheEndpointLookupFailing:
    """A failed read of the endpoints is a 400 of its own, on both verbs, and nothing is written"""

    @pytest.fixture(autouse=True)
    def _failing_find(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The objects read fails"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise BaseManagerGetError('read failed')

        monkeypatch.setattr(ObjectsManager, 'find', _fail)

    def test_on_create(self, rest_api, instances) -> None:
        """No instance is stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE
        assert instances.count_documents({'relation_id': RELATION_ID}) == 0

    def test_on_update(self, rest_api, instances) -> None:
        """The stored instance is unchanged"""
        body = _store_instance(instances)

        response = rest_api.put(f'{ROUTE_URL}/{STORED_RELATION_INSTANCE_ID}', json={
            **body, 'relation_child_id': SECOND_CHILD_ID,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE
        assert instances.find_one({'public_id': STORED_RELATION_INSTANCE_ID})['relation_child_id'] == CHILD_ID

