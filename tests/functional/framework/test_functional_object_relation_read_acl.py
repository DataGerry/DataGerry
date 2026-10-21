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
Functional tests for the object-relation read rule: every read asks for ``base.framework.objectRelation.view``, and
a CmdbObjectRelation is as readable as the less readable of its two objects

Seeded with ``tests/utils/location_acl_seed`` (a VISIBLE type, a PLAIN one, and a HIDDEN one only the admin group
may read) and four relations: VISIBLE->PLAIN (readable), VISIBLE->HIDDEN and HIDDEN->VISIBLE (a hidden counterpart)
and HIDDEN->PLAIN. The seed's editor group is the reader; it is given the view right except where a test pins the
refusal. Pinned, for that reader:

  - without the right, both relation-tab routes are a 403 naming it
  - the tabs of an object it may not read are a 403, of a missing object a 404
  - a relation with a hidden object is left out of the tab rows, ``total`` and the tab's count - a tab made only
    of such relations is no tab at all
  - the list leaves those relations out of its rows and its total, also when ``?filter=`` names one; a single read
    of one is a 403
  - a failed object read or a failed type-ACL read is a 400; an unsortable ``?sort=`` is a 400
  - the admin reads everything as before, and the default ``user`` group reaches the tabs
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.relation_routes import relations_helper
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_TABS_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_TABS_OBJECT_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_TABS_OBJECT_NOT_FOUND_MESSAGE,
    ObjectRelationRight,
)
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

LIST_URL: str = '/object_relations/'
TABS_URL: str = '/object_relations/tabs/{object_id}'
INSTANCES_URL: str = '/object_relations/tabs/{object_id}/instances'

# What `APIBlueprint.protect` answers a user whose group lacks the route's right
RIGHT_REFUSAL: str = 'User has not the required right {right}'

RELATION_ID: int = 89651
READABLE_ID: int = 89661          # VISIBLE -> PLAIN
HIDDEN_CHILD_ID: int = 89662      # VISIBLE -> HIDDEN
HIDDEN_PARENT_ID: int = 89663     # HIDDEN -> VISIBLE
HIDDEN_ONLY_ID: int = 89664       # HIDDEN -> PLAIN
ALL_RELATION_IDS: list[int] = [READABLE_ID, HIDDEN_CHILD_ID, HIDDEN_PARENT_ID, HIDDEN_ONLY_ID]
HIDDEN_RELATION_IDS: list[int] = [HIDDEN_CHILD_ID, HIDDEN_PARENT_ID, HIDDEN_ONLY_ID]

DEFAULT_USER_ID: int = 89671
DEFAULT_USER_NAME: str = 'relation-read-default-user'
HIDDEN_FIELD_VALUE: str = 'hidden-relation-value'

PARENT: str = 'parent'
CHILD: str = 'child'


def _relation(public_id: int, parent: tuple[int, int], child: tuple[int, int]) -> dict[str, Any]:
    """A stored object relation between two (object id, type id) ends; a hidden one carries a value to look for"""
    value: str = HIDDEN_FIELD_VALUE if seed.HIDDEN_TYPE_ID in (parent[1], child[1]) else 'readable'

    return {
        'public_id': public_id, 'relation_id': RELATION_ID,
        'relation_parent_id': parent[0], 'relation_parent_type_id': parent[1],
        'relation_child_id': child[0], 'relation_child_type_id': child[1],
        'field_values': [{'name': 'port', 'value': value}],
    }


@pytest.fixture(name='relations', autouse=True)
def fixture_relations(database_manager: MongoDatabaseManager, database_name: str):
    """The ACL seed, its editor given the view right, the relation definition and the four relations"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$push': {'rights': ObjectRelationRight.VIEW.value}},
    )
    definitions = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        definitions.delete_many({'public_id': RELATION_ID})
        object_relations.delete_many({'public_id': {'$in': ALL_RELATION_IDS}})
        users.delete_many({'public_id': DEFAULT_USER_ID})

    _purge()
    definitions.insert_one({
        'public_id': RELATION_ID,
        'relation_name_parent': 'Hosts', 'relation_name_child': 'Hosted On',
        'relation_icon_parent': 'fas fa-server', 'relation_icon_child': 'fas fa-network-wired',
        'relation_color_parent': '#111111', 'relation_color_child': '#222222',
    })
    visible = (seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID)
    hidden = (seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID)
    plain = (seed.PLAIN_ID, seed.PLAIN_TYPE_ID)
    object_relations.insert_many([
        _relation(READABLE_ID, visible, plain),
        _relation(HIDDEN_CHILD_ID, visible, hidden),
        _relation(HIDDEN_PARENT_ID, hidden, visible),
        _relation(HIDDEN_ONLY_ID, hidden, plain),
    ])
    users.insert_one({
        'public_id': DEFAULT_USER_ID, 'user_name': DEFAULT_USER_NAME, 'active': True, 'group_id': USER_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
    })
    yield object_relations
    _purge()
    seed.purge(database_manager, database_name)


def _reader() -> dict[str, Any]:
    """The request kwargs that send it as the reader"""
    return {'user': seed.location_editor()}


def _tabs(rest_api, object_id: int, **kwargs: Any) -> Any:
    """GET the tabs of an object"""
    return rest_api.get(TABS_URL.format(object_id=object_id), **kwargs)


def _instances(rest_api, object_id: int, role: str, **kwargs: Any) -> Any:
    """GET the first page of one tab of an object"""
    query: dict[str, Any] = {'relation_id': RELATION_ID, 'role': role, **kwargs.pop('query', {})}

    return rest_api.get(INSTANCES_URL.format(object_id=object_id), query_string=query, **kwargs)


def _counts(response: Any) -> dict[str, int]:
    """role -> count of the seeded relation's tabs"""
    assert response.status_code == HTTPStatus.OK

    return {tab['role']: tab['count'] for tab in response.get_json()['results'] if tab['relation_id'] == RELATION_ID}


def _row_ids(response: Any) -> list[int]:
    """The relation ids a tab page answered"""
    assert response.status_code == HTTPStatus.OK

    return [row['public_id'] for row in response.get_json()['results']]


def _listed_ids(response: Any) -> set[int]:
    """The seeded relation ids a list answered"""
    assert response.status_code == HTTPStatus.OK

    return {relation['public_id'] for relation in response.get_json()['results']} & set(ALL_RELATION_IDS)


def _drop_view_right(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Takes the view right back from the reader's group"""
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID}, {'$pull': {'rights': ObjectRelationRight.VIEW.value}},
    )


class TestTheRight:
    """Both relation-tab routes ask for the view right"""

    @pytest.mark.parametrize('call', [
        lambda api: _tabs(api, seed.VISIBLE_ID, **_reader()),
        lambda api: _instances(api, seed.VISIBLE_ID, PARENT, **_reader()),
    ], ids=['tabs', 'instances'])
    def test_without_it_the_route_is_a_403_naming_it(self, rest_api, database_manager, database_name,
                                                     call: Any) -> None:
        """Before anything is read"""
        _drop_view_right(database_manager, database_name)

        response = call(rest_api)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=ObjectRelationRight.VIEW.value)

    def test_the_default_group_reaches_the_tabs(self, rest_api) -> None:
        """Seeded with the right, it reads the tabs of what it may read"""
        default_user = CmdbUser(public_id=DEFAULT_USER_ID, user_name=DEFAULT_USER_NAME, active=True,
                                group_id=USER_GROUP_ID)

        assert _counts(_tabs(rest_api, seed.VISIBLE_ID, user=default_user)) == {PARENT: 1}


class TestTheBaseObject:
    """The tabs of an object are as readable as the object"""

    @pytest.mark.parametrize('call', [
        lambda api: _tabs(api, seed.HIDDEN_ID, **_reader()),
        lambda api: _instances(api, seed.HIDDEN_ID, PARENT, **_reader()),
    ], ids=['tabs', 'instances'])
    def test_an_object_the_reader_may_not_read_is_a_403(self, rest_api, call: Any) -> None:
        """Like GET /objects/<id> - and nothing of its relations is in the body"""
        response = call(rest_api)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_TABS_ACCESS_DENIED_MESSAGE.format(
            object_id=seed.HIDDEN_ID)
        assert HIDDEN_FIELD_VALUE not in response.get_data(as_text=True)

    @pytest.mark.parametrize('call', [
        lambda api: _tabs(api, seed.MISSING_OBJECT_ID, **_reader()),
        lambda api: _instances(api, seed.MISSING_OBJECT_ID, PARENT, **_reader()),
    ], ids=['tabs', 'instances'])
    def test_a_missing_object_is_a_404(self, rest_api, call: Any) -> None:
        """Deleting an object deletes its relations - there are no tabs to answer"""
        response = call(rest_api)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == OBJECT_RELATION_TABS_OBJECT_NOT_FOUND_MESSAGE.format(
            object_id=seed.MISSING_OBJECT_ID)

    def test_a_failed_object_read_is_a_400(self, rest_api, monkeypatch) -> None:
        """The read is part of the decision - its failure is named, not a 500"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise ObjectsManagerGetError('down')

        monkeypatch.setattr(ObjectsManager, 'get_object', _fail)

        response = _tabs(rest_api, seed.VISIBLE_ID, **_reader())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_TABS_OBJECT_LOOKUP_FAILED_MESSAGE.format(
            object_id=seed.VISIBLE_ID)


class TestTheTabsOfAReadableObject:
    """A relation with a hidden counterpart is neither shown nor counted"""

    def test_the_counts_leave_hidden_counterparts_out(self, rest_api) -> None:
        """Parent tab: 1 of 2; the child tab holds only a hidden counterpart, so it is no tab"""
        assert _counts(_tabs(rest_api, seed.VISIBLE_ID, **_reader())) == {PARENT: 1}

    def test_the_parent_tab_answers_only_the_readable_row(self, rest_api) -> None:
        """Rows and total agree with the count"""
        response = _instances(rest_api, seed.VISIBLE_ID, PARENT, **_reader())

        assert _row_ids(response) == [READABLE_ID]
        assert response.get_json()['total'] == 1
        assert response.get_json()['results'][0]['counterpart']['object_id'] == seed.PLAIN_ID
        assert HIDDEN_FIELD_VALUE not in response.get_data(as_text=True)

    def test_the_child_tab_answers_nothing(self, rest_api) -> None:
        """Its one relation has a hidden counterpart"""
        response = _instances(rest_api, seed.VISIBLE_ID, CHILD, **_reader())

        assert (_row_ids(response), response.get_json()['total']) == ([], 0)

    def test_an_unsortable_key_is_a_400(self, rest_api) -> None:
        """Only public_id sorts a tab"""
        response = _instances(rest_api, seed.VISIBLE_ID, PARENT, query={'sort': 'relation_id'}, **_reader())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('call', [
        lambda api: _tabs(api, seed.VISIBLE_ID, **_reader()),
        lambda api: _instances(api, seed.VISIBLE_ID, PARENT, **_reader()),
        lambda api: api.get(LIST_URL, **_reader()),
        lambda api: api.get(f'/object_relations/{READABLE_ID}', **_reader()),
    ], ids=['tabs', 'instances', 'list', 'single'])
    def test_a_failed_type_acl_read_is_a_400(self, rest_api, monkeypatch, call: Any) -> None:
        """Never read as 'nothing denied'"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise BaseManagerGetError('down')

        monkeypatch.setattr(relations_helper, 'resolve_denied_type_ids', _fail)

        response = call(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE


class TestTheListAndTheSingleRead:
    """GET /object_relations/ and /object_relations/<id>"""

    def test_the_list_answers_only_readable_relations(self, rest_api) -> None:
        """And its total follows the rows"""
        reader = rest_api.get(LIST_URL, query_string={'limit': 0}, **_reader())
        admin = rest_api.get(LIST_URL, query_string={'limit': 0})

        assert _listed_ids(reader) == {READABLE_ID}
        assert _listed_ids(admin) == set(ALL_RELATION_IDS)
        assert admin.get_json()['total'] - reader.get_json()['total'] == len(HIDDEN_RELATION_IDS)

    @pytest.mark.parametrize('relation_id', HIDDEN_RELATION_IDS)
    def test_a_filter_naming_a_hidden_relation_finds_nothing(self, rest_api, relation_id: int) -> None:
        """The rule runs ahead of the caller's filter"""
        response = rest_api.get(LIST_URL, query_string={'filter': json.dumps({'public_id': relation_id})},
                                **_reader())

        assert (_listed_ids(response), response.get_json()['total']) == (set(), 0)

    def test_a_readable_relation_is_read(self, rest_api) -> None:
        """Unchanged"""
        response = rest_api.get(f'/object_relations/{READABLE_ID}', **_reader())

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == READABLE_ID

    @pytest.mark.parametrize('relation_id', HIDDEN_RELATION_IDS)
    def test_a_relation_with_a_hidden_object_is_a_403(self, rest_api, relation_id: int) -> None:
        """Naming the relation, and nothing of it in the body"""
        response = rest_api.get(f'/object_relations/{relation_id}', **_reader())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(public_id=relation_id)
        assert HIDDEN_FIELD_VALUE not in response.get_data(as_text=True)


class TestTheAdmin:
    """Denied nothing - reads as before"""

    def test_the_tabs_count_every_relation(self, rest_api) -> None:
        """2 as parent, 1 as child"""
        assert _counts(_tabs(rest_api, seed.VISIBLE_ID)) == {PARENT: 2, CHILD: 1}

    def test_the_tabs_of_the_hidden_object_answer(self, rest_api) -> None:
        """Two as parent, one as child"""
        assert _counts(_tabs(rest_api, seed.HIDDEN_ID)) == {PARENT: 2, CHILD: 1}

    @pytest.mark.parametrize('relation_id', ALL_RELATION_IDS)
    def test_every_relation_is_read(self, rest_api, relation_id: int) -> None:
        """No 403"""
        assert rest_api.get(f'/object_relations/{relation_id}').status_code == HTTPStatus.OK
