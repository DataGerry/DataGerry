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
Functional tests: a stored type ACL carrying a key that is no user group id, through the real REST app

Such a key fails no read: the Type and its object are read by id (200) through the group keys beside it, and a Type
whose activated ACL names only such a key grants nobody (403) - the reading the type listing already had
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.type_access_seed import SeededAccess, remove_type_access, store_type_access
# -------------------------------------------------------------------------------------------------------------------- #

GRANTED_TYPE_ID: int = 89761
NOBODY_TYPE_ID: int = 89762
TYPE_IDS: list[int] = [GRANTED_TYPE_ID, NOBODY_TYPE_ID]
OBJECT_ID: int = 89771
NO_GROUP_KEY: str = 'admin'
READ: str = AccessControlPermission.READ.value


def _type_doc(public_id: int, includes: dict[str, list[str]]) -> dict[str, Any]:
    """A Type whose activated ACL holds the given entries"""
    return {
        'public_id': public_id, 'name': f'drifted-key-{public_id}', 'label': f'Type {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [], 'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'externals': [], 'sections': []},
        'acl': {'activated': True, 'groups': {'includes': includes}},
    }


@pytest.fixture(autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """
    A Type granting the administrators beside a drifted key, one naming only the drifted key (both also as the access
    rules they translate to), an object
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_many([
        _type_doc(GRANTED_TYPE_ID, {NO_GROUP_KEY: [READ], str(ADMIN_GROUP_ID): [READ]}),
        _type_doc(NOBODY_TYPE_ID, {NO_GROUP_KEY: [READ]}),
    ])
    objects.insert_one({'public_id': OBJECT_ID, 'type_id': GRANTED_TYPE_ID, 'active': True, 'author_id': 1,
                        'version': '1.0.0', 'creation_time': datetime.now(timezone.utc), 'fields': []})

    access: SeededAccess = store_type_access(database_manager.connector.client[database_name], TYPE_IDS)

    yield

    remove_type_access(database_manager.connector.client[database_name], access)
    types.delete_many({'public_id': {'$in': TYPE_IDS}})
    objects.delete_many({'public_id': OBJECT_ID})


def test_the_type_is_read_through_the_group_key_beside_it(rest_api) -> None:
    """200 - the drifted key no longer fails the read"""
    assert rest_api.get(f'/types/{GRANTED_TYPE_ID}').status_code == HTTPStatus.OK


def test_its_object_is_read(rest_api) -> None:
    """200 - the object's Type loads"""
    assert rest_api.get(f'/objects/{OBJECT_ID}').status_code == HTTPStatus.OK


def test_a_type_naming_only_the_drifted_key_grants_nobody(rest_api) -> None:
    """403 - administrators are not exempt"""
    assert rest_api.get(f'/types/{NOBODY_TYPE_ID}').status_code == HTTPStatus.FORBIDDEN
