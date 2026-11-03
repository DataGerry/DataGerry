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
Unit tests for protection_goal_helper: the name rule of the ProtectionGoal writes

Driven against MagicMock managers: the name pre-check (another goal's name refused, the goal's own name kept, a
failed read raised for the route's table), and the two writes answering a unique-index refusal with the same 400
while every other write failure is re-raised unchanged.
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.errors.database import DocumentDuplicateKeyError, DocumentTooLargeError
from cmdb.interface.request_limits_constants import DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE
from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerInsertError,
    ProtectionGoalManagerNameCheckError,
    ProtectionGoalManagerUpdateError,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import PROTECTION_GOAL_NAME_TAKEN_MSG
from cmdb.interface.rest_api.routes.isms_routes.protection_goal_helper import (
    abort_if_protection_goal_name_taken,
    insert_protection_goal,
    update_protection_goal,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.isms_routes.protection_goal_helper'
GOAL_ID: int = 41
OTHER_GOAL_ID: int = 42
NEW_GOAL_ID: int = 43
NAME: str = 'Authenticity'
DATA: dict[str, Any] = {'public_id': GOAL_ID, 'name': NAME, 'predefined': False}
STORED: dict[str, Any] = {'public_id': GOAL_ID, 'name': NAME, 'predefined': False}


def _holding(holder: int | None) -> MagicMock:
    """A manager whose name read answers ``holder``"""
    manager = MagicMock()
    manager.find_name_holder.return_value = holder
    return manager


def _taken(exc_info: Any) -> None:
    """The name rule's 400"""
    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=NAME)


class TestTheNamePreCheck:
    """abort_if_protection_goal_name_taken"""

    def test_a_free_name_passes(self) -> None:
        """Nobody holds it"""
        manager = _holding(None)

        abort_if_protection_goal_name_taken(manager, NAME)

        manager.find_name_holder.assert_called_once_with(NAME)

    def test_another_goals_name_is_a_400(self) -> None:
        """On a create"""
        with pytest.raises(HTTPException) as exc_info:
            abort_if_protection_goal_name_taken(_holding(OTHER_GOAL_ID), NAME)

        _taken(exc_info)

    def test_an_update_keeps_its_own_name(self) -> None:
        """The holder is the goal being updated"""
        abort_if_protection_goal_name_taken(_holding(GOAL_ID), NAME, GOAL_ID)

    def test_an_update_to_a_free_name_passes(self) -> None:
        """A rename nobody blocks"""
        abort_if_protection_goal_name_taken(_holding(None), NAME, GOAL_ID)

    def test_an_update_to_another_goals_name_is_a_400(self) -> None:
        """The holder is someone else"""
        with pytest.raises(HTTPException) as exc_info:
            abort_if_protection_goal_name_taken(_holding(OTHER_GOAL_ID), NAME, GOAL_ID)

        _taken(exc_info)

    def test_a_failed_read_is_raised_for_the_routes_table(self) -> None:
        """The route maps it to NAME_CHECK"""
        manager = MagicMock()
        manager.find_name_holder.side_effect = ProtectionGoalManagerNameCheckError('read failed')

        with pytest.raises(ProtectionGoalManagerNameCheckError):
            abort_if_protection_goal_name_taken(manager, NAME)


def _caused_by(error_class: type[Exception], cause_class: type[Exception]) -> Exception:
    """A manager write error caused by a database error of ``cause_class``"""
    try:
        try:
            raise cause_class('database refused the write')
        except cause_class as cause:
            raise error_class(cause) from cause
    except error_class as err:
        return err


def _duplicate(error_class: type[Exception]) -> Exception:
    """A manager write error caused by a unique-index refusal"""
    return _caused_by(error_class, DocumentDuplicateKeyError)


def _too_large(exc_info: Any) -> None:
    """The size limit's 400"""
    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE


class TestTheInsert:
    """insert_protection_goal"""

    def test_answers_the_new_id(self) -> None:
        """The ordinary case"""
        manager = MagicMock()
        manager.insert_item.return_value = NEW_GOAL_ID

        assert insert_protection_goal(manager, DATA) == NEW_GOAL_ID
        manager.insert_item.assert_called_once_with(DATA)

    def test_a_lost_race_is_the_name_rules_400(self) -> None:
        """The unique index refused the name a concurrent write took first"""
        manager = MagicMock()
        manager.insert_item.side_effect = _duplicate(ProtectionGoalManagerInsertError)

        with pytest.raises(HTTPException) as exc_info:
            insert_protection_goal(manager, DATA)

        _taken(exc_info)

    def test_a_document_over_the_size_limit_is_the_size_400(self) -> None:
        """Answered before the duplicate check, like every write arm"""
        manager = MagicMock()
        manager.insert_item.side_effect = _caused_by(ProtectionGoalManagerInsertError, DocumentTooLargeError)

        with pytest.raises(HTTPException) as exc_info:
            insert_protection_goal(manager, DATA)

        _too_large(exc_info)

    def test_any_other_insert_failure_is_re_raised(self) -> None:
        """For the route's INSERT 400"""
        manager = MagicMock()
        failure = ProtectionGoalManagerInsertError('insert failed')
        manager.insert_item.side_effect = failure

        with pytest.raises(ProtectionGoalManagerInsertError) as exc_info:
            insert_protection_goal(manager, DATA)

        assert exc_info.value is failure


class TestTheUpdate:
    """update_protection_goal"""

    def test_answers_the_stored_document(self) -> None:
        """Through update_item_from_payload"""
        manager = MagicMock()

        with patch(f'{HELPER_PATH}.update_item_from_payload', return_value=STORED) as update:
            assert update_protection_goal(manager, GOAL_ID, DATA) == STORED

        assert update.call_args.args[0] is manager
        assert update.call_args.args[1] == GOAL_ID

    def test_a_lost_race_is_the_name_rules_400(self) -> None:
        """A rename onto a name a concurrent write took first"""
        with patch(f'{HELPER_PATH}.update_item_from_payload',
                   side_effect=_duplicate(ProtectionGoalManagerUpdateError)), \
             pytest.raises(HTTPException) as exc_info:
            update_protection_goal(MagicMock(), GOAL_ID, DATA)

        _taken(exc_info)

    def test_a_document_over_the_size_limit_is_the_size_400(self) -> None:
        """Answered before the duplicate check, like every write arm"""
        with patch(f'{HELPER_PATH}.update_item_from_payload',
                   side_effect=_caused_by(ProtectionGoalManagerUpdateError, DocumentTooLargeError)), \
             pytest.raises(HTTPException) as exc_info:
            update_protection_goal(MagicMock(), GOAL_ID, DATA)

        _too_large(exc_info)

    def test_any_other_update_failure_is_re_raised(self) -> None:
        """For the route's UPDATE 400"""
        failure = ProtectionGoalManagerUpdateError('update failed')

        with patch(f'{HELPER_PATH}.update_item_from_payload', side_effect=failure), \
             pytest.raises(ProtectionGoalManagerUpdateError) as exc_info:
            update_protection_goal(MagicMock(), GOAL_ID, DATA)

        assert exc_info.value is failure
