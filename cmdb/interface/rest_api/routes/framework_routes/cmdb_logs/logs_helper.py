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
Helper methods shared by the CmdbLog REST routes

Holds the shared list assembly (`build_object_logs_response`, which every list endpoint routes its own
query through), the existence-split pipeline behind ``/logs/object/exists`` and ``/logs/object/notexists``
(`build_object_log_existence_query`) and the server-side user resolution behind ``?include_users=true``.

Every route answers a log in one shape, the model's (`serialize_object_log`), whether it was bound by a list or
read as a stored document.

It also holds the read rule every log route applies: **a log is read through the type ACL of the object it
records**, by the `type_id` the writer stamps on it - which is what still judges a log once its object is gone.
The lists pass the caller's READ ACL to the manager (the ACL stage then matches `type_id`), a single log is
judged by `is_log_readable` / `abort_unless_log_readable`, and the logs of an existing object the caller may not
read are refused like the object itself (`abort_unless_object_readable`).

NOTE the caller's ``filter`` collection parameter is NOT merged into the query here - it is parsed by
the route decorator and then ignored, which is a known gap, not a decision this helper makes on
purpose.
"""
from typing import Any, Union

from flask import Request, abort
from werkzeug import Response

from cmdb.manager import LogsManager, ObjectsManager, TypesManager, UsersManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.utils import Builder
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.security.acl.helpers import has_type_document_access
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.responses import GetMultiResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.errors.security import AccessDeniedError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LogKey,
    LogQueryOperator,
    LogResultKey,
    INCLUDE_USERS_PARAM,
    LOG_ACCESS_DENIED_MSG,
    OBJECT_LOGS_ACCESS_DENIED_MSG,
    MONGO_ID_KEY,
    OBJECT_LOOKUP_FIELD,
    OBJECT_LOOKUP_FIRST_MATCH,
    OBJECT_LOOKUP_MAX_MATCHES,
)
# -------------------------------------------------------------------------------------------------------------------- #


def build_object_log_existence_query(object_exists: bool = True) -> list[dict[str, Any]]:
    """
    Builds the pipeline selecting the object logs whose object still exists, or no longer exists

    Delete-action logs are left out on both sides. Only the existence of the referenced object
    matters, so the join caps at one id-only document instead of loading each full object, and the
    split is read straight off the joined array: element 0 is there exactly when the object is. The
    joined field is not part of a log, and `CmdbObjectLog.from_data` drops it when the rows are bound

    Args:
        object_exists (bool): True selects the logs whose object exists, False the ones whose
            object has been deleted

    Returns:
        list[dict[str, Any]]: The aggregation pipeline, passed as the criteria of a paged log read
    """
    return [
        Builder.match_({
            LogKey.LOG_TYPE.value: OBJECT_LOG_TYPE,
            LogKey.ACTION.value: {LogQueryOperator.NE.value: LogAction.DELETE.value},
        }),
        Builder.lookup_(
            from_collection=CmdbObject.COLLECTION,
            local_field=LogKey.OBJECT_ID.value,
            foreign_field=LogKey.PUBLIC_ID.value,
            as_field=OBJECT_LOOKUP_FIELD,
            pipeline=[
                Builder.limit_(OBJECT_LOOKUP_MAX_MATCHES),
                Builder.project_({MONGO_ID_KEY: 1}),
            ],
        ),
        Builder.match_({OBJECT_LOOKUP_FIRST_MATCH: {LogQueryOperator.EXISTS.value: object_exists}}),
    ]


def _include_users_requested(request: Request) -> bool:
    """Returns True when the request opted into embedded users via ``?include_users=true``."""
    return request.args.get(INCLUDE_USERS_PARAM, 'false').lower() == 'true'


def resolve_log_users(users_manager: UsersManager, logs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Resolves the distinct users referenced by a page of logs into a public_id-keyed map

    Collects the distinct ``user_id`` values from the given logs and fetches their minimal user
    projection in a single query. The map is keyed by the stringified user public_id so the frontend
    can map ``users[log.user_id]`` directly. Deleted users (a ``user_id`` with no matching user) are
    simply omitted; the log's own stored ``user_name`` remains the fallback.

    Args:
        users_manager (UsersManager): Manager used to fetch the minimal user projection
        logs (list[dict[str, Any]]): The serialized logs of the current page

    Returns:
        dict[str, dict[str, Any]]: Map of stringified public_id -> minimal user dict
    """
    user_ids = {log[LogKey.USER_ID.value] for log in logs if log.get(LogKey.USER_ID.value) is not None}

    if not user_ids:
        return {}

    users = users_manager.get_minimal_users_by_ids(list(user_ids))

    return {str(user[LogKey.PUBLIC_ID.value]): user for user in users}


def build_object_logs_response(logs_manager: LogsManager,
                               query: Union[dict[str, Any], list[dict[str, Any]]],
                               params: CollectionParameters,
                               request: Request,
                               request_user: CmdbUser) -> Response:
    """
    Runs an object-log query and wraps the matching logs in a paginated GetMultiResponse

    Shared by every CmdbLog list endpoint: each only differs by the ``query`` it passes, so the
    iterate -> serialize -> GetMultiResponse assembly lives here once. Every list is read through the
    caller's READ ACL: a log whose stamped type the caller may not read is neither returned nor counted.
    When the request sets ``?include_users=true`` the ``results`` payload becomes ``{logs, users}`` - the same paginated
    envelope (total/count/pager) with the referenced users resolved server-side under ``users`` so the
    frontend does not fetch each log's user separately. Without the flag the payload stays the plain
    list of logs (the default, preserved for API clients).

    Args:
        logs_manager (LogsManager): Manager used to iterate the logs collection
        query (dict[str, Any] | list[dict[str, Any]]): Match filter or aggregation pipeline
        params (CollectionParameters): Pagination/sort parameters from the request
        request (Request): Active request, used for the response URL and the include_users detection
        request_user (CmdbUser): User making the request - its READ ACL filters the logs, and it resolves the
            UsersManager

    Returns:
        Response: A GetMultiResponse; ``results`` is the log list, or ``{logs, users}`` when requested
    """
    builder_params = BuilderParameters(query, params.limit, params.skip, params.sort, params.order)

    # The type ACL stage matches the type each log is stamped with, ahead of the paging
    iteration_result = logs_manager.iterate(builder_params, request_user, AccessControlPermission.READ)
    logs = [serialize_object_log(log) for log in iteration_result.results]

    api_response = GetMultiResponse(logs,
                                    iteration_result.total,
                                    params,
                                    request.url,
                                    request_wants_body(request))

    # The response is built from the plain log LIST first, on purpose: GetMultiResponse derives `count`
    # from len(results) in its constructor, so wrapping the logs in {logs, users} before that point
    # would report the page size as 2 (the number of keys) instead of the number of logs
    if _include_users_requested(request):
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)
        api_response.results = {
            LogResultKey.LOGS.value: api_response.results,
            LogResultKey.USERS.value: resolve_log_users(users_manager, logs),
        }

    return api_response.make_response()


def is_log_readable(log: dict[str, Any], request_user: CmdbUser, types_manager: TypesManager) -> bool:
    """
    Decides whether the caller may read one log, by the type the log is stamped with

    The same decision the list routes' ACL stage makes: a log is hidden when its type's ACL denies the caller
    READ. A log without a type (one the backfill could not attribute) and a log whose type no longer exists are
    readable - the ACL stage lets them through as well, since it only excludes the types it denies

    Args:
        log (dict[str, Any]): The stored log document
        request_user (CmdbUser): The caller
        types_manager (TypesManager): Manager used to read the log's type

    Returns:
        bool: True when the caller may read the log
    """
    type_id: Any = log.get(LogKey.TYPE_ID.value)

    if type_id is None:
        return True

    log_type: dict[str, Any] | None = types_manager.get_type(type_id)

    if log_type is None:
        return True

    return has_type_document_access(log_type, request_user, AccessControlPermission.READ)


def abort_unless_log_readable(log: dict[str, Any], request_user: CmdbUser, types_manager: TypesManager) -> None:
    """
    Refuses a single-log read or delete the caller's type ACL does not grant

    Deleting a log is judged by READ as well: whoever may not see a history may not erase it either

    Args:
        log (dict[str, Any]): The stored log document
        request_user (CmdbUser): The caller
        types_manager (TypesManager): Manager used to read the log's type

    Raises:
        HTTPException: 403 when the caller may not read the log
    """
    if not is_log_readable(log, request_user, types_manager):
        abort(403, LOG_ACCESS_DENIED_MSG.format(public_id=log.get(LogKey.PUBLIC_ID.value)))


def abort_unless_object_readable(object_id: int, request_user: CmdbUser, objects_manager: ObjectsManager) -> None:
    """
    Refuses the logs of an existing object the caller may not read

    Answers like ``GET /objects/<id>`` does. An object that no longer exists is no refusal: its logs are judged
    one by one by the list's ACL stage, on the type each is stamped with

    Args:
        object_id (int): public_id of the object whose logs are requested
        request_user (CmdbUser): The caller
        objects_manager (ObjectsManager): Manager used to read the object through the caller's ACL

    Raises:
        HTTPException: 403 when the object exists and the caller may not read it
    """
    try:
        objects_manager.get_object(object_id, request_user, AccessControlPermission.READ)
    except AccessDeniedError:
        abort(403, OBJECT_LOGS_ACCESS_DENIED_MSG.format(object_id=object_id))


def serialize_object_log(log: CmdbObjectLog | dict[str, Any]) -> dict[str, Any]:
    """
    Answers a log in the one shape every log route sends: the model's

    A stored document goes through ``CmdbObjectLog.from_data`` first, so the single read answers exactly what a list
    row answers for the same log - a missing ``user_name`` reads ``'Unknown'``, a missing ``changes`` ``[]``, and a
    key the model does not declare is not passed on

    Args:
        log (CmdbObjectLog | dict[str, Any]): A bound log (the lists) or a stored log document (the single reads)

    Returns:
        dict[str, Any]: The serialized log
    """
    if isinstance(log, dict):
        log = CmdbObjectLog.from_data(log)

    return CmdbObjectLog.to_json(log)
