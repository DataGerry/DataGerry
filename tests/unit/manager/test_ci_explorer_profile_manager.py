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

Drive the cleanup helpers past a MagicMock standing in for the manager (no real database). The shared
``_remove_id_from_filter`` first deletes the profiles the removal would leave with an EMPTY filter - an
empty filter means "no restriction", so pulling a narrow profile's last id would widen it to
everything - then pulls the id from every other profile, and wraps failures as
``CiExplorerProfileManagerUpdateError``. The two public helpers delegate to it with the right filter
field. What the criteria actually match is the integration tier's question
"""
# pylint: disable=protected-access
import logging
from unittest.mock import MagicMock

import pytest

from cmdb.manager.ci_explorer_profile_manager import CiExplorerProfileManager
from cmdb.models.ci_explorer_model import CiExplorerProfileKey
from cmdb.errors.manager.ci_explorer_profile_manager import CiExplorerProfileManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

TYPES_FILTER_FIELD: str = CiExplorerProfileKey.TYPES_FILTER.value
RELATIONS_FILTER_FIELD: str = CiExplorerProfileKey.RELATIONS_FILTER.value

TYPE_ID: int = 42
RELATION_ID: int = 73
EMPTIED_PROFILE: dict = {'public_id': 7, 'name': 'only-servers'}


def _mock_manager(emptied: list[dict] | None = None) -> MagicMock:
    """A CiExplorerProfileManager stand-in whose find() answers the profiles the removal would empty."""
    mgr = MagicMock(spec=CiExplorerProfileManager)
    mgr.build_emptied_filter_criteria.side_effect = CiExplorerProfileManager.build_emptied_filter_criteria
    mgr.find.return_value = emptied or []

    return mgr


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _remove_id_from_filter                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildEmptiedFilterCriteria:
    """The query of the profiles a pull would empty."""

    def test_the_filter_holds_the_id_and_nothing_else(self) -> None:
        """Holds the id, and holds no element that is anything else"""
        assert CiExplorerProfileManager.build_emptied_filter_criteria(TYPES_FILTER_FIELD, TYPE_ID) == {'$and': [
            {TYPES_FILTER_FIELD: TYPE_ID},
            {TYPES_FILTER_FIELD: {'$not': {'$elemMatch': {'$ne': TYPE_ID}}}},
        ]}


class TestRemoveIdFromFilter:
    """``_remove_id_from_filter`` deletes the profiles it would empty, pulls from the rest, wraps failures."""

    def test_nothing_emptied_is_a_plain_pull(self) -> None:
        """No profile holds the id alone: nothing is deleted, the id is pulled everywhere"""
        mgr = _mock_manager()

        assert CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID) == []

        mgr.delete_many.assert_not_called()
        mgr.update_many_pull.assert_called_once_with(
            {TYPES_FILTER_FIELD: TYPE_ID}, {TYPES_FILTER_FIELD: TYPE_ID},
        )

    def test_the_profiles_it_would_empty_are_looked_up_by_the_criteria(self) -> None:
        """The lookup asks exactly the emptied-filter criteria, and reads only the id and the name"""
        mgr = _mock_manager()

        CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID)

        mgr.find.assert_called_once_with(
            criteria=CiExplorerProfileManager.build_emptied_filter_criteria(TYPES_FILTER_FIELD, TYPE_ID),
            projection={'public_id': 1, 'name': 1},
        )

    def test_an_emptied_profile_is_deleted_and_answered(self) -> None:
        """A narrow profile losing its last id is deleted, not widened - and its id is answered"""
        mgr = _mock_manager([EMPTIED_PROFILE])

        deleted = CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID)

        assert deleted == [EMPTIED_PROFILE['public_id']]
        mgr.delete_many.assert_called_once_with({'public_id': {'$in': [EMPTIED_PROFILE['public_id']]}})

    def test_the_deletion_runs_before_the_pull(self) -> None:
        """Pulled first, an emptied profile could not be told from one saved empty on purpose"""
        mgr = _mock_manager([EMPTIED_PROFILE])

        CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID)

        writes = [entry for entry in mgr.mock_calls if entry[0] in ('delete_many', 'update_many_pull')]
        assert [entry[0] for entry in writes] == ['delete_many', 'update_many_pull']

    def test_an_emptied_profile_is_logged_by_name(self, caplog) -> None:
        """The deletion is logged at WARNING, naming the profile, since nobody asked for it"""
        mgr = _mock_manager([EMPTIED_PROFILE])

        with caplog.at_level(logging.WARNING):
            CiExplorerProfileManager._remove_id_from_filter(mgr, TYPES_FILTER_FIELD, TYPE_ID)

        assert EMPTIED_PROFILE['name'] in caplog.text

    @pytest.mark.parametrize('failing', ['find', 'delete_many', 'update_many_pull'])
    def test_wraps_any_failure_as_update_error(self, failing: str) -> None:
        """A failure of the lookup, the deletion or the pull surfaces as CiExplorerProfileManagerUpdateError"""
        mgr = _mock_manager([EMPTIED_PROFILE])
        getattr(mgr, failing).side_effect = RuntimeError('db down')

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

        mgr._remove_id_from_filter.return_value = [EMPTIED_PROFILE['public_id']]

        assert CiExplorerProfileManager.remove_type_from_profiles(mgr, TYPE_ID) == [EMPTIED_PROFILE['public_id']]

        mgr._remove_id_from_filter.assert_called_once_with(TYPES_FILTER_FIELD, TYPE_ID)


class TestRemoveRelationFromProfiles:
    """``remove_relation_from_profiles`` delegates to the shared helper on the 'relations_filter' field."""

    def test_delegates_with_relations_filter_field(self) -> None:
        """The public helper pulls the relation_id from the RELATIONS_FILTER_FIELD."""
        mgr = _mock_manager()

        mgr._remove_id_from_filter.return_value = []

        assert CiExplorerProfileManager.remove_relation_from_profiles(mgr, RELATION_ID) == []

        mgr._remove_id_from_filter.assert_called_once_with(RELATIONS_FILTER_FIELD, RELATION_ID)
