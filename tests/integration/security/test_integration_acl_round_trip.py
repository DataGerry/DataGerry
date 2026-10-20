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
Integration tests for a CmdbType's ``acl`` block read into the model and written back, against a real MongoDB

The chain a type update runs: the stored block (string group keys, lists of permission values) is read into a
``GroupACL`` (int keys), changed in memory (sets), and written back through ``TypesManager.update_type``. Pinned:

  - the block is stored again in its stored form - string keys, each permission list sorted
  - the stored result is what both access readers decide on alike: the model (``has_type_document_access``) and
    the query (``build_permitted_types_criteria``) grant exactly what the in-memory ACL granted
  - writing the same model twice stores the same block (re-run safe)
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.builder import build_permitted_types_criteria
from cmdb.security.acl.helpers import has_type_document_access
from cmdb.security.acl.permission import AccessControlPermission

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 97701
TYPE_NAME: str = 'acl-round-trip'

GRANTED_GROUP_ID: int = 2
DELETING_GROUP_ID: int = 3
NEW_GROUP_ID: int = 4
GROUP_IDS: list[int] = [GRANTED_GROUP_ID, DELETING_GROUP_ID, NEW_GROUP_ID]

# Stored unsorted on purpose: the write-back has to sort it
STORED_ACL: dict[str, Any] = {
    AclKey.ACTIVATED.value: True,
    AclKey.GROUPS.value: {AclKey.INCLUDES.value: {
        str(GRANTED_GROUP_ID): ['UPDATE', 'READ'],
        str(DELETING_GROUP_ID): ['DELETE'],
    }},
}

# After granting CREATE to the new group and revoking UPDATE from the granted one
CHANGED_INCLUDES: dict[str, list[str]] = {
    str(GRANTED_GROUP_ID): ['READ'],
    str(DELETING_GROUP_ID): ['DELETE'],
    str(NEW_GROUP_ID): ['CREATE'],
}


class _User:
    """Minimal stand-in for CmdbUser: the access readers read nothing but group_id"""

    def __init__(self, group_id: int) -> None:
        self.group_id = group_id


@pytest.fixture(name='types')
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """The types collection holding the one seeded type, removed again afterwards"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    collection.delete_many({TypeSchemaKey.PUBLIC_ID.value: TYPE_ID})

    document: dict[str, Any] = make_type_doc(TYPE_ID, TYPE_NAME)
    document[TypeSchemaKey.ACL.value] = STORED_ACL
    collection.insert_one(document)

    yield collection

    collection.delete_many({TypeSchemaKey.PUBLIC_ID.value: TYPE_ID})


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """A TypesManager on the test database"""
    return TypesManager(database_manager)


def _changed_type(types_manager: TypesManager) -> CmdbType:
    """Reads the seeded type into the model and changes its ACL in memory"""
    cmdb_type: CmdbType | None = types_manager.get_type_instance(TYPE_ID)
    assert cmdb_type is not None

    cmdb_type.acl.grant_access(NEW_GROUP_ID, AccessControlPermission.CREATE)
    cmdb_type.acl.revoke_access(GRANTED_GROUP_ID, AccessControlPermission.UPDATE)

    return cmdb_type


def _stored_acl(types: Any) -> dict[str, Any]:
    """The acl block as it is stored now"""
    return types.find_one({TypeSchemaKey.PUBLIC_ID.value: TYPE_ID})[TypeSchemaKey.ACL.value]


@pytest.mark.usefixtures('types')
class TestReadIntoTheModel:
    """The stored block, read through the manager"""

    def test_the_group_keys_are_ints(self, types_manager: TypesManager) -> None:
        """What a CmdbUser's group_id is compared against"""
        cmdb_type: CmdbType | None = types_manager.get_type_instance(TYPE_ID)

        assert sorted(cmdb_type.acl.groups.includes) == [GRANTED_GROUP_ID, DELETING_GROUP_ID]

    def test_the_model_decides_on_the_stored_permissions(self, types_manager: TypesManager) -> None:
        """Granted is granted and nothing else"""
        acl: AccessControlList = types_manager.get_type_instance(TYPE_ID).acl

        assert acl.verify_access(GRANTED_GROUP_ID, AccessControlPermission.UPDATE) is True
        assert acl.verify_access(DELETING_GROUP_ID, AccessControlPermission.DELETE) is True
        assert acl.verify_access(DELETING_GROUP_ID, AccessControlPermission.READ) is False


class TestWrittenBack:
    """The changed model, stored through TypesManager.update_type"""

    def test_the_block_is_stored_with_string_keys_and_sorted_lists(
        self, types, types_manager: TypesManager,
    ) -> None:
        """The stored form, whatever the in-memory containers became"""
        types_manager.update_type(TYPE_ID, _changed_type(types_manager))

        assert _stored_acl(types) == {
            AclKey.ACTIVATED.value: True,
            AclKey.GROUPS.value: {AclKey.INCLUDES.value: CHANGED_INCLUDES},
        }

    def test_an_unchanged_model_only_sorts_the_lists(self, types, types_manager: TypesManager) -> None:
        """Read and written back untouched: the same permissions, each list sorted"""
        types_manager.update_type(TYPE_ID, types_manager.get_type_instance(TYPE_ID))

        assert _stored_acl(types)[AclKey.GROUPS.value][AclKey.INCLUDES.value] == {
            str(GRANTED_GROUP_ID): ['READ', 'UPDATE'],
            str(DELETING_GROUP_ID): ['DELETE'],
        }

    def test_writing_twice_stores_the_same_block(self, types, types_manager: TypesManager) -> None:
        """Re-run safe: a second write of the same model changes nothing"""
        cmdb_type: CmdbType = _changed_type(types_manager)
        types_manager.update_type(TYPE_ID, cmdb_type)
        first: dict[str, Any] = _stored_acl(types)

        types_manager.update_type(TYPE_ID, cmdb_type)

        assert _stored_acl(types) == first

    @pytest.mark.parametrize('group_id', GROUP_IDS)
    @pytest.mark.parametrize('permission', list(AccessControlPermission))
    def test_both_readers_grant_what_the_model_granted(
        self, types, types_manager: TypesManager, group_id: int, permission: AccessControlPermission,
    ) -> None:
        """Twelve combinations: three groups against all four permissions, decided by model, document and query"""
        cmdb_type: CmdbType = _changed_type(types_manager)
        types_manager.update_type(TYPE_ID, cmdb_type)
        document: dict[str, Any] = types.find_one({TypeSchemaKey.PUBLIC_ID.value: TYPE_ID})

        in_memory: bool = cmdb_type.acl.verify_access(group_id, permission)
        by_document: bool = has_type_document_access(document, _User(group_id), permission)
        by_query: bool = types.count_documents({
            '$and': [{TypeSchemaKey.PUBLIC_ID.value: TYPE_ID}, build_permitted_types_criteria(group_id, permission)]
        }) == 1

        assert in_memory == by_document == by_query
