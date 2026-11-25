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
Integration tests for what goes with a deleted user group and with gone Types, against the test MongoDB

A group's assignments are deleted in one write and the ledger's undo puts every one back, ``_id`` and all - also when
run twice; the pull of the gone Types keeps only the stored ids, leaves a role on every Type alone and is re-run safe
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_rules import delete_group_assignments
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import AccessAssignmentsManager, ScopeRolesManager
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 9601
OTHER_GROUP_ID: int = 9602
KEPT_TYPE_ID: int = 9611
GONE_TYPE_ID: int = 9612


def _assignment(public_id: int, group_id: int) -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': public_id, 'scope': '*', 'description': ''}


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """Three assignments - two of the group - and three roles"""
    database = database_manager.connector.client[database_name]
    collections: dict[str, Any] = {'assignments': database[CmdbAccessAssignment.COLLECTION],
                                   'roles': database[CmdbScopeRole.COLLECTION]}
    collections['assignments'].insert_many([_assignment(1, GROUP_ID), _assignment(2, GROUP_ID),
                                            _assignment(3, OTHER_GROUP_ID)])
    collections['roles'].insert_many([
        {'public_id': 1, 'name': 'both', 'types': [KEPT_TYPE_ID, GONE_TYPE_ID], 'operations': []},
        {'public_id': 2, 'name': 'gone', 'types': [GONE_TYPE_ID], 'operations': []},
        {'public_id': 3, 'name': 'every', 'types': '*', 'operations': []},
    ])

    yield collections

    for collection in collections.values():
        collection.delete_many({})


def _stored(collection: Any) -> list[dict[str, Any]]:
    """Every document, ``_id`` included, by public_id"""
    return sorted(collection.find(), key=lambda document: document['public_id'])


class TestGroupAssignments:
    """Deleted in one write; the ledger puts them back."""

    def test_the_groups_assignments_go(self, database_manager: MongoDatabaseManager,
                                       collections: dict[str, Any]) -> None:
        """Two deleted, the other group's stays"""
        ledger = WriteLedger()

        assert delete_group_assignments(ledger, AccessAssignmentsManager(database_manager), GROUP_ID) == 2
        assert [document['public_id'] for document in _stored(collections['assignments'])] == [3]

    def test_the_undo_restores_them_exactly(self, database_manager: MongoDatabaseManager,
                                            collections: dict[str, Any]) -> None:
        """Same documents, same _id; a second undo changes nothing"""
        before: list[dict[str, Any]] = _stored(collections['assignments'])
        ledger = WriteLedger()
        delete_group_assignments(ledger, AccessAssignmentsManager(database_manager), GROUP_ID)

        assert not ledger.undo()
        assert _stored(collections['assignments']) == before
        assert not ledger.undo()
        assert _stored(collections['assignments']) == before


class TestPullMissingTypes:
    """Only stored ids stay; '*' is left alone; re-run safe."""

    def test_the_gone_type_leaves(self, database_manager: MongoDatabaseManager, collections: dict[str, Any]) -> None:
        """Two roles changed - one keeps its stored Type, one is left with none"""
        assert ScopeRolesManager(database_manager).pull_missing_types([KEPT_TYPE_ID]) == 2

        types: dict[int, Any] = {role['public_id']: role['types'] for role in collections['roles'].find()}
        assert types == {1: [KEPT_TYPE_ID], 2: [], 3: '*'}

    def test_no_type_stored_empties_every_listing_role(self, database_manager: MongoDatabaseManager,
                                                       collections: dict[str, Any]) -> None:
        """What a configuration reset leaves; a second pull changes nothing"""
        manager = ScopeRolesManager(database_manager)
        manager.pull_missing_types([])

        assert {role['public_id']: role['types'] for role in collections['roles'].find()} == {1: [], 2: [], 3: '*'}
        assert manager.pull_missing_types([]) == 0
