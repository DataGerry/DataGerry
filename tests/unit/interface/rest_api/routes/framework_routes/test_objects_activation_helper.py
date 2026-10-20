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
Unit tests for objects_activation_helper: the activation right an update needs when it changes an Object's active
state, the per-request right cache, and the ACTIVE_CHANGE entry the change is recorded with

DB-free: ``user_has_right`` and ``log_object_change`` are patched where the helper reads them
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import Forbidden

from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_activation_helper import (
    context_has_right,
    guard_active_state_change,
    log_active_state_change,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    ACTIVATION_RIGHT_MISSING_MESSAGE,
    ObjectLogComment,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import ObjectWriteContext
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.right_model.right_constants import ObjectRightName
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_activation_helper'
OBJECT_ID: int = 42
OTHER_RIGHT: str = 'base.framework.object.edit'


def _context() -> ObjectWriteContext:
    """A context whose managers are mocks and whose caches start empty."""
    return ObjectWriteContext(SimpleNamespace(public_id=7), MagicMock(), MagicMock(), MagicMock())


def _object(active: bool) -> SimpleNamespace:
    """Stands in for a CmdbObject: only the active flag is read."""
    return SimpleNamespace(active=active)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  context_has_right                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestContextHasRight:
    """One group read per right and request, however many targets ask."""

    @pytest.mark.parametrize('held', [True, False])
    def test_the_answer_is_the_right_check_and_is_cached(self, held: bool) -> None:
        """Asked twice, the group is read once; the answer is the check's"""
        context = _context()

        with patch(f'{HELPER_PATH}.user_has_right', return_value=held) as check:
            assert context_has_right(context, ObjectRightName.ACTIVATION.value) is held
            assert context_has_right(context, ObjectRightName.ACTIVATION.value) is held

        check.assert_called_once_with(ObjectRightName.ACTIVATION.value, context.request_user)
        assert context.right_cache == {ObjectRightName.ACTIVATION.value: held}

    def test_each_right_is_cached_on_its_own(self) -> None:
        """A second right is checked, not answered from the first one's entry"""
        context = _context()

        with patch(f'{HELPER_PATH}.user_has_right', side_effect=[True, False]) as check:
            assert context_has_right(context, ObjectRightName.ACTIVATION.value) is True
            assert context_has_right(context, OTHER_RIGHT) is False

        assert check.call_count == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_active_state_change                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGuardActiveStateChange:
    """The activation right is asked only when the state would change."""

    @pytest.mark.parametrize('state', [True, False])
    def test_an_unchanged_state_asks_no_right(self, state: bool) -> None:
        """Re-sending the stored state needs the edit right alone"""
        with patch(f'{HELPER_PATH}.user_has_right') as check:
            guard_active_state_change(OBJECT_ID, state, state, _context())

        check.assert_not_called()

    @pytest.mark.parametrize('stored, candidate', [(True, False), (False, True)])
    def test_a_change_with_the_right_passes(self, stored: bool, candidate: bool) -> None:
        """Both directions are judged the same way"""
        with patch(f'{HELPER_PATH}.user_has_right', return_value=True) as check:
            guard_active_state_change(OBJECT_ID, stored, candidate, _context())

        check.assert_called_once()
        assert check.call_args.args[0] == ObjectRightName.ACTIVATION.value

    @pytest.mark.parametrize('stored, candidate', [(True, False), (False, True)])
    def test_a_change_without_the_right_is_a_403_naming_it(self, stored: bool, candidate: bool) -> None:
        """The message names the object and the missing right"""
        with patch(f'{HELPER_PATH}.user_has_right', return_value=False):
            with pytest.raises(Forbidden) as refused:
                guard_active_state_change(OBJECT_ID, stored, candidate, _context())

        assert refused.value.description == ACTIVATION_RIGHT_MISSING_MESSAGE.format(
            public_id=OBJECT_ID, right=ObjectRightName.ACTIVATION.value,
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                               log_active_state_change                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLogActiveStateChange:
    """The state route's entry, written only for a real change."""

    @pytest.mark.parametrize('state', [True, False])
    def test_an_unchanged_state_writes_nothing(self, state: bool) -> None:
        """No entry when the flag stayed"""
        with patch(f'{HELPER_PATH}.log_object_change') as log:
            log_active_state_change(_context(), _object(state), _object(state))

        log.assert_not_called()

    @pytest.mark.parametrize('before, after', [(True, False), (False, True)])
    def test_a_change_writes_the_active_change_entry(self, before: bool, after: bool) -> None:
        """ACTIVE_CHANGE, the state route's comment, {old, new}, the object as read back"""
        context = _context()
        after_object: Any = _object(after)

        with patch(f'{HELPER_PATH}.log_object_change') as log:
            log_active_state_change(context, _object(before), after_object)

        log.assert_called_once_with(
            context.request_user, context.logs_manager, LogAction.ACTIVE_CHANGE, after_object,
            ObjectLogComment.ACTIVE_CHANGED.value, changes={'old': before, 'new': after},
        )
