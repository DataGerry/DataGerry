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
Integration tests for cmdb.database.updater.versions.updater_20261001 against a real MongoDB

Seeds CmdbTypes with every kind of ``acl.activated`` a database written before the boolean rule may hold, runs
the migration, and asserts:

  - each non-boolean value became the boolean the single read already decided on, and nothing else changed
  - a second run changes nothing
  - afterwards the listing query (``build_denied_types_criteria``, ``activated: true``) and the single read
    (``acl_grants_access``) agree on every one of those types - the disagreement on ``0`` / ``""`` is gone
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261001 import Update20261001
from cmdb.manager.types_manager import TypesManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.builder import build_denied_types_criteria
from cmdb.security.acl.helpers import acl_grants_access
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

# A group the seeded ACLs grant nothing, so an activated ACL denies it
GROUP_ID: int = 2
ABSENT: object = object()

# public_id -> the stored activated value (ABSENT = no key at all)
STORED_FLAGS: dict[int, Any] = {
    97701: 'yes',
    97702: 'false',
    97703: 0,
    97704: '',
    97705: 1,
    97706: True,
    97707: False,
    97708: None,
    97709: ABSENT,
}

# What each value reads as - the boolean the migration stores, and what a null or absent flag stays
EXPECTED_AFTER: dict[int, Any] = {
    97701: True, 97702: True, 97703: False, 97704: False, 97705: True,
    97706: True, 97707: False, 97708: None, 97709: ABSENT,
}


def _type_doc(public_id: int, activated: Any) -> dict[str, Any]:
    """A type whose ACL grants the test group nothing, with the given flag"""
    doc = make_type_doc(public_id, f'acl-flag-{public_id}')
    acl: dict[str, Any] = {'groups': {'includes': {'1': ['READ']}}}

    if activated is not ABSENT:
        acl['activated'] = activated

    doc[TypeSchemaKey.ACL.value] = acl

    return doc


@pytest.fixture(name='types', autouse=True)
def fixture_types(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded types, purged before and after"""
    collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({TypeSchemaKey.PUBLIC_ID.value: {'$in': list(STORED_FLAGS)}})

    _purge()
    collection.insert_many([_type_doc(public_id, activated) for public_id, activated in STORED_FLAGS.items()])
    yield collection
    _purge()


def _stored_flags(types: Any) -> dict[int, Any]:
    """public_id -> the stored activated value, ABSENT for no key"""
    return {
        doc[TypeSchemaKey.PUBLIC_ID.value]: doc[TypeSchemaKey.ACL.value].get('activated', ABSENT)
        for doc in types.find({TypeSchemaKey.PUBLIC_ID.value: {'$in': list(STORED_FLAGS)}})
    }


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261001(database_manager, database_name).start_update()


def test_each_flag_becomes_the_boolean_it_reads_as(database_manager, database_name, types) -> None:
    """Non-booleans are rewritten; booleans, null and an absent key are left as they are"""
    _run(database_manager, database_name)

    assert _stored_flags(types) == EXPECTED_AFTER


def test_a_second_run_changes_nothing(database_manager, database_name, types) -> None:
    """Re-run safe: the first run left nothing the selection matches"""
    _run(database_manager, database_name)
    after_first: dict[int, Any] = _stored_flags(types)

    _run(database_manager, database_name)

    assert _stored_flags(types) == after_first


def test_the_listing_and_the_single_read_agree_afterwards(database_manager, database_name, types) -> None:
    """The listing denies exactly the types the single read denies"""
    _run(database_manager, database_name)

    denied_by_listing: set[int] = {
        doc[TypeSchemaKey.PUBLIC_ID.value]
        for doc in TypesManager(database_manager).find(
            criteria={
                '$and': [
                    build_denied_types_criteria(GROUP_ID, AccessControlPermission.READ),
                    {TypeSchemaKey.PUBLIC_ID.value: {'$in': list(STORED_FLAGS)}},
                ],
            },
        )
    }
    denied_by_single_read: set[int] = {
        doc[TypeSchemaKey.PUBLIC_ID.value]
        for doc in types.find({TypeSchemaKey.PUBLIC_ID.value: {'$in': list(STORED_FLAGS)}})
        if not acl_grants_access(
            AccessControlList.from_data(doc[TypeSchemaKey.ACL.value]), GROUP_ID, AccessControlPermission.READ,
        )
    }

    assert denied_by_listing == denied_by_single_read == {97701, 97702, 97705, 97706}
