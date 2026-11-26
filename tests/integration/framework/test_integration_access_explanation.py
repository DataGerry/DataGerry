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
Integration tests: an explanation's condition marks against real data in MongoDB

Seeded: a site with a room and a device placed in the room, a device elsewhere, a person linked to a user and a device
owned by it. The object's scope block is computed by the real ``ObjectScopeBlocks.block_of`` (a stored block is never
read), the tokens resolved by the real ``ScopeResolver``. Pinned: each condition is marked as MongoDB matches the
compiled condition on the stored object, so every condition met is exactly the database's match of the whole scope
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.object_scope_blocks import ObjectScopeBlocks
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import condition_marks
from cmdb.framework.scope_compiler import ScopeField, ScopeResolver, compile_scope, scope_references
# -------------------------------------------------------------------------------------------------------------------- #

NOW: datetime = datetime(2026, 11, 26, tzinfo=timezone.utc)
SITE, ROOM, PLACED, ELSEWHERE, PERSON = 9881, 9882, 9883, 9884, 9885
OBJECT_IDS: list[int] = [SITE, ROOM, PLACED, ELSEWHERE, PERSON]
NODE_IDS: list[int] = [9891, 9892, 9893, 9894]
PLAIN_TYPE_ID: int = 9895
USER: CmdbUser = CmdbUser(public_id=9896, user_name='explain-marks', active=True, group_ids=[9897])
FIELDS: dict[str, ScopeField] = {'owner': ScopeField('person', selectable=frozenset({'PERSON'}))}
WITHIN_SITE: dict[str, Any] = {'within': SITE}
WITHIN_ELSEWHERE: dict[str, Any] = {'within': ELSEWHERE}
MY_PERSON: dict[str, Any] = {'field': 'owner', 'op': 'equals', 'value': {'user': 'person'}}


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[ObjectsManager]:
    """The tree, the person, the placed device owned by it; removed after"""
    database = database_manager.connector.client[database_name]
    database[CmdbObject.COLLECTION].insert_many([
        {'public_id': SITE, 'type_id': PLAIN_TYPE_ID, 'active': True, 'fields': []},
        {'public_id': ROOM, 'type_id': PLAIN_TYPE_ID, 'active': True, 'fields': []},
        {'public_id': PLACED, 'type_id': PLAIN_TYPE_ID, 'active': True,
         'fields': [{'name': 'owner', 'value': PERSON}, {'name': 'place', 'value': 9892, 'type': 'location'}]},
        {'public_id': ELSEWHERE, 'type_id': PLAIN_TYPE_ID, 'active': True, 'fields': []},
        {'public_id': PERSON, 'type_id': PLAIN_TYPE_ID, 'active': True, 'fields': [],
         'system_ref': {'kind': 'user', 'id': USER.public_id}}])
    parents: dict[int, int] = {SITE: 1, ROOM: 9891, PLACED: 9892, ELSEWHERE: 1}
    database[CmdbLocation.COLLECTION].insert_many([
        {'public_id': node_id, 'name': str(object_id), 'parent': parents[object_id], 'object_id': object_id,
         'type_id': PLAIN_TYPE_ID} for node_id, object_id in zip(NODE_IDS, (SITE, ROOM, PLACED, ELSEWHERE))])

    yield ObjectsManager(database_manager, database_name)

    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': OBJECT_IDS}})
    database[CmdbLocation.COLLECTION].delete_many({'public_id': {'$in': NODE_IDS}})


@pytest.mark.parametrize('conditions, expected', [
    ([WITHIN_SITE, MY_PERSON], [True, True]),
    ([WITHIN_ELSEWHERE, MY_PERSON], [False, True]),
    ([WITHIN_SITE], [True]),
], ids=['both-met', 'elsewhere', 'site-only'])
def test_the_marks_are_the_database_match(objects: ObjectsManager, database_manager: MongoDatabaseManager,
                                          database_name: str, conditions: list[dict[str, Any]],
                                          expected: list[bool]) -> None:
    """Per condition the block and the token; all met exactly when MongoDB matches the whole scope"""
    collection = database_manager.connector.client[database_name][CmdbObject.COLLECTION]
    stored: dict[str, Any] = collection.find_one({'public_id': PLACED}, {'_id': 0, '_scope': 0})
    judged: dict[str, Any] = {**stored, '_scope': ObjectScopeBlocks(objects).block_of(stored)}
    context = ScopeResolver(objects).resolve(USER, scope_references([conditions]))
    marks = condition_marks(conditions, FIELDS, NOW, context, judged)

    ObjectScopeBlocks(objects).refresh([PLACED])
    matched: bool = collection.count_documents({'$and': [compile_scope(conditions, FIELDS, NOW, context),
                                                         {'public_id': PLACED}]}) == 1

    assert [mark['met'] for mark in marks] == expected
    assert all(expected) is matched
