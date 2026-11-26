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
The read-access check other routes run on a CmdbObject before they answer something ABOUT it

A route that serves data hanging off one object - its logs, its relation tabs - is as readable as the object
itself, and answers like ``GET /objects/<id>`` does: 403 when the caller's groups may not read the object's type.
Whether a missing object is refused is the caller's choice - the object's logs outlive it, its relations do not.

The write check (``abort_unless_write_allowed``) is the access engine's decision on the object itself: the Type of
each state the operation touches, and every field the write changes. The Field Rules run right after it
(``apply_object_field_rules``) - as the server, so nothing they write is judged against the writer
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager
from cmdb.framework.access_engine import AccessDecision, can, classes_of_fields, refusal_message
from cmdb.framework.field_rules import RuleApplication, run_field_rules
from cmdb.models.access_model import ScopeOperation
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

def read_object_or_abort(
    object_id: int,
    request_user: CmdbUser,
    objects_manager: ObjectsManager,
    denied_message: str,
    missing_message: str | None = None,
) -> dict[str, Any] | None:
    """
    Reads a CmdbObject through the caller's READ ACL, refusing an object the caller may not read

    Args:
        object_id (int): public_id of the CmdbObject
        request_user (CmdbUser): The caller
        objects_manager (ObjectsManager): Manager used to read the object through the caller's ACL
        denied_message (str): The message of the 403
        missing_message (str | None): The message of a 404 for an object that does not exist, or None to
            answer None for it instead. Defaults to None

    Raises:
        HTTPException: 403 when the object exists and the caller may not read it; 404 when it does not exist
            and a ``missing_message`` was given
        ObjectsManagerGetError: When reading the object failed

    Returns:
        dict[str, Any] | None: The object, or None when it does not exist and no ``missing_message`` was given
    """
    try:
        found: dict[str, Any] | None = objects_manager.get_object(
            object_id, request_user, AccessControlPermission.READ,
        )
    except AccessDeniedError:
        abort(403, denied_message)

    if found is None and missing_message is not None:
        abort(404, missing_message)

    return found


def abort_unless_write_allowed(request_user: CmdbUser, operation: ScopeOperation,
                               before: dict[str, Any] | None, after: dict[str, Any],
                               object_type: CmdbType | None = None) -> None:
    """
    Refuses an object create or edit the access engine does not allow - a Type the operation is not granted on, or a
    changed field the granting roles may not write

    Args:
        request_user (CmdbUser): The writer
        operation (ScopeOperation): CREATE or EDIT
        before (dict[str, Any] | None): The stored object; None for a create
        after (dict[str, Any]): The object as it would be stored
        object_type (CmdbType | None): The Type the object is stored as, when the caller holds it - its fields'
            classes are read from it instead of the database. Defaults to None

    Raises:
        HTTPException: 403 naming the refused fields or the Type
    """
    decision: AccessDecision = can(request_user, operation, before, after, field_classes=classes_of_fields(
        object_type.get_fields()) if object_type is not None else None)

    if not decision.allowed:
        abort(403, refusal_message(decision))


def apply_object_field_rules(request_user: CmdbUser, before: dict[str, Any] | None, after: dict[str, Any],
                             object_type: CmdbType) -> list[dict[str, Any]]:
    """
    Runs the active Field Rules on an object write that passed its write check - their values written into the state

    Args:
        request_user (CmdbUser): The writer
        before (dict[str, Any] | None): The stored object; None for a create
        after (dict[str, Any]): The object as it would be stored (changed in place)
        object_type (CmdbType): The Type the object is stored as

    Raises:
        HTTPException: 400 naming the rule whose value the field would refuse

    Returns:
        list[dict[str, Any]]: What the rules changed - the object log records it
    """
    application: RuleApplication = run_field_rules(request_user, before, after, object_type.get_fields() or [],
                                                   object_type.get_all_mds_fields())

    if application.problems:
        abort(400, ' '.join(application.problems))

    return application.changes
