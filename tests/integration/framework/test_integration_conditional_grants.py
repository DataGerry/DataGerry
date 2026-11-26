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
Integration tests: the access engine on conditional assignments against real documents in MongoDB (phase 9, R21)

Stored: a Type with a text, a number, a date and a checkbox field; objects spread over them; a user group holding
the role through three conditional assignments (they add up), the administrators through ``"*"``. The engine reads
the assignments, the roles and the Types itself. Pinned, for every object: the list filter (``scope_filter``, run by
MongoDB) and ``can()`` (the in-memory matcher) agree - for the whole collection, for the one Type, for several
operations; an edit is allowed only when both states match; the administrators see everything
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_engine import ScopeOperation, can, scope_filter
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 97701
TYPE_ID: int = 97711
OTHER_TYPE_ID: int = 97712
ROLE_ID: int = 97721
VIEW_ROLE_ID: int = 97722
ADMIN_ROLE_ID: int = 97723
FIRST_OBJECT_ID: int = 97731
ADMIN_GROUP_ID: int = 1
TODAY: datetime = datetime.now(timezone.utc).replace(tzinfo=None, hour=12, minute=0, second=0, microsecond=0)
USER: CmdbUser = CmdbUser(public_id=97741, user_name='conditional-grants', active=True, group_ids=[GROUP_ID])
ADMIN: CmdbUser = CmdbUser(public_id=97742, user_name='conditional-admin', active=True, group_ids=[ADMIN_GROUP_ID])

# Three alternatives - an object matching any one is the group's
SCOPES: list[list[dict[str, Any]]] = [
    [{'field': 'size', 'op': 'between', 'value': [10, 20]}, {'field': 'host', 'op': 'starts_with', 'value': 'web'}],
    [{'field': 'host', 'op': 'not_equals', 'value': 'db-1'}, {'field': 'flag', 'op': 'equals', 'value': True}],
    [{'field': 'seen', 'op': 'gte', 'value': {'days_ago': 7}}, {'field': 'size', 'op': 'is_empty'}],
]

# host, size, seen (days ago or None), flag - one entry left out when its value is the string 'missing'
VALUES: list[tuple[Any, Any, Any, Any]] = [
    ('web-1', 12, None, False), ('web-2', 25, None, False), ('db-1', 15, None, True), ('db-2', 3, None, True),
    ('', None, 1, False), (None, None, 30, False), ('web-3', 'missing', 2, True), ('app', '12', None, True),
    ('web-4', 20, 0, 'missing'), ('db-1', None, 3, True), ('missing', 10, None, False), ('web-5', 9, 8, False),
]


def _object(public_id: int, values: tuple[Any, Any, Any, Any], type_id: int = TYPE_ID) -> dict[str, Any]:
    """A stored object; a 'missing' value has no entry"""
    names: list[str] = ['host', 'size', 'seen', 'flag']
    fields: list[dict[str, Any]] = []

    for name, value in zip(names, values):
        if value == 'missing':
            continue

        if name == 'seen' and value is not None:
            value = TODAY - timedelta(days=value)

        fields.append({'name': name, 'value': value})

    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': fields}


OBJECTS: list[dict[str, Any]] = [_object(FIRST_OBJECT_ID + offset, values) for offset, values in enumerate(VALUES)]
OTHER_OBJECT: dict[str, Any] = _object(FIRST_OBJECT_ID + len(VALUES), VALUES[0], OTHER_TYPE_ID)


def _type(type_id: int) -> dict[str, Any]:
    """The four fields"""
    return {'public_id': type_id, 'name': f'conditional-grants-{type_id}', 'label': 'T', 'author_id': 1,
            'active': True, 'version': '1.0.0', 'global_template_ids': [],
            'fields': [{'type': 'text', 'name': 'host', 'label': 'h'},
                       {'type': 'number', 'name': 'size', 'label': 's'},
                       {'type': 'date', 'name': 'seen', 'label': 'd'},
                       {'type': 'checkbox', 'name': 'flag', 'label': 'f'}],
            'render_meta': {'icon': '', 'externals': [], 'summary': {'fields': []},
                            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                                          'fields': ['host', 'size', 'seen', 'flag']}]},
            'acl': {'activated': False, 'groups': {'includes': {}}}}


def _role(role_id: int, operations: list[str]) -> dict[str, Any]:
    """On both Types"""
    return {'public_id': role_id, 'name': f'conditional-grants-{role_id}', 'description': '',
            'types': [TYPE_ID, OTHER_TYPE_ID], 'operations': operations, 'write_regular_fields': True,
            'field_classes': []}


@pytest.fixture(name='objects', autouse=True)
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The Types, the roles, the assignments and the objects; removed after"""
    database = database_manager.connector.client[database_name]
    assert database[CmdbAccessAssignment.COLLECTION].count_documents({}) == 0, 'an access rule left by another test'
    database[CmdbType.COLLECTION].insert_many([_type(TYPE_ID), _type(OTHER_TYPE_ID)])
    database[CmdbScopeRole.COLLECTION].insert_many([_role(ROLE_ID, ['view', 'edit']), _role(VIEW_ROLE_ID, ['view']),
                                                    _role(ADMIN_ROLE_ID, ['view', 'create', 'edit', 'delete'])])
    database[CmdbAccessAssignment.COLLECTION].insert_many(
        [{'public_id': 97751 + index, 'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': scope, 'description': ''}
         for index, scope in enumerate(SCOPES)]
        + [{'public_id': 97761, 'group_id': ADMIN_GROUP_ID, 'role_id': ADMIN_ROLE_ID, 'scope': '*', 'description': ''}])
    database[CmdbObject.COLLECTION].insert_many([dict(document) for document in [*OBJECTS, OTHER_OBJECT]])

    yield database[CmdbObject.COLLECTION]

    database[CmdbObject.COLLECTION].delete_many({'type_id': {'$in': [TYPE_ID, OTHER_TYPE_ID]}})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [TYPE_ID, OTHER_TYPE_ID]}})


def _filtered(objects: Any, criteria: dict[str, Any]) -> set[int]:
    """The seeded ids MongoDB lets through"""
    seeded: dict[str, Any] = {'type_id': {'$in': [TYPE_ID, OTHER_TYPE_ID]}}

    return {document['public_id'] for document in objects.find({'$and': [seeded, criteria]} if criteria else seeded)}


def _judged(user: CmdbUser, operation: ScopeOperation) -> set[int]:
    """The seeded ids can() allows one by one"""
    return {document['public_id'] for document in [*OBJECTS, OTHER_OBJECT]
            if can(user, operation, document, document if operation is ScopeOperation.EDIT else None).allowed}


@pytest.mark.usefixtures('rest_api_app_context')
class TestTheFilterAndCanAgree:
    """MongoDB and the matcher, object by object"""

    @pytest.mark.parametrize('operation', [ScopeOperation.VIEW, ScopeOperation.EDIT], ids=['view', 'edit'])
    def test_on_the_whole_collection(self, objects: Any, operation: ScopeOperation) -> None:
        """And the matches are the ones the scopes name - neither nothing nor everything"""
        listed: set[int] = _filtered(objects, scope_filter(USER, operation))

        assert listed == _judged(USER, operation)
        assert listed == {FIRST_OBJECT_ID + offset for offset in (0, 3, 4, 6, 7, 8, 9)} | {OTHER_OBJECT['public_id']}

    def test_for_one_type(self, objects: Any) -> None:
        """The Type part drops"""
        one_type: dict[str, Any] = scope_filter(USER, ScopeOperation.VIEW, TYPE_ID)
        listed: set[int] = _filtered(objects, {'$and': [{'type_id': TYPE_ID}, one_type]})

        assert listed == _judged(USER, ScopeOperation.VIEW) - {OTHER_OBJECT['public_id']}

    def test_for_an_operation_no_assignment_grants(self, objects: Any) -> None:
        """Delete: nothing"""
        assert _filtered(objects, scope_filter(USER, ScopeOperation.DELETE)) == set() == \
            _judged(USER, ScopeOperation.DELETE)

    def test_the_administrators_see_everything(self, objects: Any) -> None:
        """Their '*' assignment"""
        assert _filtered(objects, scope_filter(ADMIN, ScopeOperation.VIEW)) == \
            {document['public_id'] for document in [*OBJECTS, OTHER_OBJECT]}


@pytest.mark.usefixtures('rest_api_app_context')
def test_an_edit_needs_both_states_in_scope() -> None:
    """web-1 (12) moved to 30 leaves every scope; moved to 18 stays"""
    before: dict[str, Any] = OBJECTS[0]
    moved_out: dict[str, Any] = _object(before['public_id'], ('web-1', 30, None, False))
    moved_in: dict[str, Any] = _object(before['public_id'], ('web-1', 18, None, False))

    assert not can(USER, ScopeOperation.EDIT, before, moved_out).allowed
    assert can(USER, ScopeOperation.EDIT, before, moved_in).allowed
    assert not can(USER, ScopeOperation.EDIT, moved_out, before).allowed
