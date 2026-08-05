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

Drive the cleanup helpers past a MagicMock standing in for the manager (no real database): the
shared ``_remove_id_from_filter`` issues the expected ``update_many_pull`` and wraps failures as
``CiExplorerProfileManagerUpdateError``; the two public helpers delegate to it with the correct
filter field.
"""
# pylint: disable=protected-access
from unittest.mock import MagicMock

import pytest

from cmdb.manager.ci_explorer_profile_manager import (
    CiExplorerProfileManager,
    TYPES_FILTER_FIELD,
    RELATIONS_FILTER_FIELD,
)
from cmdb.errors.manager.ci_explorer_profile_manager import CiExplorerProfileManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42
RELATION_ID: int = 73


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a CiExplorerProfileManager."""
    return MagicMock(spec=CiExplorerProfileManager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _remove_id_from_filter                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemoveIdFromFilter:
    """``_remove_id_from_filter`` pulls the id from the given field and wraps failures."""

    def test_issues_scoped_update_many_pull(self) -> None:
        """The helper issues a single ``update_many_pull`` scoped to and pulling from the field."""
        mgr = _mock_manager()

        CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID)

        mgr.update_many_pull.assert_called_once_with(
            {TYPES_FILTER_FIELD: TYPE_ID}, {TYPES_FILTER_FIELD: TYPE_ID},
        )

    def test_wraps_failure_as_update_error(self) -> None:
        """A failure in the underlying pull surfaces as CiExplorerProfileManagerUpdateError."""
        mgr = _mock_manager()
        mgr.update_many_pull.side_effect = RuntimeError('db down')

        with pytest.raises(CiExplorerProfileManagerUpdateError):
            CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                    remove_type / remove_relation delegation                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemoveTypeFromProfiles:
    """``remove_type_from_profiles`` delegates to the shared helper on the 'types_filter' field."""

    def test_delegates_with_types_filter_field(self) -> None:
        """The public helper pulls the type_id from the TYPES_FILTER_FIELD."""
        mgr = _mock_manager()

        CiExplorerProfileManager.remove_type_from_profiles(mgr, TYPE_ID)

        mgr._remove_id_from_filter.assert_called_once_with(TYPES_FILTER_FIELD, TYPE_ID)


class TestRemoveRelationFromProfiles:
    """``remove_relation_from_profiles`` delegates to the shared helper on the 'relations_filter' field."""

    def test_delegates_with_relations_filter_field(self) -> None:
        """The public helper pulls the relation_id from the RELATIONS_FILTER_FIELD."""
        mgr = _mock_manager()

        CiExplorerProfileManager.remove_relation_from_profiles(mgr, RELATION_ID)

        mgr._remove_id_from_filter.assert_called_once_with(RELATIONS_FILTER_FIELD, RELATION_ID)
