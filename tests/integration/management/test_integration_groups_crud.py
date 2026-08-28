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
Integration tests for the CmdbUserGroup CRUD surface of GroupsManager

Pins the manager-layer behavior against a real MongoDB instance after the refactor onto
GenericManager: insert returns the new public_id and persists the doc, get_group resolves
present ids into hydrated ``CmdbUserGroup`` instances and missing ids to None, update
overwrites the label, delete reports the removal and refuses the protected bootstrap ids,
iterate finds the seeded rows
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.models.group_model import (
    CmdbUserGroup,
    ADMIN_GROUP_ID,
    USER_GROUP_ID,
    MASTER_RIGHT_NAME,
)

from cmdb.errors.manager.groups_manager import GroupsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID_FOR_GET: int = 9801
GROUP_ID_FOR_UPDATE: int = 9802
GROUP_ID_FOR_DELETE: int = 9803
GROUP_ID_FOR_INSERT: int = 9804
GROUP_IDS_FOR_ITERATE: list[int] = [9811, 9812, 9813]
MISSING_GROUP_ID: int = 9899
FORGED_GROUP_ID: int = 9898

ALL_SEEDED_IDS: list[int] = [
    GROUP_ID_FOR_GET,
    GROUP_ID_FOR_UPDATE,
    GROUP_ID_FOR_DELETE,
    GROUP_ID_FOR_INSERT,
    MISSING_GROUP_ID,
    FORGED_GROUP_ID,
    *GROUP_IDS_FOR_ITERATE,
]

ORIGINAL_LABEL: str = 'Original'
UPDATED_LABEL: str = 'Updated'


def _group_data(public_id: int, label: str = ORIGINAL_LABEL) -> dict[str, Any]:
    """Builds a minimal CmdbUserGroup payload acceptable to ``GroupsManager.insert_group``."""
    return {
        'public_id': public_id,
        'name': f'group-{public_id}',
        'label': label,
        'rights': [],
    }


@pytest.fixture(scope='module', autouse=True)
def _cleanup_seeded_groups(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover seeded CmdbUserGroup docs after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_SEEDED_IDS}})


@pytest.fixture(name='groups_manager')
def fixture_groups_manager(database_manager: MongoDatabaseManager) -> GroupsManager:
    """Provides a GroupsManager wired to the test database."""
    return GroupsManager(database_manager)


def _delete_group_by_id(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes one CmdbUserGroup doc directly via the collection, used for per-test cleanup."""
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       INSERT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertGroup:
    """``GroupsManager.insert_group`` persists the doc and returns its public_id."""

    def test_returns_public_id_and_persists(
        self,
        groups_manager: GroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Insert returns the public_id of the new doc and a follow-up find sees the persisted row."""
        try:
            returned_id = groups_manager.insert_group(_group_data(GROUP_ID_FOR_INSERT))

            assert returned_id == GROUP_ID_FOR_INSERT
            stored = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
                .find_one({'public_id': GROUP_ID_FOR_INSERT})
            assert stored is not None
            assert stored['name'] == f'group-{GROUP_ID_FOR_INSERT}'
        finally:
            _delete_group_by_id(database_manager, database_name, GROUP_ID_FOR_INSERT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        GET                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetGroup:
    """``GroupsManager.get_group`` returns a hydrated CmdbUserGroup, or None when missing."""

    @pytest.fixture(autouse=True)
    def _seed_one(
        self,
        groups_manager: GroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Inserts a single group before each test in this class and removes it after."""
        groups_manager.insert_group(_group_data(GROUP_ID_FOR_GET))
        yield
        _delete_group_by_id(database_manager, database_name, GROUP_ID_FOR_GET)

    def test_returns_cmdb_user_group_for_present_id(self, groups_manager: GroupsManager) -> None:
        """A present id resolves into a ``CmdbUserGroup`` instance carrying the seeded public_id."""
        result = groups_manager.get_group(GROUP_ID_FOR_GET)

        assert isinstance(result, CmdbUserGroup)
        assert result.public_id == GROUP_ID_FOR_GET

    def test_returns_none_for_missing_id(self, groups_manager: GroupsManager) -> None:
        """A missing id returns None instead of attempting to rehydrate (this is the refactor's bug fix)."""
        assert groups_manager.get_group(MISSING_GROUP_ID) is None

    def test_bootstrap_admin_group_holds_the_master_right(self, groups_manager: GroupsManager) -> None:
        """
        The seeded administrator group carries the master right

        This is the invariant the update route defends: ``base.*`` is the only right the admin group
        is seeded with, and losing it would leave nobody able to hand it back
        """
        admin_group = groups_manager.get_group(ADMIN_GROUP_ID)

        assert admin_group is not None
        assert admin_group.has_right(MASTER_RIGHT_NAME)
        assert admin_group.has_extended_right('base.user-management.group.edit')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateGroup:
    """``GroupsManager.update_group`` writes the new payload over the existing doc."""

    def test_persists_new_label(
        self,
        groups_manager: GroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Updating an existing group replaces the stored label."""
        try:
            groups_manager.insert_group(_group_data(GROUP_ID_FOR_UPDATE))

            groups_manager.update_group(GROUP_ID_FOR_UPDATE, _group_data(GROUP_ID_FOR_UPDATE, UPDATED_LABEL))

            stored = groups_manager.get_group(GROUP_ID_FOR_UPDATE)
            assert stored is not None
            assert stored.label == UPDATED_LABEL
        finally:
            _delete_group_by_id(database_manager, database_name, GROUP_ID_FOR_UPDATE)

    def test_update_missing_id_does_not_upsert(self, groups_manager: GroupsManager) -> None:
        """Updating a non-existent id is a no-op and must not silently insert a new doc."""
        groups_manager.update_group(MISSING_GROUP_ID, _group_data(MISSING_GROUP_ID, UPDATED_LABEL))

        assert groups_manager.get_group(MISSING_GROUP_ID) is None

    def test_update_does_not_rewrite_public_id(
        self,
        groups_manager: GroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A forged payload public_id cannot rewrite the stored id (identity is pinned to the arg)."""
        try:
            groups_manager.insert_group(_group_data(GROUP_ID_FOR_UPDATE))

            forged = _group_data(GROUP_ID_FOR_UPDATE, UPDATED_LABEL)
            forged['public_id'] = FORGED_GROUP_ID  # attacker-supplied mismatched id

            groups_manager.update_group(GROUP_ID_FOR_UPDATE, forged)

            # The real doc kept its id and got the new label; the forged id never came into existence
            stored = groups_manager.get_group(GROUP_ID_FOR_UPDATE)
            assert stored is not None
            assert stored.label == UPDATED_LABEL
            assert groups_manager.get_group(FORGED_GROUP_ID) is None
        finally:
            _delete_group_by_id(database_manager, database_name, GROUP_ID_FOR_UPDATE)
            _delete_group_by_id(database_manager, database_name, FORGED_GROUP_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteGroup:
    """``GroupsManager.delete_group`` removes regular groups and refuses the bootstrap admin / user ids."""

    def test_returns_true_and_removes_doc(
        self,
        groups_manager: GroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting an existing group returns True and a follow-up get returns None."""
        groups_manager.insert_group(_group_data(GROUP_ID_FOR_DELETE))

        deleted = groups_manager.delete_group(GROUP_ID_FOR_DELETE)

        assert deleted is True
        assert groups_manager.get_group(GROUP_ID_FOR_DELETE) is None
        _delete_group_by_id(database_manager, database_name, GROUP_ID_FOR_DELETE)

    @pytest.mark.parametrize('protected_id', [ADMIN_GROUP_ID, USER_GROUP_ID])
    def test_protected_bootstrap_ids_raise_delete_error(
        self,
        groups_manager: GroupsManager,
        protected_id: int,
    ) -> None:
        """Attempts to delete the bootstrap admin / user group raise ``GroupsManagerDeleteError``."""
        with pytest.raises(GroupsManagerDeleteError):
            groups_manager.delete_group(protected_id)

        # The protected group must still be present after the failed call.
        assert groups_manager.get_group(protected_id) is not None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      ITERATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterateGroups:
    """``GroupsManager.iterate`` returns the seeded groups matching the supplied filter."""

    @pytest.fixture(autouse=True)
    def _seed_many(
        self,
        groups_manager: GroupsManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ):
        """Inserts the iteration seed rows before the test and removes them after."""
        for public_id in GROUP_IDS_FOR_ITERATE:
            groups_manager.insert_group(_group_data(public_id))
        yield
        for public_id in GROUP_IDS_FOR_ITERATE:
            _delete_group_by_id(database_manager, database_name, public_id)

    def test_returns_seeded_rows_via_id_filter(self, groups_manager: GroupsManager) -> None:
        """A $match on the seed public_ids returns exactly the seeded set."""
        params = BuilderParameters(
            criteria=[{'$match': {'public_id': {'$in': GROUP_IDS_FOR_ITERATE}}}],
            sort='public_id',
            order=1,
        )

        result = groups_manager.iterate(params)

        returned_ids = [group.public_id for group in result.results]
        assert returned_ids == GROUP_IDS_FOR_ITERATE
        assert result.total == len(GROUP_IDS_FOR_ITERATE)
