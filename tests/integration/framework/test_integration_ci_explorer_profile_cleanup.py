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
Integration tests for the CiExplorerProfileManager cleanup helpers

Against a real MongoDB, verify that ``remove_type_from_profiles`` / ``remove_relation_from_profiles``
pull the given id from the matching array of every profile that references it, while leaving the
other array and the profiles that do not reference it untouched.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.ci_explorer_profile_manager import CiExplorerProfileManager
from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 8870
OTHER_TYPE_ID: int = 8871
RELATION_ID: int = 8880
OTHER_RELATION_ID: int = 8881

PROFILE_WITH_REFS: int = 8890
PROFILE_WITHOUT_REFS: int = 8891

ALL_PROFILE_IDS: list[int] = [PROFILE_WITH_REFS, PROFILE_WITHOUT_REFS]


def _profile_doc(public_id: int, types_filter: list[int], relations_filter: list[int]) -> dict[str, Any]:
    """Builds a CmdbCiExplorerProfile doc for direct DB insertion."""
    return {
        'public_id': public_id,
        'name': f'profile-{public_id}',
        'types_filter': types_filter,
        'relations_filter': relations_filter,
        'with_locations': True,
        'with_ipam_relations': False,
    }


@pytest.fixture(name='ci_explorer_profile_manager')
def fixture_ci_explorer_profile_manager(database_manager: MongoDatabaseManager) -> CiExplorerProfileManager:
    """Provides a CiExplorerProfileManager wired to the test database."""
    return CiExplorerProfileManager(database_manager)


@pytest.fixture(autouse=True)
def _seed_profiles(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one profile referencing the ids under test and one that does not; cleans up after."""
    collection = database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)
    collection.insert_many([
        _profile_doc(PROFILE_WITH_REFS, [TYPE_ID, OTHER_TYPE_ID], [RELATION_ID, OTHER_RELATION_ID]),
        _profile_doc(PROFILE_WITHOUT_REFS, [OTHER_TYPE_ID], [OTHER_RELATION_ID]),
    ])
    yield
    collection.delete_many({'public_id': {'$in': ALL_PROFILE_IDS}})


def _profile(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any]:
    """Reads a single profile doc back from the collection."""
    return database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


class TestRemoveTypeFromProfiles:
    """``remove_type_from_profiles`` removes the type_id from every profile's 'types_filter'."""

    def test_pulls_only_the_given_type_and_leaves_the_rest(
        self,
        ci_explorer_profile_manager: CiExplorerProfileManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The type_id is pulled from the referencing profile; other ids, the other array and the other profile stay."""
        ci_explorer_profile_manager.remove_type_from_profiles(TYPE_ID)

        with_refs = _profile(database_manager, database_name, PROFILE_WITH_REFS)
        without_refs = _profile(database_manager, database_name, PROFILE_WITHOUT_REFS)

        # Only TYPE_ID is pulled from the referencing profile's types_filter
        assert with_refs['types_filter'] == [OTHER_TYPE_ID]
        # The relations_filter of the same profile is untouched
        assert with_refs['relations_filter'] == [RELATION_ID, OTHER_RELATION_ID]
        # A profile that never referenced TYPE_ID is left as-is
        assert without_refs['types_filter'] == [OTHER_TYPE_ID]


class TestRemoveRelationFromProfiles:
    """``remove_relation_from_profiles`` removes the relation_id from every profile's 'relations_filter'."""

    def test_pulls_only_the_given_relation_and_leaves_the_rest(
        self,
        ci_explorer_profile_manager: CiExplorerProfileManager,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The relation_id is pulled from the referencing profile; other ids, the other array and profile stay."""
        ci_explorer_profile_manager.remove_relation_from_profiles(RELATION_ID)

        with_refs = _profile(database_manager, database_name, PROFILE_WITH_REFS)
        without_refs = _profile(database_manager, database_name, PROFILE_WITHOUT_REFS)

        # Only RELATION_ID is pulled from the referencing profile's relations_filter
        assert with_refs['relations_filter'] == [OTHER_RELATION_ID]
        # The types_filter of the same profile is untouched
        assert with_refs['types_filter'] == [TYPE_ID, OTHER_TYPE_ID]
        # A profile that never referenced RELATION_ID is left as-is
        assert without_refs['relations_filter'] == [OTHER_RELATION_ID]
