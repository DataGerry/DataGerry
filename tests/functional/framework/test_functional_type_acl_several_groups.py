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
Functional tests: the type ACL of a user in several user groups, through the real REST app

The caller is in two groups: the RIGHTS group holds the type and object view rights and no ACL entry, the READER
group holds no right and the ACL entry granting READ. Neither alone can read the Type; together they can - the rights
are the union of the groups, and so is the type ACL. A Type whose ACL lists neither group stays hidden
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.type_access_seed import SeededAccess, remove_type_access, store_type_access
# -------------------------------------------------------------------------------------------------------------------- #

RIGHTS_GROUP_ID: int = 89701
READER_GROUP_ID: int = 89702
GROUP_IDS: list[int] = [RIGHTS_GROUP_ID, READER_GROUP_ID]
CALLER_ID: int = 89711
CALLER_NAME: str = 'several-groups-caller'

READABLE_TYPE_ID: int = 89721
HIDDEN_TYPE_ID: int = 89722
TYPE_IDS: list[int] = [READABLE_TYPE_ID, HIDDEN_TYPE_ID]
READABLE_OBJECT_ID: int = 89731
TYPE_FILTER_KEY: str = 'filter'
LIST_LIMIT_KEY: str = 'limit'
NO_LIMIT: int = 0


def _type_doc(public_id: int, reader_group_id: int) -> dict[str, Any]:
    """A Type whose activated ACL grants READ to one group only"""
    return {
        'public_id': public_id, 'name': f'several-groups-{public_id}', 'label': f'Type {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [], 'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'externals': [], 'sections': []},
        'acl': {'activated': True,
                'groups': {'includes': {str(reader_group_id): [AccessControlPermission.READ.value]}}},
    }


def _caller(group_ids: list[int]) -> CmdbUser:
    """The caller, in the given groups"""
    return CmdbUser(public_id=CALLER_ID, user_name=CALLER_NAME, active=True, group_ids=group_ids)


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """
    The two groups, the caller in both, the two Types (with the access rules their ACLs translate to) and an object of
    the readable one - removed afterwards
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': READABLE_OBJECT_ID})
        groups.delete_many({'public_id': {'$in': GROUP_IDS}})
        users.delete_many({'public_id': CALLER_ID})

    _purge()
    types.insert_many([_type_doc(READABLE_TYPE_ID, READER_GROUP_ID), _type_doc(HIDDEN_TYPE_ID, ADMIN_GROUP_ID)])
    objects.insert_one({'public_id': READABLE_OBJECT_ID, 'type_id': READABLE_TYPE_ID, 'active': True, 'author_id': 1,
                        'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'fields': []})
    groups.insert_many([
        {'public_id': RIGHTS_GROUP_ID, 'name': 'several-groups-rights', 'label': 'Rights',
         'rights': [TypeRight.VIEW.value, ObjectRightName.VIEW.value]},
        {'public_id': READER_GROUP_ID, 'name': 'several-groups-reader', 'label': 'Reader', 'rights': []},
    ])
    users.insert_one({'public_id': CALLER_ID, 'user_name': CALLER_NAME, 'active': True, 'group_ids': GROUP_IDS,
                      'registration_time': datetime.now(timezone.utc)})
    access: SeededAccess = store_type_access(database_manager.connector.client[database_name], TYPE_IDS)
    yield users
    remove_type_access(database_manager.connector.client[database_name], access)
    _purge()


def _listed_type_ids(rest_api: Any) -> set[int]:
    """The seeded Types the caller's type listing holds"""
    response: Any = rest_api.get('/types/', user=_caller(GROUP_IDS), query_string={
        TYPE_FILTER_KEY: f'{{"public_id": {{"$in": {TYPE_IDS}}}}}', LIST_LIMIT_KEY: NO_LIMIT,
    })
    assert response.status_code == HTTPStatus.OK

    return {entry['public_id'] for entry in response.get_json()['results']}


@pytest.mark.usefixtures('seeded')
class TestTheGroupsCombine:
    """The right from one group and the ACL entry from the other"""

    def test_the_type_is_read_by_id(self, rest_api) -> None:
        """200 - the reader group's ACL entry, with the rights group's view right"""
        assert rest_api.get(f'/types/{READABLE_TYPE_ID}', user=_caller(GROUP_IDS)).status_code == HTTPStatus.OK

    def test_a_type_neither_group_is_listed_for_stays_refused(self, rest_api) -> None:
        """403 - no group's entry grants it"""
        assert rest_api.get(f'/types/{HIDDEN_TYPE_ID}', user=_caller(GROUP_IDS)).status_code == HTTPStatus.FORBIDDEN

    def test_the_listing_holds_the_readable_type_only(self, rest_api) -> None:
        """The listing and the read by id agree"""
        assert _listed_type_ids(rest_api) == {READABLE_TYPE_ID}

    def test_an_object_of_the_type_is_read(self, rest_api) -> None:
        """The object read takes the same union"""
        assert rest_api.get(f'/objects/{READABLE_OBJECT_ID}', user=_caller(GROUP_IDS)).status_code == HTTPStatus.OK


class TestOneGroupAloneIsNotEnough:
    """The controls: each group alone fails on its own missing half"""

    def test_without_the_reader_group_the_acl_refuses(self, rest_api, seeded) -> None:
        """The rights group alone: the view right, but no ACL entry - 403"""
        seeded.update_one({'public_id': CALLER_ID}, {'$set': {'group_ids': [RIGHTS_GROUP_ID]}})

        assert rest_api.get(f'/types/{READABLE_TYPE_ID}', user=_caller([RIGHTS_GROUP_ID])).status_code == \
            HTTPStatus.FORBIDDEN

    def test_without_the_rights_group_the_right_refuses(self, rest_api, seeded) -> None:
        """The reader group alone: the ACL entry, but no view right - 403"""
        seeded.update_one({'public_id': CALLER_ID}, {'$set': {'group_ids': [READER_GROUP_ID]}})

        assert rest_api.get(f'/types/{READABLE_TYPE_ID}', user=_caller([READER_GROUP_ID])).status_code == \
            HTTPStatus.FORBIDDEN
