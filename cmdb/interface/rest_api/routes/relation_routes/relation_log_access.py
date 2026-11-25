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
Who may read a CmdbObjectRelationLog: it is as readable as the relation it records, judged by the relation's two type
ids stamped on it

History outlives what it records - a log may name a Type that no longer exists, or none at all. The caller's denial is
read as the access engine holds it (``resolve_denied_types``), so such a log is judged like an object of a gone Type:
readable while not every Type is restricted, denied when every Type is (a role on every Type assigned). The list
narrows by ``readable_log_condition`` (``access_engine.id_criteria`` on both stamped keys), a single read and the
delete by ``read_object_relation_log_or_abort`` - one rule for both, no Type or object read
"""
from http import HTTPStatus
from typing import Any

from flask import abort

from cmdb.manager import ObjectRelationLogsManager
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import DeniedTypes, id_criteria
from cmdb.security.acl.builder import resolve_denied_types
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE,
)

from cmdb.errors.manager import BaseManagerGetError, BaseManagerInitError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'read_log_denial_or_abort',
    'readable_log_condition',
    'is_log_readable',
    'read_object_relation_log_or_abort',
]

# The two stamped keys a relation log is judged by
STAMPED_TYPE_KEYS: tuple[str, str] = (ObjectRelationKey.RELATION_PARENT_TYPE_ID.value,
                                      ObjectRelationKey.RELATION_CHILD_TYPE_ID.value)


def read_log_denial_or_abort(request_user: CmdbUser) -> DeniedTypes:
    """
    Reads the caller's READ denial, the input of every relation-log read rule

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 when the caller's grants could not be read

    Returns:
        DeniedTypes: The denial
    """
    try:
        return resolve_denied_types(request_user, AccessControlPermission.READ)
    except (BaseManagerGetError, BaseManagerInitError):
        abort(400, OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE)


def readable_log_condition(denied: DeniedTypes) -> dict[str, Any]:
    """
    The condition keeping only the logs whose two stamped types the caller may read

    Args:
        denied (DeniedTypes): The caller's denial

    Returns:
        dict[str, Any]: The condition - ``$nin`` the denied Types on both keys, or ``$in`` the admitted ones when every
            Type is restricted (a log stamped with a gone Type or none is then out); empty when nothing is denied
    """
    condition: dict[str, Any] = {}

    for key in STAMPED_TYPE_KEYS:
        condition.update(id_criteria(key, denied))

    return condition


def is_log_readable(object_relation_log: dict[str, Any], denied: DeniedTypes) -> bool:
    """
    Judges one stored log by its two stamped types - the single-document twin of ``readable_log_condition``

    Args:
        object_relation_log (dict[str, Any]): The stored CmdbObjectRelationLog
        denied (DeniedTypes): The caller's denial

    Returns:
        bool: True when neither side's type is denied
    """
    return not any(denied.denies(object_relation_log.get(key)) for key in STAMPED_TYPE_KEYS)


def read_object_relation_log_or_abort(object_relation_logs_manager: ObjectRelationLogsManager, public_id: int,
                                      denied: DeniedTypes) -> dict[str, Any]:
    """
    Reads a stored CmdbObjectRelationLog the caller addresses by id, refusing one it may not read - the entry of the
    log read and the log delete

    Args:
        object_relation_logs_manager (ObjectRelationLogsManager): Manager reading the CmdbObjectRelationLog
        public_id (int): public_id of the CmdbObjectRelationLog
        denied (DeniedTypes): The caller's denial

    Raises:
        werkzeug.exceptions.NotFound: Aborts with 404 when no such CmdbObjectRelationLog exists
        werkzeug.exceptions.Forbidden: Aborts with 403 when the caller may not read one of its two stamped types
        ObjectRelationLogsManagerGetError: When the read fails

    Returns:
        dict[str, Any]: The stored CmdbObjectRelationLog
    """
    object_relation_log: dict[str, Any] | None = object_relation_logs_manager.get_object_relation_log(public_id)

    if not object_relation_log:
        abort(HTTPStatus.NOT_FOUND, OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE.format(public_id=public_id))

    if not is_log_readable(object_relation_log, denied):
        abort(HTTPStatus.FORBIDDEN, OBJECT_RELATION_LOG_ACCESS_DENIED_MESSAGE.format(public_id=public_id))

    return object_relation_log
