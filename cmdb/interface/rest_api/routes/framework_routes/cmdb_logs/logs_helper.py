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
query through), the existence split behind ``/logs/object/exists`` and ``/logs/object/notexists``
(`build_object_log_existence_query`) and the server-side user resolution behind ``?include_users=true``.

The existence split decides existence once per object, not once per log: one aggregation lists the object ids the
logs name that no object carries any more (`read_deleted_object_ids`), and the page is a plain filter on that list
(`build_object_log_existence_filter`), so the page and its count read no other collection. Past
``MAX_DELETED_OBJECT_IDS`` ids it falls back to joining every log to its object (`build_object_log_existence_join`).

Every route answers a log in one shape, the model's (`serialize_object_log`), whether it was bound by a list or
read as a stored document.

It also holds the read rule every log route applies: **a log is read through the type ACL of the object it
records**, by the `type_id` the writer stamps on it - which is what still judges a log once its object is gone.
The lists pass the caller's READ ACL to the manager (the ACL stage then matches `type_id`), a single log is
judged by `is_log_readable` / `abort_unless_log_readable`, and the logs of an existing object the caller may not
read are refused like the object itself (`objects_access_helper.read_object_or_abort`).

NOTE the caller's ``filter`` collection parameter is NOT merged into the query here - it is parsed by
the route decorator and then ignored, which is a known gap, not a decision this helper makes on
purpose.
"""
from logging import Logger, getLogger
from typing import Any, Union

from flask import Request, abort
from werkzeug import Response

from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.manager import LogsManager, TypesManager, UsersManager
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
from cmdb.interface.rest_api.routes.routes_helper import read_boolean_value, request_wants_body
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LogKey,
    LogQueryOperator,
    LogResultKey,
    INCLUDE_USERS_PARAM,
    LOG_ACCESS_DENIED_MSG,
    MAX_DELETED_OBJECT_IDS,
    MONGO_ID_KEY,
    OBJECT_LOOKUP_FIELD,
    OBJECT_LOOKUP_FIRST_MATCH,
    OBJECT_LOOKUP_MAX_MATCHES,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def object_entry_actions() -> list[int]:
    """
    The log actions an object's own history consists of: every LogAction except DELETE

    Derived from the enum, so an action added later joins the existence split without a change here

    Returns:
        list[int]: The stored values of every LogAction but DELETE, in enum order
    """
    return [action.value for action in LogAction if action is not LogAction.DELETE]


def _object_log_entry_condition() -> dict[str, Any]:
    """
    The condition both sides of the existence split start from: object logs that are not deletes

    A delete log has no object by construction, so it would land on the "deleted" side every time; it has its own
    list (``/logs/object/deleted``) instead.

    ``action`` is an ``$in`` of the remaining actions, not ``$ne`` DELETE. Both mean the same for every stored log
    (a log always carries one of the enum's actions), but only ``$in`` lets MongoDB read a ``log_time`` page off the
    ``(log_type, action, log_time)`` index - each listed action is one ordered run of that index, merged in order -
    while ``$ne`` keeps a sort of every matching log in memory before the page is cut

    Returns:
        dict[str, Any]: The filter document
    """
    return {
        LogKey.LOG_TYPE.value: OBJECT_LOG_TYPE,
        LogKey.ACTION.value: {LogQueryOperator.IN.value: object_entry_actions()},
    }


def _object_existence_lookup(local_field: str) -> dict[str, Any]:
    """
    The `$lookup` deciding whether the object a value names exists

    Only existence matters, so the join caps at one id-only document instead of loading the full object; the
    equality match on ``public_id`` stays index-backed

    Args:
        local_field (str): The field holding the object id on the documents entering the stage

    Returns:
        dict[str, Any]: The `$lookup` stage, joined under ``OBJECT_LOOKUP_FIELD``
    """
    return Builder.lookup_(
        from_collection=CmdbObject.COLLECTION,
        local_field=local_field,
        foreign_field=LogKey.PUBLIC_ID.value,
        as_field=OBJECT_LOOKUP_FIELD,
        pipeline=[
            Builder.limit_(OBJECT_LOOKUP_MAX_MATCHES),
            Builder.project_({MONGO_ID_KEY: 1}),
        ],
    )


def build_deleted_object_ids_pipeline() -> list[dict[str, Any]]:
    """
    Builds the pipeline listing the object ids the logs name that no object carries any more

    Groups the logs by ``object_id`` first, so the join to ``framework.objects`` runs once per object and not once
    per log. The grouping has no filter on purpose: unfiltered, MongoDB reads it off the
    ``object_id_log_time_public_id`` index (a DISTINCT_SCAN, one index key per object) without loading a log. An id
    that only a delete log or another log type names costs one extra join and changes nothing, since the page query
    filters those logs out itself.
    A log without an ``object_id`` groups under ``None``, which no object carries - so it is "deleted", as the per-log
    join decides too

    The last stage reads one row past ``MAX_DELETED_OBJECT_IDS``, so a caller can tell the list was cut without
    reading every row

    Returns:
        list[dict[str, Any]]: The aggregation pipeline over the logs collection; each row is ``{_id: <object id>}``
    """
    return [
        Builder.group_(f'${LogKey.OBJECT_ID.value}'),
        _object_existence_lookup(MONGO_ID_KEY),
        Builder.match_({OBJECT_LOOKUP_FIRST_MATCH: {LogQueryOperator.EXISTS.value: False}}),
        Builder.project_({MONGO_ID_KEY: 1}),
        Builder.limit_(MAX_DELETED_OBJECT_IDS + 1),
    ]


def read_deleted_object_ids(logs_manager: LogsManager) -> list[Any] | None:
    """
    Reads the object ids the logs name that no object carries any more

    Runs under the query time budget of a page read, so a read that outgrows it answers like a slow page does

    Args:
        logs_manager (LogsManager): Manager used to aggregate the logs collection

    Raises:
        BaseManagerIterationError: If the aggregation fails or runs past its time budget

    Returns:
        list[Any] | None: The deleted object ids, or None when there are more than ``MAX_DELETED_OBJECT_IDS``
    """
    rows: list[dict[str, Any]] = logs_manager.aggregate_within_time_limit(
        build_deleted_object_ids_pipeline(), QUERY_TIME_LIMIT_MS,
    )

    if len(rows) > MAX_DELETED_OBJECT_IDS:
        return None

    return [row[MONGO_ID_KEY] for row in rows]


def build_object_log_existence_filter(deleted_object_ids: list[Any], object_exists: bool) -> dict[str, Any]:
    """
    Builds the filter selecting one side of the existence split from the deleted object ids

    A plain filter, so the page and its count are ordinary indexed reads of the logs collection: no log is joined.
    An empty list puts every object log on the "exists" side and none on the other

    Args:
        deleted_object_ids (list[Any]): The object ids no object carries any more (``read_deleted_object_ids``)
        object_exists (bool): True selects the logs whose object exists, False the ones whose object is gone

    Returns:
        dict[str, Any]: The filter document
    """
    operator: LogQueryOperator = LogQueryOperator.NIN if object_exists else LogQueryOperator.IN

    return {
        **_object_log_entry_condition(),
        LogKey.OBJECT_ID.value: {operator.value: deleted_object_ids},
    }


def build_object_log_existence_join(object_exists: bool) -> list[dict[str, Any]]:
    """
    Builds the pipeline selecting one side of the existence split by joining every log to its object

    The fallback for a history whose deleted object ids are too many to send as a list: correct at any size, but the
    join runs once per object log, ahead of the paging, and again for the count. The joined field is not part of a
    log, and `CmdbObjectLog.from_data` drops it when the rows are bound

    Args:
        object_exists (bool): True selects the logs whose object exists, False the ones whose object is gone

    Returns:
        list[dict[str, Any]]: The aggregation pipeline
    """
    return [
        Builder.match_(_object_log_entry_condition()),
        _object_existence_lookup(LogKey.OBJECT_ID.value),
        Builder.match_({OBJECT_LOOKUP_FIRST_MATCH: {LogQueryOperator.EXISTS.value: object_exists}}),
    ]


def build_object_log_existence_query(logs_manager: LogsManager,
                                     object_exists: bool = True) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Builds the criteria selecting the object logs whose object still exists, or no longer exists

    Decides existence once per object (``read_deleted_object_ids``) and pages the logs with a plain filter on that
    list. When the list would be too long for one command it falls back to joining every log to its object
    (``build_object_log_existence_join``), which answers the same rows. Delete-action logs are left out on both sides

    Args:
        logs_manager (LogsManager): Manager used to read the deleted object ids
        object_exists (bool): True selects the logs whose object exists, False the ones whose object has been
            deleted

    Raises:
        BaseManagerIterationError: If reading the deleted object ids fails or runs past its time budget

    Returns:
        dict[str, Any] | list[dict[str, Any]]: The criteria of a paged log read - a filter, or the fallback pipeline
    """
    deleted_object_ids: list[Any] | None = read_deleted_object_ids(logs_manager)

    if deleted_object_ids is None:
        LOGGER.warning("[build_object_log_existence_query] More than %s deleted object ids - joining every log",
                       MAX_DELETED_OBJECT_IDS)
        return build_object_log_existence_join(object_exists)

    return build_object_log_existence_filter(deleted_object_ids, object_exists)


def _include_users_requested(request: Request) -> bool:
    """
    Whether the request opted into embedded users (``?include_users=true``)

    By the API's one rule for flags (``read_boolean_value``), read off the request the response is built for

    Args:
        request (Request): The request being answered

    Raises:
        HTTPException: 400 when the flag is neither true nor false

    Returns:
        bool: The flag; False when absent
    """
    return read_boolean_value(INCLUDE_USERS_PARAM, request.args.get(INCLUDE_USERS_PARAM), default=False)


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
        request (Request): Active request, used for the response URL and the include_users flag
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
