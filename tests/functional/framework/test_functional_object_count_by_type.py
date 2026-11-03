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
Functional tests: `GET /objects/count/<type_id>`, `GET /objects/count` and the dashboard chart
`GET /objects/group/type_id`

The per-type count is a route on one Type, so it follows the Type's READ rule like `GET /types/count_objects/<id>`: a
caller whose group the Type's ACL denies READ is refused (403) and learns no number; a missing Type has no objects
(0); a readable Type's count is its total, narrowed to active objects when the active-only cookie asks for it. Both
count routes answer a failed read 400 and an unexpected error 500 through `handle_route_errors`.

The chart counts per type in one aggregation: a viewer gets no group for a type it may not READ, an object whose
type is gone no longer fails the chart (its group is left out), and every group is `{_id, count, label, type_color}`
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

import cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes as objects_routes
from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

#: Readable by every group (ACL off) and readable by the admin group only
OPEN_TYPE_ID: int = 86101
GUARDED_TYPE_ID: int = 86102
#: A Type id nothing carries
MISSING_TYPE_ID: int = 86109
#: The Type id of an object whose Type is gone
ORPHAN_TYPE_ID: int = 86108

OPEN_ACTIVE_ID: int = 86111
OPEN_INACTIVE_ID: int = 86112
GUARDED_OBJECT_ID: int = 86113
#: An object of ORPHAN_TYPE_ID - its type is gone
ORPHAN_OBJECT_ID: int = 86114
OBJECT_IDS: list[int] = [OPEN_ACTIVE_ID, OPEN_INACTIVE_ID, GUARDED_OBJECT_ID, ORPHAN_OBJECT_ID]

VIEWER_GROUP_ID: int = 86121
VIEWER_ID: int = 86122
VIEWER_NAME: str = 'object-count-viewer'

NAME_FIELD: str = 'name'
ACTIVE_ONLY_QUERY: str = '?onlyActiveObjCookie=true'


def _type_doc(type_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A one-field Type with the given ACL"""
    return {
        'public_id': type_id, 'name': f'object-count-{type_id}', 'label': f'Counted {type_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube', 'summary': {'fields': [NAME_FIELD]}, 'externals': [],
            'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
        },
        'acl': acl,
    }


def _object_doc(public_id: int, type_id: int, active: bool) -> dict[str, Any]:
    """An object of a Type"""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': active, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': f'object-{public_id}'}],
    }


def _viewer() -> CmdbUser:
    """A member of a group holding the object view right alone - the guarded Type's ACL grants it nothing"""
    return CmdbUser(public_id=VIEWER_ID, user_name=VIEWER_NAME, active=True, group_id=VIEWER_GROUP_ID)


def _count(rest_api, type_id: int, query: str = '', **user: Any) -> Any:
    """GET the per-type count"""
    return rest_api.get(f'{ROUTE_URL}/count/{type_id}{query}', **user)


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Both Types with their objects, the viewer group and user; everything removed afterwards"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [OPEN_TYPE_ID, GUARDED_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        groups.delete_many({'public_id': VIEWER_GROUP_ID})
        users.delete_many({'public_id': VIEWER_ID})

    _purge()
    types.insert_many([
        _type_doc(OPEN_TYPE_ID, {'activated': False, 'groups': {'includes': None}}),
        _type_doc(GUARDED_TYPE_ID, {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}),
    ])
    objects.insert_many([
        _object_doc(OPEN_ACTIVE_ID, OPEN_TYPE_ID, True),
        _object_doc(OPEN_INACTIVE_ID, OPEN_TYPE_ID, False),
        _object_doc(GUARDED_OBJECT_ID, GUARDED_TYPE_ID, True),
        _object_doc(ORPHAN_OBJECT_ID, ORPHAN_TYPE_ID, True),
    ])
    groups.insert_one({'public_id': VIEWER_GROUP_ID, 'name': VIEWER_NAME, 'label': VIEWER_NAME,
                       'rights': [ObjectRightName.VIEW.value]})
    users.insert_one({'public_id': VIEWER_ID, 'user_name': VIEWER_NAME, 'active': True, 'group_id': VIEWER_GROUP_ID,
                      'registration_time': datetime.now(timezone.utc)})
    yield
    _purge()


class TestTheTypesReadRule:
    """The count of one Type is as readable as the Type"""

    def test_a_type_the_caller_may_not_read_is_a_403(self, rest_api) -> None:
        """The viewer learns no number - the body is the refusal, not a count"""
        response = _count(rest_api, GUARDED_TYPE_ID, user=_viewer())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert str(GUARDED_TYPE_ID) in response.get_json()['message']

    def test_a_group_the_acl_grants_gets_the_count(self, rest_api) -> None:
        """The admin group reads the guarded Type"""
        response = _count(rest_api, GUARDED_TYPE_ID)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == 1

    def test_a_type_without_an_acl_is_counted_for_the_viewer(self, rest_api) -> None:
        """The same viewer, an open Type: both objects"""
        response = _count(rest_api, OPEN_TYPE_ID, user=_viewer())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == 2

    def test_a_missing_type_has_no_objects(self, rest_api) -> None:
        """Not a 404 - like the Type-side count"""
        response = _count(rest_api, MISSING_TYPE_ID, user=_viewer())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == 0


class TestTheActiveOnlyCookie:
    """The object view's count, unlike the Type delete's pre-check, honours the cookie"""

    def test_without_the_cookie_every_object_counts(self, rest_api) -> None:
        """One active, one inactive"""
        assert _count(rest_api, OPEN_TYPE_ID).get_json() == 2

    def test_with_the_cookie_only_active_objects_count(self, rest_api) -> None:
        """The inactive one is left out"""
        assert _count(rest_api, OPEN_TYPE_ID, ACTIVE_ONLY_QUERY).get_json() == 1


class TestTheErrorAnswers:
    """Both count routes, through handle_route_errors"""

    def test_a_failed_type_read_is_a_400(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """The per-type route reads the Type first"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise TypesManagerGetError('lost')

        monkeypatch.setattr(TypesManager, 'get_type', _fail)

        assert _count(rest_api, OPEN_TYPE_ID).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('url', [f'{ROUTE_URL}/count', f'{ROUTE_URL}/count/{OPEN_TYPE_ID}'],
                             ids=['tenant', 'per-type'])
    def test_a_failed_count_is_a_400(self, rest_api, monkeypatch: pytest.MonkeyPatch, url: str) -> None:
        """count_objects wraps the database failure as ObjectsManagerGetError"""
        def _fail(*_args: Any, **_kwargs: Any) -> int:
            raise ObjectsManagerGetError('lost')

        monkeypatch.setattr(ObjectsManager, 'count_objects', _fail)

        assert rest_api.get(url).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('url', [f'{ROUTE_URL}/count', f'{ROUTE_URL}/count/{OPEN_TYPE_ID}'],
                             ids=['tenant', 'per-type'])
    def test_a_database_failure_below_the_manager_is_a_400_too(self, rest_api, monkeypatch: pytest.MonkeyPatch,
                                                               url: str) -> None:
        """The raw count's own error is wrapped by count_objects, so it reaches the 400 branch"""
        def _fail(*_args: Any, **_kwargs: Any) -> int:
            raise BaseManagerGetError('lost')

        monkeypatch.setattr(ObjectsManager, 'count_documents', _fail)

        assert rest_api.get(url).status_code == HTTPStatus.BAD_REQUEST


GROUP_URL: str = f'{ROUTE_URL}/group/type_id'
#: Every group the chart answers carries exactly these keys
GROUP_KEYS: set[str] = {'_id', 'count', 'label', 'type_color'}
#: Lifted so the seeded types are always among the answered groups, whatever else the test database holds
UNCAPPED: int = 10_000


def _groups(rest_api, query: str = '', **user: Any) -> dict[int, dict[str, Any]]:
    """The chart's groups by type id"""
    response = rest_api.get(f'{GROUP_URL}{query}', **user)

    assert response.status_code == HTTPStatus.OK

    return {group['_id']: group for group in response.get_json()}


class TestTheDashboardChart:
    """GET /objects/group/type_id against seeded types and objects"""

    @pytest.fixture(autouse=True)
    def _uncapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cap is pinned by its own test"""
        monkeypatch.setattr(objects_routes, 'MAX_DASHBOARD_GROUPS', UNCAPPED)

    def test_an_object_whose_type_is_gone_no_longer_fails_the_chart(self, rest_api) -> None:
        """200, and the orphan's group is left out"""
        groups = _groups(rest_api)

        assert ORPHAN_TYPE_ID not in groups
        assert groups[OPEN_TYPE_ID]['count'] == 2

    def test_a_group_is_its_type_id_count_label_and_colour(self, rest_api) -> None:
        """No object document rides along"""
        groups = _groups(rest_api)

        assert all(set(group) == GROUP_KEYS for group in groups.values())
        assert groups[OPEN_TYPE_ID]['label'] == f'Counted {OPEN_TYPE_ID}'

    def test_a_viewer_gets_no_group_for_a_type_it_may_not_read(self, rest_api) -> None:
        """Left out in the count's pipeline - the open type is still there"""
        groups = _groups(rest_api, user=_viewer())

        assert GUARDED_TYPE_ID not in groups
        assert OPEN_TYPE_ID in groups

    def test_the_admin_group_gets_the_guarded_type(self, rest_api) -> None:
        """The ACL grants it READ"""
        assert _groups(rest_api)[GUARDED_TYPE_ID]['count'] == 1

    def test_the_active_only_cookie_narrows_the_counts(self, rest_api) -> None:
        """The inactive object of the open type is left out"""
        assert _groups(rest_api, ACTIVE_ONLY_QUERY)[OPEN_TYPE_ID]['count'] == 1


def test_the_chart_is_capped_and_largest_first(rest_api) -> None:
    """At most MAX_DASHBOARD_GROUPS groups, by count descending"""
    response = rest_api.get(GROUP_URL)
    counts = [group['count'] for group in response.get_json()]

    assert len(counts) <= objects_routes.MAX_DASHBOARD_GROUPS
    assert counts == sorted(counts, reverse=True)

