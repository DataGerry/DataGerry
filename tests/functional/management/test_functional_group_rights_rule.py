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
Functional tests for the ``rights`` rule of a CmdbUserGroup write, and for the repair of a stored bad group

Both write routes (``POST /groups/``, ``PUT /groups/<id>``) accept only right names the right tree knows: an entry
that is not a string fails the schema, an unknown name is refused with one message naming it, and nothing is
written either way. Both routes store the same form - each name once, in tree order.

A group stored before the rule with an unhashable entry cannot be read or deleted, and every member is refused
every request with a 500; after ``updater_20261002`` all of it works again. A PUT is not locked out: the update
checks only that the id exists, so a valid payload overwrites the bad entry and repairs the group by itself
"""
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261002 import Update20261002
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_UNKNOWN_RIGHTS_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/groups'

CREATE_NAME: str = 'rights-rule-create'
UPDATE_GROUP_ID: int = 96901
BROKEN_GROUP_ID: int = 96902
MEMBER_USER_ID: int = 96903
ALL_GROUP_IDS: list[int] = [UPDATE_GROUP_ID, BROKEN_GROUP_ID]

KNOWN_RIGHT: str = 'base.framework.object.view'
GROUP_VIEW_RIGHT: str = 'base.user-management.group.view'
WILDCARD_RIGHT: str = 'base.framework.type.*'
UNKNOWN_RIGHT: str = 'base.no-such-right'
OTHER_UNKNOWN_RIGHT: str = 'base.framework.no-such-right'

NOT_STRING_ENTRIES: list[Any] = [{}, 1, None, [KNOWN_RIGHT]]


def _payload(name: str, rights: list[Any]) -> dict[str, Any]:
    """A group payload with the given rights"""
    return {'name': name, 'label': name, 'rights': rights}


def _unknown_message(*names: str) -> str:
    """The refusal both routes answer for the given unknown names"""
    return GROUP_UNKNOWN_RIGHTS_MSG.format(names=', '.join(f"'{name}'" for name in names))


def _tree_order(names: list[str]) -> list[str]:
    """The given names, each once, in the order of the right tree - the stored form"""
    wanted: set[str] = set(names)

    return [right.name for right in flat_rights_tree(ALL_RIGHTS) if right.name in wanted]


@pytest.fixture(name='groups')
def fixture_groups(database_manager: MongoDatabaseManager, database_name: str):
    """The groups collection, with one group to update seeded and every test group removed afterwards"""
    collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    collection.delete_many({'$or': [{'public_id': {'$in': ALL_GROUP_IDS}}, {'name': CREATE_NAME}]})
    collection.insert_one({'public_id': UPDATE_GROUP_ID, **_payload(f'group-{UPDATE_GROUP_ID}', [KNOWN_RIGHT])})

    yield collection

    collection.delete_many({'$or': [{'public_id': {'$in': ALL_GROUP_IDS}}, {'name': CREATE_NAME}]})


def _put(rest_api, rights: list[Any]):
    """PUT the seeded group with the given rights"""
    return rest_api.put(f'{ROUTE_URL}/{UPDATE_GROUP_ID}', json=_payload(f'group-{UPDATE_GROUP_ID}', rights))

# ------------------------------------------------------ the rule ---------------------------------------------------- #

class TestNotStringEntries:
    """An entry that is not a string fails the schema on both routes; nothing is written"""

    @pytest.mark.parametrize('entry', NOT_STRING_ENTRIES)
    def test_create_refuses_and_stores_nothing(self, rest_api, groups, entry: Any) -> None:
        """POST answers 400 and no group of that name exists"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(CREATE_NAME, [KNOWN_RIGHT, entry]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert groups.count_documents({'name': CREATE_NAME}) == 0

    @pytest.mark.parametrize('entry', NOT_STRING_ENTRIES)
    def test_update_refuses_and_leaves_the_stored_rights(self, rest_api, groups, entry: Any) -> None:
        """PUT answers 400 and the stored rights are unchanged"""
        response = _put(rest_api, [entry])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert groups.find_one({'public_id': UPDATE_GROUP_ID})['rights'] == [KNOWN_RIGHT]


class TestUnknownNames:
    """A name the right tree does not know is refused on both routes with the same message"""

    def test_create_refuses_naming_each_unknown_once(self, rest_api, groups) -> None:
        """Every unknown name is listed once, in the order sent; nothing is stored"""
        rights: list[str] = [UNKNOWN_RIGHT, KNOWN_RIGHT, OTHER_UNKNOWN_RIGHT, UNKNOWN_RIGHT]

        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(CREATE_NAME, rights))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _unknown_message(UNKNOWN_RIGHT, OTHER_UNKNOWN_RIGHT)
        assert groups.count_documents({'name': CREATE_NAME}) == 0

    def test_update_refuses_with_the_create_message(self, rest_api, groups) -> None:
        """PUT used to drop the name silently; now it answers the create's 400 and stores nothing"""
        response = _put(rest_api, [KNOWN_RIGHT, UNKNOWN_RIGHT])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _unknown_message(UNKNOWN_RIGHT)
        assert groups.find_one({'public_id': UPDATE_GROUP_ID})['rights'] == [KNOWN_RIGHT]

    def test_a_wildcard_right_is_a_known_name(self, rest_api, groups) -> None:
        """A wildcard node of the tree is accepted and stored"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(CREATE_NAME, [WILDCARD_RIGHT]))

        assert response.status_code == HTTPStatus.CREATED
        assert groups.find_one({'name': CREATE_NAME})['rights'] == [WILDCARD_RIGHT]


class TestOneStoredForm:
    """Create and update store the same list for the same input"""

    SUBMITTED: list[str] = [GROUP_VIEW_RIGHT, KNOWN_RIGHT, WILDCARD_RIGHT, KNOWN_RIGHT]

    def test_create_stores_each_name_once_in_tree_order(self, rest_api, groups) -> None:
        """Duplicates go and the order is the tree's"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_payload(CREATE_NAME, self.SUBMITTED))

        assert response.status_code == HTTPStatus.CREATED
        stored: dict[str, Any] = groups.find_one({'name': CREATE_NAME})
        assert stored['rights'] == _tree_order(self.SUBMITTED)
        assert stored['public_id'] == response.get_json()['result_id']

    def test_update_stores_the_same_list(self, rest_api, groups) -> None:
        """The update's stored form is the create's"""
        assert _put(rest_api, self.SUBMITTED).status_code == HTTPStatus.ACCEPTED
        assert groups.find_one({'public_id': UPDATE_GROUP_ID})['rights'] == _tree_order(self.SUBMITTED)

# ----------------------------------------------- a stored bad group ------------------------------------------------- #

class TestRepairOfAStoredBadGroup:
    """A group stored with an unhashable entry is locked until the migration repairs it"""

    @pytest.fixture(name='member')
    def fixture_member(self, groups, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the broken group with one member, removing both afterwards"""
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        users.delete_many({'public_id': MEMBER_USER_ID})
        groups.insert_one({'public_id': BROKEN_GROUP_ID,
                           **_payload(f'group-{BROKEN_GROUP_ID}', [{}, GROUP_VIEW_RIGHT])})
        users.insert_one({'public_id': MEMBER_USER_ID, 'user_name': f'user-{MEMBER_USER_ID}', 'active': True,
                          'group_id': BROKEN_GROUP_ID, 'password': 'hashed-stub'})

        yield SimpleNamespace(public_id=MEMBER_USER_ID)

        users.delete_many({'public_id': MEMBER_USER_ID})

    def test_locked_before_the_repair(self, rest_api, member) -> None:
        """GET and DELETE answer 400, and the member's own request a 500"""
        assert rest_api.get(f'{ROUTE_URL}/{BROKEN_GROUP_ID}').status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.delete(f'{ROUTE_URL}/{BROKEN_GROUP_ID}').status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(
            f'{ROUTE_URL}/{BROKEN_GROUP_ID}', user=member,
        ).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_put_repairs_it_without_the_migration(self, rest_api, member, groups) -> None:
        """The update reads only the id, so a valid payload overwrites the bad entry and the group reads again"""
        response = rest_api.put(
            f'{ROUTE_URL}/{BROKEN_GROUP_ID}', json=_payload(f'group-{BROKEN_GROUP_ID}', [KNOWN_RIGHT]),
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        assert groups.find_one({'public_id': BROKEN_GROUP_ID})['rights'] == [KNOWN_RIGHT]
        read = rest_api.get(f'{ROUTE_URL}/{BROKEN_GROUP_ID}')
        assert read.status_code == HTTPStatus.OK
        assert read.get_json()['result']['rights'] == response.get_json()['result']['rights']

    def test_usable_after_the_repair(
        self, rest_api, member, groups, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The member is served by the right the group kept, and the group can be edited and deleted again"""
        updater = Update20261002(database_manager, database_name)
        updater.increase_updater_version = lambda _version: None  # the session's updater version stays as it is
        updater.start_update()

        member_read = rest_api.get(f'{ROUTE_URL}/{BROKEN_GROUP_ID}', user=member)
        assert member_read.status_code == HTTPStatus.OK
        assert [right['name'] for right in member_read.get_json()['result']['rights']] == [GROUP_VIEW_RIGHT]

        assert rest_api.put(
            f'{ROUTE_URL}/{BROKEN_GROUP_ID}', json=_payload(f'group-{BROKEN_GROUP_ID}', [KNOWN_RIGHT]),
        ).status_code == HTTPStatus.ACCEPTED

        database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_many({'public_id': MEMBER_USER_ID})
        assert rest_api.delete(f'{ROUTE_URL}/{BROKEN_GROUP_ID}').status_code == HTTPStatus.ACCEPTED
        assert groups.count_documents({'public_id': BROKEN_GROUP_ID}) == 0
