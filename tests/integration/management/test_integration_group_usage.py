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
Integration tests for the CmdbUserGroup usage census and the ACL entry removal against a real MongoDB

Seeds types whose ACL grants the group alone, next to another existing group, next to a deleted group only, and not
at all, plus an auth section naming the group, and asserts:

  - the census reads the members, the LDAP default and mapping rows, the sole-grantee and the naming types
  - the removal unsets the group's entry on every naming type and nothing else of them
  - the write ledger's undo writes each type's own entry back
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.group_usage_helper import (
    read_group_usage,
    remove_group_from_type_acls,
)
from cmdb.manager import GroupsManager, SettingsManager, TypesManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

GROUP: int = 98901
OTHER_GROUP: int = 98902
DELETED_GROUP: int = 98903
MEMBER_ID: int = 98911
SOLE_TYPE: int = 98921
SHARED_TYPE: int = 98922
DELETED_ONLY_TYPE: int = 98923
UNRELATED_TYPE: int = 98924
ALL_TYPES: list[int] = [SOLE_TYPE, SHARED_TYPE, DELETED_ONLY_TYPE, UNRELATED_TYPE]
GROUP_DN: str = 'cn=integration,dc=example,dc=com'
READ: list[str] = ['READ']
UPDATE: list[str] = ['READ', 'UPDATE']
AUTH_ID: str = 'auth'


def _acl(includes: dict[int, list[str]]) -> dict[str, Any]:
    """An activated acl block."""
    return {'activated': True, 'groups': {'includes': {str(key): value for key, value in includes.items()}}}


SEEDED_ACLS: dict[int, dict[str, Any]] = {
    SOLE_TYPE: _acl({GROUP: UPDATE, DELETED_GROUP: READ}),
    SHARED_TYPE: _acl({GROUP: READ, OTHER_GROUP: READ}),
    DELETED_ONLY_TYPE: _acl({DELETED_GROUP: READ}),
    UNRELATED_TYPE: _acl({OTHER_GROUP: READ}),
}


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Two groups, a member, the four types and an auth section naming the group - all restored after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    stored_auth = settings.find_one({'_id': AUTH_ID})

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [GROUP, OTHER_GROUP]}})
        users.delete_many({'public_id': MEMBER_ID})
        types.delete_many({'public_id': {'$in': ALL_TYPES}})

    _purge()
    groups.insert_many([{'public_id': group_id, 'name': f'usage-{group_id}', 'label': 'Usage', 'rights': []}
                        for group_id in (GROUP, OTHER_GROUP)])
    users.insert_one({'public_id': MEMBER_ID, 'user_name': 'usage-member', 'group_id': GROUP, 'active': True})
    for type_id, acl in SEEDED_ACLS.items():
        types.insert_one({**make_type_doc(type_id, f'usage-type-{type_id}'), 'acl': acl})
    settings.replace_one({'_id': AUTH_ID}, {'_id': AUTH_ID, 'providers': [{
        'class_name': 'LdapAuthenticationProvider',
        'config': {'default_group': GROUP, 'groups': {'mapping': [{'group_dn': GROUP_DN, 'group_id': GROUP}]}},
    }]}, upsert=True)
    yield types
    _purge()
    if stored_auth is None:
        settings.delete_one({'_id': AUTH_ID})
    else:
        settings.replace_one({'_id': AUTH_ID}, stored_auth)


def _managers(database_manager: MongoDatabaseManager) -> tuple[Any, ...]:
    """The four managers of the census"""
    return (UsersManager(database_manager), SettingsManager(database_manager), TypesManager(database_manager),
            GroupsManager(database_manager))


def _acls(types: Any) -> dict[int, dict[str, Any]]:
    """The stored ACL of every seeded type"""
    return {document['public_id']: document['acl'] for document in types.find({'public_id': {'$in': ALL_TYPES}})}


def test_the_census_reads_every_holder(database_manager) -> None:
    """Members, LDAP default + mapping, the locked type, every naming type"""
    usage = read_group_usage(GROUP, _managers(database_manager))

    assert (usage.members, usage.ldap_default_group, usage.ldap_group_mappings) == (1, True, [GROUP_DN])
    assert usage.sole_grantee_type_ids == [SOLE_TYPE]
    assert usage.acl_entries == {SOLE_TYPE: UPDATE, SHARED_TYPE: READ}
    assert usage.blocks_delete


def test_the_removal_unsets_only_the_groups_entry(seeded, database_manager) -> None:
    """Every naming type loses that one key; the others are untouched"""
    managers = _managers(database_manager)
    usage = read_group_usage(GROUP, managers)

    remove_group_from_type_acls(WriteLedger(), managers[2], GROUP, usage)

    stored = _acls(seeded)
    assert stored[SOLE_TYPE] == _acl({DELETED_GROUP: READ})
    assert stored[SHARED_TYPE] == _acl({OTHER_GROUP: READ})
    assert stored[DELETED_ONLY_TYPE] == SEEDED_ACLS[DELETED_ONLY_TYPE]
    assert stored[UNRELATED_TYPE] == SEEDED_ACLS[UNRELATED_TYPE]


def test_the_undo_writes_each_entry_back(seeded, database_manager) -> None:
    """A failed delete leaves the ACLs as they were"""
    managers = _managers(database_manager)
    ledger = WriteLedger()
    remove_group_from_type_acls(ledger, managers[2], GROUP, read_group_usage(GROUP, managers))

    residue = ledger.undo()

    assert not residue
    assert _acls(seeded) == SEEDED_ACLS
