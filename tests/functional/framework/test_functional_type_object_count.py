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
Functional tests: `GET /types/count_objects/<id>` is the pre-check of the Type delete

The delete page shows the number and offers the delete only at 0, and `DELETE /types/<id>` refuses a Type that
still has objects. So the route must answer what the guard counts: every object of the Type, active or not,
whatever the request's active-only flag. A caller whose group the Type's ACL denies READ is refused (403) rather
than given a count: an ACL lives on the Type, so a scoped count would be the total or 0, and a 0 would offer a delete
the guard refuses.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/types'

COUNTED_TYPE_ID: int = 89601
ACTIVE_OBJECT_ID: int = 89611
INACTIVE_OBJECT_ID: int = 89612
OBJECT_IDS: list[int] = [ACTIVE_OBJECT_ID, INACTIVE_OBJECT_ID]

VIEWER_GROUP_ID: int = 89621
VIEWER_ID: int = 89622
VIEWER_NAME: str = 'type-count-viewer'

NAME_FIELD: str = 'name'
ACTIVE_ONLY_QUERY: str = '?onlyActiveObjCookie=true'


def _type_doc() -> dict[str, Any]:
    """A Type whose objects only the admin group may READ."""
    return {
        'public_id': COUNTED_TYPE_ID, 'name': f'type-count-{COUNTED_TYPE_ID}', 'label': 'Counted',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube', 'summary': {'fields': [NAME_FIELD]}, 'externals': [],
            'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
        },
        'acl': {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}},
    }


def _object_doc(public_id: int, active: bool) -> dict[str, Any]:
    """An object of the counted Type."""
    return {
        'public_id': public_id, 'type_id': COUNTED_TYPE_ID, 'active': active, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': f'object-{public_id}'}],
    }


def _viewer() -> CmdbUser:
    """A member of a group holding the Type view right alone - the Type's ACL grants it nothing."""
    return CmdbUser(public_id=VIEWER_ID, user_name=VIEWER_NAME, active=True, group_id=VIEWER_GROUP_ID)


def _count(rest_api, query: str = '', **user: Any) -> Any:
    """GET the pre-check's count."""
    return rest_api.get(f'{ROUTE_URL}/count_objects/{COUNTED_TYPE_ID}{query}', **user)


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the Type, the viewer group and user; each test adds the objects it needs; everything is removed."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': COUNTED_TYPE_ID})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        groups.delete_many({'public_id': VIEWER_GROUP_ID})
        users.delete_many({'public_id': VIEWER_ID})

    _purge()
    types.insert_one(_type_doc())
    groups.insert_one({'public_id': VIEWER_GROUP_ID, 'name': VIEWER_NAME, 'label': VIEWER_NAME,
                       'rights': [TypeRight.VIEW.value]})
    users.insert_one({'public_id': VIEWER_ID, 'user_name': VIEWER_NAME, 'active': True, 'group_id': VIEWER_GROUP_ID,
                      'registration_time': datetime.now(timezone.utc)})
    yield types, objects
    _purge()


class TestTheCountIsTheDeleteGuards:
    """The pre-check answers the guard's question."""

    def test_every_object_is_counted_active_or_not(self, rest_api, collections) -> None:
        """One active and one inactive object: 2"""
        _, objects = collections
        objects.insert_many([_object_doc(ACTIVE_OBJECT_ID, True), _object_doc(INACTIVE_OBJECT_ID, False)])

        response = _count(rest_api)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == len(OBJECT_IDS)

    def test_the_active_only_flag_does_not_narrow_it(self, rest_api, collections) -> None:
        """The flag the object lists honour would leave the inactive object out - the guard counts it"""
        _, objects = collections
        objects.insert_many([_object_doc(ACTIVE_OBJECT_ID, True), _object_doc(INACTIVE_OBJECT_ID, False)])

        assert _count(rest_api, ACTIVE_ONLY_QUERY).get_json() == len(OBJECT_IDS)

    def test_an_inactive_object_blocks_the_delete_the_count_reports(self, rest_api, collections) -> None:
        """The case the active-only branch got wrong: the pre-check says 1, and the delete is refused"""
        types, objects = collections
        objects.insert_one(_object_doc(INACTIVE_OBJECT_ID, False))

        assert _count(rest_api, ACTIVE_ONLY_QUERY).get_json() == 1
        assert rest_api.delete(f'{ROUTE_URL}/{COUNTED_TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST
        assert types.find_one({'public_id': COUNTED_TYPE_ID}) is not None


class TestACallerTheTypeAclHidesItFromIsRefused:
    """A Type the caller's group may not READ is refused by id, its count included."""

    def test_a_caller_who_may_not_read_the_type_is_refused(self, rest_api, collections) -> None:
        """A 403 - neither the total nor a 0 the guard would contradict"""
        _, objects = collections
        objects.insert_many([_object_doc(ACTIVE_OBJECT_ID, True), _object_doc(INACTIVE_OBJECT_ID, False)])

        response = _count(rest_api, user=_viewer())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert str(COUNTED_TYPE_ID) in response.get_json()['message']

    def test_the_same_caller_reads_none_of_them(self, rest_api, collections) -> None:
        """The control: the Type's ACL really does deny the viewer its objects"""
        _, objects = collections
        objects.insert_one(_object_doc(ACTIVE_OBJECT_ID, True))

        response = rest_api.get(f'/objects/{ACTIVE_OBJECT_ID}', user=_viewer())

        assert response.status_code == HTTPStatus.FORBIDDEN
