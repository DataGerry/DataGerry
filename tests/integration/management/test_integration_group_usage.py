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
Integration tests for the CmdbUserGroup usage census against a real MongoDB

Seeds two groups, a member, an auth section naming the group, a Type with a stored ACL naming the group, two scope
roles and assignments, and asserts:

  - the census reads the members and the LDAP default and mapping rows
  - the delete's access effect lists the group's own assignments and the Types their removal locks or opens
  - a stored type ACL naming the group is no part of the census
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.access_routes.access_change_guard import GroupDeleteEffect, group_delete_effect
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.group_usage_helper import (
    add_access_usage,
    read_group_usage,
)
from cmdb.manager import SettingsManager, UsersManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

GROUP: int = 98901
OTHER_GROUP: int = 98902
MEMBER_ID: int = 98911
VIEWED_TYPE: int = 98921
EDITED_TYPE: int = 98922
VIEW_ROLE: int = 98931
EDIT_ROLE: int = 98932
VIEW_EDITED_ROLE: int = 98933
OWN_VIEW_ASSIGNMENT: int = 98941
OWN_EDITED_VIEW_ASSIGNMENT: int = 98942
OTHER_EDIT_ASSIGNMENT: int = 98943
ALL_TYPES: list[int] = [VIEWED_TYPE, EDITED_TYPE]
GROUP_DN: str = 'cn=integration,dc=example,dc=com'
AUTH_ID: str = 'auth'
CALLER: CmdbUser = CmdbUser(public_id=98951, user_name='usage-caller', active=True, group_ids=[OTHER_GROUP])


def _role(public_id: int, type_id: int, operations: list[str]) -> dict[str, Any]:
    """A stored scope role on one Type"""
    return {'public_id': public_id, 'name': f'usage-role-{public_id}', 'description': '', 'types': [type_id],
            'operations': operations, 'write_regular_fields': True, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int) -> dict[str, Any]:
    """A stored unconditional assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': '*', 'description': ''}


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """
    The group views VIEWED_TYPE alone (its removal opens it) and views EDITED_TYPE, which the other group may only
    edit (its removal locks it) - all restored after
    """
    database = database_manager.connector.client[database_name]
    settings = database[SettingsManager.COLLECTION]
    stored_auth = settings.find_one({'_id': AUTH_ID})

    def _purge() -> None:
        database[CmdbUserGroup.COLLECTION].delete_many({'public_id': {'$in': [GROUP, OTHER_GROUP]}})
        database[CmdbUser.COLLECTION].delete_many({'public_id': MEMBER_ID})
        database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': ALL_TYPES}})
        database[CmdbScopeRole.COLLECTION].delete_many({'public_id': {'$in': [VIEW_ROLE, EDIT_ROLE, VIEW_EDITED_ROLE]}})
        database[CmdbAccessAssignment.COLLECTION].delete_many({'public_id': {'$in': [
            OWN_VIEW_ASSIGNMENT, OWN_EDITED_VIEW_ASSIGNMENT, OTHER_EDIT_ASSIGNMENT]}})

    _purge()
    database[CmdbUserGroup.COLLECTION].insert_many([
        {'public_id': group_id, 'name': f'usage-{group_id}', 'label': 'Usage', 'rights': []}
        for group_id in (GROUP, OTHER_GROUP)])
    database[CmdbUser.COLLECTION].insert_one({'public_id': MEMBER_ID, 'user_name': 'usage-member',
                                              'group_ids': [GROUP], 'active': True})
    database[CmdbType.COLLECTION].insert_one({
        **make_type_doc(VIEWED_TYPE, f'usage-type-{VIEWED_TYPE}'),
        'acl': {'activated': True, 'groups': {'includes': {str(GROUP): ['READ']}}},
    })
    database[CmdbType.COLLECTION].insert_one(make_type_doc(EDITED_TYPE, f'usage-type-{EDITED_TYPE}'))
    database[CmdbScopeRole.COLLECTION].insert_many([
        _role(VIEW_ROLE, VIEWED_TYPE, ['view']), _role(EDIT_ROLE, EDITED_TYPE, ['edit']),
        _role(VIEW_EDITED_ROLE, EDITED_TYPE, ['view']),
    ])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        _assignment(OWN_VIEW_ASSIGNMENT, GROUP, VIEW_ROLE),
        _assignment(OWN_EDITED_VIEW_ASSIGNMENT, GROUP, VIEW_EDITED_ROLE),
        _assignment(OTHER_EDIT_ASSIGNMENT, OTHER_GROUP, EDIT_ROLE),
    ])
    settings.replace_one({'_id': AUTH_ID}, {'_id': AUTH_ID, 'providers': [{
        'class_name': 'LdapAuthenticationProvider',
        'config': {'default_group': GROUP, 'groups': {'mapping': [{'group_dn': GROUP_DN, 'group_id': GROUP}]}},
    }]}, upsert=True)
    yield
    _purge()
    if stored_auth is None:
        settings.delete_one({'_id': AUTH_ID})
    else:
        settings.replace_one({'_id': AUTH_ID}, stored_auth)


def test_the_census_reads_the_members_and_the_ldap_settings(database_manager) -> None:
    """Members, LDAP default + mapping; the stored type ACL naming the group is no part of it"""
    usage = read_group_usage(GROUP, (UsersManager(database_manager), SettingsManager(database_manager)))

    assert (usage.members, usage.sole_members, usage.ldap_default_group, usage.ldap_group_mappings) == (
        1, 1, True, [GROUP_DN])
    assert (usage.locked_type_ids, usage.opened_type_ids, usage.assignment_ids) == ([], [], [])


def test_the_delete_effect_lists_own_assignments_and_the_types_locked_and_opened() -> None:
    """VIEWED_TYPE loses its only restriction (opened), EDITED_TYPE its only viewer (locked)"""
    effect: GroupDeleteEffect = group_delete_effect(CALLER, GROUP)

    assert effect == GroupDeleteEffect([OWN_VIEW_ASSIGNMENT, OWN_EDITED_VIEW_ASSIGNMENT], [EDITED_TYPE], [VIEWED_TYPE])


def test_the_effect_joins_the_census(database_manager) -> None:
    """The answer the usage route gives - a locked Type blocks"""
    usage = read_group_usage(GROUP, (UsersManager(database_manager), SettingsManager(database_manager)))

    add_access_usage(usage, group_delete_effect(CALLER, GROUP))

    assert (usage.locked_type_ids, usage.opened_type_ids, usage.blocks_delete) == ([EDITED_TYPE], [VIEWED_TYPE], True)
