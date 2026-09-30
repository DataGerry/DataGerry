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
Integration tests for `route_utils.user_has_right` against real stored groups

`APIBlueprint.protect` hands the request user in, and the check reads only that user's group. Against
MongoDB and the real right tree this shows what the unit tests cannot: a stored right name resolves
to a right the group holds, a wildcard right of a parent segment grants its children, a group
without either refuses, and a user whose group was deleted holds no right at all
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import user_has_right
# -------------------------------------------------------------------------------------------------------------------- #

DIRECT_GROUP_ID: int = 93940
WILDCARD_GROUP_ID: int = 93941
EMPTY_GROUP_ID: int = 93942
MISSING_GROUP_ID: int = 93943
GROUP_IDS: list[int] = [DIRECT_GROUP_ID, WILDCARD_GROUP_ID, EMPTY_GROUP_ID, MISSING_GROUP_ID]

RIGHT: str = 'base.framework.object.view'
OTHER_RIGHT: str = 'base.framework.type.view'
PARENT_WILDCARD: str = 'base.framework.object.*'


@pytest.fixture(autouse=True)
def _groups(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores three groups (the right itself, its parent wildcard, nothing); runs in the app context."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    groups.delete_many({'public_id': {'$in': GROUP_IDS}})
    groups.insert_many([
        {'public_id': DIRECT_GROUP_ID, 'name': 'direct-right', 'label': 'Direct', 'rights': [RIGHT]},
        {'public_id': WILDCARD_GROUP_ID, 'name': 'wildcard-right', 'label': 'Wildcard', 'rights': [PARENT_WILDCARD]},
        {'public_id': EMPTY_GROUP_ID, 'name': 'no-right', 'label': 'None', 'rights': []},
    ])

    with rest_api.application.app_context():
        yield

    groups.delete_many({'public_id': {'$in': GROUP_IDS}})


def _user(group_id: int) -> CmdbUser:
    """An on-premise user of the given group, as insert_request_user would hand it in."""
    return CmdbUser(public_id=1, user_name='right-check', active=True, group_id=group_id)


def test_a_stored_right_is_held() -> None:
    """The group's stored right name resolves through the real right tree"""
    assert user_has_right(RIGHT, _user(DIRECT_GROUP_ID)) is True
    assert user_has_right(OTHER_RIGHT, _user(DIRECT_GROUP_ID)) is False


def test_a_parent_wildcard_grants_its_children() -> None:
    """base.framework.object.* grants base.framework.object.view, and nothing outside its branch"""
    assert user_has_right(RIGHT, _user(WILDCARD_GROUP_ID)) is True
    assert user_has_right(OTHER_RIGHT, _user(WILDCARD_GROUP_ID)) is False


def test_a_group_without_the_right_refuses() -> None:
    """Neither the right nor a wildcard of it"""
    assert user_has_right(RIGHT, _user(EMPTY_GROUP_ID)) is False


def test_a_user_whose_group_is_gone_holds_no_right() -> None:
    """Authenticated, but refused every right - no error"""
    assert user_has_right(RIGHT, _user(MISSING_GROUP_ID)) is False


def test_on_premise_the_users_database_name_is_not_where_the_group_is_read() -> None:
    """
    A user carries the model's default database name; on-premise it must not select the database

    A manager given a database name uses it in every mode, so reading the group from the user's own
    name would look in a database that does not hold it and refuse every right
    """
    user: CmdbUser = _user(DIRECT_GROUP_ID)

    assert user.database != ''
    assert user_has_right(RIGHT, user) is True


def test_in_cloud_mode_the_group_is_read_from_the_users_tenant(rest_api, monkeypatch: pytest.MonkeyPatch,
                                                               database_name: str) -> None:
    """The provider binds the tenant database the user carries"""
    monkeypatch.setattr(rest_api.application, 'cloud_mode', True)
    tenant_user: CmdbUser = CmdbUser(public_id=1, user_name='right-check', active=True,
                                     group_id=DIRECT_GROUP_ID, database=database_name)
    elsewhere_user: CmdbUser = CmdbUser(public_id=1, user_name='right-check', active=True,
                                        group_id=DIRECT_GROUP_ID, database=f'{database_name}-other-tenant')

    assert user_has_right(RIGHT, tenant_user) is True
    assert user_has_right(RIGHT, elsewhere_user) is False
