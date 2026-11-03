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
The writes of IsmsProtectionGoals that carry the name rule

A ProtectionGoal's name is unique, compared exactly as sent. ``abort_if_protection_goal_name_taken`` reads which goal
holds the name, which answers the ordinary case; the unique index on ``name`` (``IsmsProtectionGoal.INDEX_KEYS``) is
what holds when two writes race, and ``insert_protection_goal`` / ``update_protection_goal`` answer its refusal with
the same 400 (``abort_if_duplicate``), after a document over MongoDB's size limit has had its own 400
(``abort_if_too_large``). Everything else a write raises is re-raised for the route's error table.
"""
from typing import Any

from flask import abort

from cmdb.manager import ProtectionGoalManager
from cmdb.models.isms_model import IsmsProtectionGoal
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.errors.manager.protection_goal_manager import (
    ProtectionGoalManagerInsertError,
    ProtectionGoalManagerUpdateError,
)
from cmdb.interface.route_utils import abort_if_too_large
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import PROTECTION_GOAL_NAME_TAKEN_MSG
from cmdb.interface.rest_api.routes.routes_helper import abort_if_duplicate, update_item_from_payload
# -------------------------------------------------------------------------------------------------------------------- #


def abort_if_protection_goal_name_taken(
        protection_goal_manager: ProtectionGoalManager,
        name: str,
        exclude_id: int | None = None) -> None:
    """
    Refuses a write whose name another IsmsProtectionGoal already holds

    The readable half of the uniqueness rule; the unique index on ``name`` holds under concurrency

    Args:
        protection_goal_manager (ProtectionGoalManager): Manager of the ProtectionGoals
        name (str): The name the write would store
        exclude_id (int | None): public_id of the goal being updated, which may keep its own name. Defaults to None

    Raises:
        ProtectionGoalManagerNameCheckError: If the name read failed
        HTTPException: 400 when another IsmsProtectionGoal holds the name
    """
    holder: int | None = protection_goal_manager.find_name_holder(name)

    if holder is not None and holder != exclude_id:
        abort(400, PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=name))


def insert_protection_goal(protection_goal_manager: ProtectionGoalManager, data: dict[str, Any]) -> int:
    """
    Inserts an IsmsProtectionGoal, answering a lost name race with the name rule's 400

    Args:
        protection_goal_manager (ProtectionGoalManager): Manager of the ProtectionGoals
        data (dict[str, Any]): The validated ProtectionGoal

    Raises:
        HTTPException: 400 when the document is too large, or the unique index refused the name
        ProtectionGoalManagerInsertError: If the insert failed for any other reason

    Returns:
        int: The public_id of the new ProtectionGoal
    """
    try:
        return protection_goal_manager.insert_item(data)
    except ProtectionGoalManagerInsertError as err:
        abort_if_too_large(err)
        abort_if_duplicate(err, PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=data[ProtectionGoalKey.NAME.value]))


def update_protection_goal(
        protection_goal_manager: ProtectionGoalManager,
        public_id: int,
        data: dict[str, Any]) -> dict[str, Any]:
    """
    Updates an IsmsProtectionGoal, answering a lost name race with the name rule's 400

    Args:
        protection_goal_manager (ProtectionGoalManager): Manager of the ProtectionGoals
        public_id (int): public_id of the ProtectionGoal, taken from the URL
        data (dict[str, Any]): The validated, identity-pinned ProtectionGoal

    Raises:
        HTTPException: 400 when the document is too large, or the unique index refused the name
        ProtectionGoalManagerUpdateError: If the update failed for any other reason

    Returns:
        dict[str, Any]: The document as stored (``update_item_from_payload``)
    """
    try:
        return update_item_from_payload(protection_goal_manager, public_id, IsmsProtectionGoal, data)
    except ProtectionGoalManagerUpdateError as err:
        abort_if_too_large(err)
        abort_if_duplicate(err, PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=data[ProtectionGoalKey.NAME.value]))
