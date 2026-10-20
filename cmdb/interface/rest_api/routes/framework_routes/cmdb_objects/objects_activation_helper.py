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
The active state an object update may change, and how the change is recorded

``PUT /objects/state/<id>`` changes the active state behind its own right, ``base.framework.object.activation``. The
edit routes - the single and bulk ``PUT`` and the bulk ``PATCH`` - carry ``active`` in their body behind the edit
right, so they ask for the activation right as well, per target and only when that target's stored state would
change: re-sending the state an object already has needs the edit right alone. The check runs before the target is
written, so a bulk update refused on one target writes none (the request's ``WriteLedger`` undoes the earlier ones).

A change of the state through an edit route is recorded the way the state route records it: an ``ACTIVE_CHANGE``
entry with ``{'old': bool, 'new': bool}``, written beside the edit's own ``EDIT`` entry - the edit diff covers the
fields and the multi-data sections only
"""
from flask import abort

from cmdb.interface.route_utils import user_has_right
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject, ObjectChangeKey
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    ACTIVATION_RIGHT_MISSING_MESSAGE,
    ObjectLogComment,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    log_object_change,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import (
    ObjectWriteContext,
)
# -------------------------------------------------------------------------------------------------------------------- #


def context_has_right(context: ObjectWriteContext, right: str) -> bool:
    """
    Answers whether the update's caller holds a right, reading the caller's group at most once per right

    Args:
        context (ObjectWriteContext): The caller and the managers; its ``right_cache`` is extended in place
        right (str): The right to check

    Returns:
        bool: True when the caller's group holds the right (directly or through an extended right)
    """
    if right not in context.right_cache:
        context.right_cache[right] = user_has_right(right, context.request_user)

    return context.right_cache[right]


def guard_active_state_change(
        public_id: int,
        stored_active: bool,
        candidate_active: bool,
        context: ObjectWriteContext,
    ) -> None:
    """
    Refuses an update that changes an object's active state without the activation right

    Args:
        public_id (int): public_id of the CmdbObject being updated
        stored_active (bool): The active state as stored
        candidate_active (bool): The active state the update would write
        context (ObjectWriteContext): The caller and the managers

    Raises:
        HTTPException: 403 naming the right when the state changes and the caller lacks it
    """
    if stored_active == candidate_active:
        return

    right: str = ObjectRightName.ACTIVATION.value

    if not context_has_right(context, right):
        abort(403, ACTIVATION_RIGHT_MISSING_MESSAGE.format(public_id=public_id, right=right))


def log_active_state_change(context: ObjectWriteContext, before: CmdbObject, after: CmdbObject) -> None:
    """
    Writes the ``ACTIVE_CHANGE`` entry of an update that changed an object's active state, best-effort

    Nothing is written when the state is unchanged. The entry is the state route's: its comment, and the diff
    ``{'old': bool, 'new': bool}``; the object is rendered as it is after the update

    Args:
        context (ObjectWriteContext): The caller and the managers
        before (CmdbObject): The object as stored before the update
        after (CmdbObject): The object as read back after the update
    """
    if before.active == after.active:
        return

    log_object_change(
        context.request_user, context.logs_manager, LogAction.ACTIVE_CHANGE, after,
        ObjectLogComment.ACTIVE_CHANGED.value,
        changes={ObjectChangeKey.OLD.value: before.active, ObjectChangeKey.NEW.value: after.active},
    )
