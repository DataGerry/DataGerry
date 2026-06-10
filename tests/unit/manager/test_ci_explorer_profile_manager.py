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
Unit tests for CiExplorerProfileManager

Drive the two cleanup helpers (``remove_type_from_profiles`` / ``remove_relation_from_profiles``)
past a MagicMock standing in for the manager, asserting each issues the expected
``update_many_pull`` call (correct filter field and pulled id) without touching a real database.
"""
from unittest.mock import MagicMock

from cmdb.manager.ci_explorer_profile_manager import CiExplorerProfileManager
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42
RELATION_ID: int = 73


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a CiExplorerProfileManager."""
    return MagicMock(spec=CiExplorerProfileManager)


class TestRemoveTypeFromProfiles:
    """``remove_type_from_profiles`` pulls the type_id from every profile's 'types_filter'."""

    def test_pulls_type_id_from_types_filter(self) -> None:
        """The helper issues a single ``update_many_pull`` scoped to and pulling from 'types_filter'."""
        mgr = _mock_manager()

        CiExplorerProfileManager.remove_type_from_profiles(mgr, TYPE_ID)

        mgr.update_many_pull.assert_called_once_with(
            {'types_filter': TYPE_ID}, {'types_filter': TYPE_ID},
        )


class TestRemoveRelationFromProfiles:
    """``remove_relation_from_profiles`` pulls the relation_id from every profile's 'relations_filter'."""

    def test_pulls_relation_id_from_relations_filter(self) -> None:
        """The helper issues a single ``update_many_pull`` scoped to and pulling from 'relations_filter'."""
        mgr = _mock_manager()

        CiExplorerProfileManager.remove_relation_from_profiles(mgr, RELATION_ID)

        mgr.update_many_pull.assert_called_once_with(
            {'relations_filter': RELATION_ID}, {'relations_filter': RELATION_ID},
        )
