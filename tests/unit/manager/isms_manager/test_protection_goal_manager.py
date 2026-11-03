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
Unit tests for cmdb.manager.isms_manager.protection_goal_manager.ProtectionGoalManager.find_name_holder

Pure tests: no Mongo. The method is driven against a ``MagicMock(spec=ProtectionGoalManager)`` with ``get_one_by``
stubbed: the exact-name read, the holder's public_id or None, and a failed read wrapped as the name-check error with
the base error kept as its cause. The read against real MongoDB is in the integration tier.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.protection_goal_manager import ProtectionGoalManagerNameCheckError
# -------------------------------------------------------------------------------------------------------------------- #

HOLDER_ID: int = 311
NAME: str = 'Authenticity'


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a ProtectionGoalManager instance"""
    return MagicMock(spec=ProtectionGoalManager)


class TestFindNameHolder:
    """``find_name_holder`` answers which goal holds a name"""

    def test_answers_the_holders_public_id(self) -> None:
        """Read by the exact name"""
        manager = _mock_manager()
        manager.get_one_by.return_value = {'public_id': HOLDER_ID, 'name': NAME}

        assert ProtectionGoalManager.find_name_holder(manager, NAME) == HOLDER_ID
        manager.get_one_by.assert_called_once_with({'name': NAME})

    def test_answers_none_for_a_free_name(self) -> None:
        """Nobody holds it"""
        manager = _mock_manager()
        manager.get_one_by.return_value = None

        assert ProtectionGoalManager.find_name_holder(manager, NAME) is None

    def test_a_failed_read_is_the_name_check_error(self) -> None:
        """Its own class, so the routes can answer it with its own 400 - the cause is kept"""
        manager = _mock_manager()
        failure = BaseManagerGetError('read failed')
        manager.get_one_by.side_effect = failure

        with pytest.raises(ProtectionGoalManagerNameCheckError) as exc_info:
            ProtectionGoalManager.find_name_holder(manager, NAME)

        assert exc_info.value.args[0] is failure

    def test_a_bug_is_not_wrapped(self) -> None:
        """Only the read's own error is caught"""
        manager = _mock_manager()
        manager.get_one_by.side_effect = KeyError('bug')

        with pytest.raises(KeyError):
            ProtectionGoalManager.find_name_holder(manager, NAME)
