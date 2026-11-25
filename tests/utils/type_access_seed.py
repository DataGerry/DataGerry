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
Stores the access rules a test's seeded type ACLs translate to - so the access engine decides as those ACLs do

A test that seeds Types with an activated ``acl`` calls ``store_type_access`` after storing them and
``remove_type_access`` in its clean-up - a seed helper whose clean-up keeps no state calls
``remove_type_access_of_types`` with the Types it stored instead. The Types are read back from the collection and
translated (``access_engine.translate_type_acls``); every group an ACL names counts as existing - a test's groups often
are not stored, and the type ACL never asked. The roles and assignments get ids from a seed range and names marked with
it, so neither clashes with what a test stores itself, nor with another seed
"""
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pymongo.database import Database

from cmdb.framework.access_engine import assignment_documents, role_documents, translate_type_acls
from cmdb.models.access_model import AccessAssignmentKey, CmdbAccessAssignment, CmdbScopeRole, ScopeRoleKey
from cmdb.models.group_model import ADMIN_GROUP_ID
from cmdb.models.type_model import CmdbType
from cmdb.security.acl.acl_groups import acl_group_ids
# -------------------------------------------------------------------------------------------------------------------- #

# Seeded ids start here - far above what any test stores itself
SEED_ID_FLOOR: int = 8_000_000

# Appended to every seeded role's name, with the role's id
SEED_NAME_MARK: str = ' [seed {role_id}]'

ACL_KEY: str = 'acl'
PUBLIC_ID_KEY: str = 'public_id'


@dataclass
class SeededAccess:
    """
    What one ``store_type_access`` stored

    Attributes:
        role_ids (list[int]): The scope roles' public_ids
        assignment_ids (list[int]): The assignments' public_ids
    """
    role_ids: list[int] = field(default_factory=list)
    assignment_ids: list[int] = field(default_factory=list)


def _next_id(collection: Any) -> int:
    """The first free id at or above the seed floor"""
    highest: dict[str, Any] | None = collection.find_one({PUBLIC_ID_KEY: {'$gte': SEED_ID_FLOOR}},
                                                         sort=[(PUBLIC_ID_KEY, -1)])

    return SEED_ID_FLOOR if highest is None else highest[PUBLIC_ID_KEY] + 1


def store_type_access(database: Database, type_ids: Iterable[int]) -> SeededAccess:
    """
    Stores the roles and assignments the given stored Types' ACLs translate to

    Args:
        database (Database): The test database
        type_ids (Iterable[int]): The seeded Types - read back as stored

    Returns:
        SeededAccess: What was stored, for ``remove_type_access``
    """
    types: list[dict[str, Any]] = list(database[CmdbType.COLLECTION].find({PUBLIC_ID_KEY: {'$in': list(type_ids)}}))
    named_groups: set[int] = {group_id for document in types for group_id in acl_group_ids(document.get(ACL_KEY))}
    roles = translate_type_acls(types, named_groups | {ADMIN_GROUP_ID}, ADMIN_GROUP_ID)

    if not roles:
        return SeededAccess()

    first_role_id: int = _next_id(database[CmdbScopeRole.COLLECTION])
    first_assignment_id: int = _next_id(database[CmdbAccessAssignment.COLLECTION])
    role_docs: list[dict[str, Any]] = role_documents(roles, first_role_id)

    for document in role_docs:
        document[ScopeRoleKey.NAME.value] += SEED_NAME_MARK.format(role_id=document[ScopeRoleKey.PUBLIC_ID.value])

    assignment_docs: list[dict[str, Any]] = assignment_documents(roles, first_role_id, first_assignment_id)
    database[CmdbScopeRole.COLLECTION].insert_many(role_docs)
    database[CmdbAccessAssignment.COLLECTION].insert_many(assignment_docs)

    return SeededAccess(role_ids=[document[PUBLIC_ID_KEY] for document in role_docs],
                        assignment_ids=[document[PUBLIC_ID_KEY] for document in assignment_docs])


def remove_type_access(database: Database, seeded: SeededAccess) -> None:
    """
    Removes what ``store_type_access`` stored

    Args:
        database (Database): The test database
        seeded (SeededAccess): What was stored
    """
    database[CmdbAccessAssignment.COLLECTION].delete_many({PUBLIC_ID_KEY: {'$in': seeded.assignment_ids}})
    database[CmdbScopeRole.COLLECTION].delete_many({PUBLIC_ID_KEY: {'$in': seeded.role_ids}})


def remove_type_access_of_types(database: Database, type_ids: Iterable[int]) -> None:
    """
    Removes every seeded role naming one of the given Types, with its assignments - for a clean-up that keeps no
    ``SeededAccess``; roles and assignments a test stored itself (below the seed floor) are left alone

    Args:
        database (Database): The test database
        type_ids (Iterable[int]): The seeded Types
    """
    role_ids: list[int] = [document[PUBLIC_ID_KEY] for document in database[CmdbScopeRole.COLLECTION].find(
        {PUBLIC_ID_KEY: {'$gte': SEED_ID_FLOOR}, ScopeRoleKey.TYPES.value: {'$in': list(type_ids)}},
        {PUBLIC_ID_KEY: 1})]

    if not role_ids:
        return

    database[CmdbAccessAssignment.COLLECTION].delete_many({PUBLIC_ID_KEY: {'$gte': SEED_ID_FLOOR},
                                                           AccessAssignmentKey.ROLE_ID.value: {'$in': role_ids}})
    database[CmdbScopeRole.COLLECTION].delete_many({PUBLIC_ID_KEY: {'$in': role_ids}})
