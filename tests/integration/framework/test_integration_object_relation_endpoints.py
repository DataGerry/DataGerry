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
Integration tests for the CmdbObjectRelation endpoint check, against the real collections

The real ObjectsManager answers the endpoints and the real ACL builder the caller's denied types. Pinned is why
the stored type ids must be the endpoints' own: the definition-update cascade deletes instances BY those ids, so
when a relation stops allowing a child type, exactly the instances whose child really is of that type go - one
stamped by ``resolve_object_relation_endpoints`` is reached, a forged one would not have been
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager, ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    handle_deleted_type_ids,
    resolve_object_relation_endpoints,
)
from tests.utils.ipam_doc_builders import make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

RELATION_ID: int = 98001
PARENT_TYPE_ID: int = 98011
CHILD_TYPE_ID: int = 98012
SECOND_CHILD_TYPE_ID: int = 98013
PROTECTED_TYPE_ID: int = 98014
PARENT_ID: int = 98021
CHILD_ID: int = 98022
SECOND_CHILD_ID: int = 98023
PROTECTED_ID: int = 98024
STAMPED_INSTANCE_ID: int = 98031
KEPT_INSTANCE_ID: int = 98032
ADMIN_GROUP_ID: int = 1

ALL_TYPE_IDS: list[int] = [PARENT_TYPE_ID, CHILD_TYPE_ID, SECOND_CHILD_TYPE_ID, PROTECTED_TYPE_ID]
ALL_OBJECTS: dict[int, int] = {
    PARENT_ID: PARENT_TYPE_ID, CHILD_ID: CHILD_TYPE_ID, SECOND_CHILD_ID: SECOND_CHILD_TYPE_ID,
    PROTECTED_ID: PROTECTED_TYPE_ID,
}
RELATION: dict[str, Any] = {
    'public_id': RELATION_ID,
    'parent_type_ids': [PARENT_TYPE_ID],
    'child_type_ids': [CHILD_TYPE_ID, SECOND_CHILD_TYPE_ID, PROTECTED_TYPE_ID],
}
REQUEST_USER: CmdbUser = CmdbUser(public_id=1, user_name='relation-endpoints', active=True, group_id=ADMIN_GROUP_ID)


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """The REST app's context: the ACL builder reaches the types through ManagerProvider"""
    with rest_api.application.app_context():
        yield


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Types (one ACL-protected against the admin group), their objects; instances purged after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    instances = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': list(ALL_OBJECTS)}})
        instances.delete_many({'relation_id': RELATION_ID})

    _purge()

    for type_id in ALL_TYPE_IDS:
        type_doc = make_type_doc(type_id, f'relation-endpoint-integration-{type_id}')

        if type_id == PROTECTED_TYPE_ID:
            type_doc['acl'] = {'activated': True, 'groups': {'includes': {'2': ['READ']}}}

        types.insert_one(type_doc)

    objects.insert_many([make_object_doc(object_id, type_id, []) for object_id, type_id in ALL_OBJECTS.items()])
    yield instances
    _purge()


def _resolve(database_manager: MongoDatabaseManager, child_id: int) -> tuple[int, int]:
    """The real check, with the real managers"""
    return resolve_object_relation_endpoints(
        RELATION, PARENT_ID, child_id, ObjectsManager(database_manager), REQUEST_USER,
    )


def test_the_real_types_are_answered(database_manager) -> None:
    """Read from the objects themselves"""
    assert _resolve(database_manager, CHILD_ID) == (PARENT_TYPE_ID, CHILD_TYPE_ID)


def test_an_endpoint_the_group_may_not_read_is_refused(database_manager) -> None:
    """The real ACL builder denies the protected type to the admin group"""
    with pytest.raises(HTTPException) as caught:
        _resolve(database_manager, PROTECTED_ID)

    assert str(PROTECTED_ID) in caught.value.description


def test_the_cascade_reaches_exactly_the_instances_of_the_dropped_type(database_manager, collections) -> None:
    """Stamped types are what the definition-update cascade deletes by"""
    for instance_id, child_id in ((STAMPED_INSTANCE_ID, CHILD_ID), (KEPT_INSTANCE_ID, SECOND_CHILD_ID)):
        parent_type_id, child_type_id = _resolve(database_manager, child_id)
        collections.insert_one({
            'public_id': instance_id, 'relation_id': RELATION_ID,
            'relation_parent_id': PARENT_ID, 'relation_parent_type_id': parent_type_id,
            'relation_child_id': child_id, 'relation_child_type_id': child_type_id,
            'field_values': [], 'author_id': 1,
        })

    handle_deleted_type_ids(
        RELATION_ID, RELATION,
        {**RELATION, 'child_type_ids': [SECOND_CHILD_TYPE_ID, PROTECTED_TYPE_ID]},
        ObjectRelationsManager(database_manager),
    )

    remaining = {doc['public_id'] for doc in collections.find({'relation_id': RELATION_ID})}
    assert remaining == {KEPT_INSTANCE_ID}
