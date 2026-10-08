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
Implementation of all API routes for CmdbObjectRelations

A CmdbObjectRelation is one concrete relation instance between two CmdbObjects, typed by the
CmdbRelation it references. The routes fall into three groups:

    - CRUD over single instances (`/`, `/<public_id>`) plus the bulk delete (`/delete/many`)
    - the relation-tab routes (`/tabs/<object_id>` and `/tabs/<object_id>/instances`), which serve one
      CmdbObject's relation tabs without loading every instance: the first returns the tab descriptors
      (one per relation definition and role, with its instance count), the second one page of a single
      tab with the counterpart object resolved per row
    - nothing else - the CmdbRelation definitions themselves live in `relations_routes`

Every read route asks for `base.framework.objectRelation.view`, and every read answers a CmdbObjectRelation only
when the caller may read BOTH of its objects, judged by the type ids stamped on it: the lists and the tabs leave
the others out of their rows and their totals, and a single read refuses one with a 403. The relation tabs of an
object are moreover as readable as the object itself - 403 when the caller may not read it, 404 when it does not
exist

Two invariants the write routes enforce, both of them server-side only:

    - the referenced CmdbRelation must still exist, and the two endpoints must be different CmdbObjects
      (a CmdbObject is never related to itself)
    - `author_id`, `creation_time` and `last_edit_time` are owned by the server, and a value sent for
      any of them is overwritten rather than trusted. A create stamps the author and the creation time
      and clears `last_edit_time` (a relation that has never been edited has no edit time); an update
      preserves the stored creation time, records the editing user as `author_id` (the field doubles as
      "who last touched this" - a CmdbObjectRelation has no separate editor field) and stamps
      `last_edit_time`. Left to the body by the create route, a
      client could claim - and backdate - an edit that never happened, and the `{'$date': ...}` wrapper
      it sent was stored as a sub-document MongoDB cannot sort or range-filter

Every write also writes its history through the ObjectRelationLogsManager. That is best-effort and
always happens AFTER the write, so a failed write can never leave a log claiming a change that did not
happen, and a failed log can never fail the request (see the log helpers in `relations_helper`)
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import request, abort
from werkzeug import Response

from cmdb.manager import ObjectRelationsManager, ObjectRelationLogsManager, RelationsManager, ObjectsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey, ObjectRelationRole
from cmdb.models.log_model import LogInteraction

from cmdb.framework.results import IterationResult

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    abort_if_query_too_slow,
    abort_if_too_large,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
    DefaultResponse,
)

from cmdb.interface.rest_api.routes.routes_helper import request_wants_body, pin_public_id
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    DEFAULT_TAB_PAGE_SIZE,
    MAX_TAB_PAGE_SIZE,
    SORT_DIRECTIONS,
    TAB_SORT_KEYS,
    TAB_SORT_KEY_INVALID_MESSAGE,
    OBJECT_RELATION_ACCESS_DENIED_MESSAGE,
    ObjectRelationRight,
    ObjectRelationTabParam,
    TabInstancesKey,
    OBJECT_RELATION_BULK_DELETE_FAILED_MESSAGE,
    OBJECT_RELATION_BULK_NONE_EXIST_MESSAGE,
    OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE,
)
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    get_existing_relation_or_abort,
    guard_object_relation_field_values,
    is_object_relation_readable,
    read_tab_object_or_abort,
    resolve_unreadable_type_ids_or_abort,
    resolve_object_relation_endpoints,
    resolve_counterpart_summaries,
    log_object_relation_change,
    log_object_relation_update,
    log_object_relation_deletions,
    read_bulk_delete_selection,
    delete_object_relations,
)

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.object_relations_manager import (
    ObjectRelationsManagerInsertError,
    ObjectRelationsManagerGetError,
    ObjectRelationsManagerIterationError,
    ObjectRelationsManagerUpdateError,
    ObjectRelationsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

object_relations_blueprint = APIBlueprint('object_relations', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

def stamp_object_relation_references(data: dict[str, Any], relation: dict[str, Any], request_user: CmdbUser) -> None:
    """
    Judges a CmdbObjectRelation write against its CmdbRelation and stamps what the server owns, in place

    Both endpoints are read (``resolve_object_relation_endpoints``): they must exist, be readable by the caller
    and be of a type the relation allows on their side. Their real type ids replace whatever the body sent, and
    the field values must name the relation's declared fields. Shared by the create and the update, since an
    update replaces both endpoints wholesale

    Args:
        data (dict[str, Any]): The validated write payload, modified in place
        relation (dict[str, Any]): The referenced CmdbRelation, as stored
        request_user (CmdbUser): The user issuing the request

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 when an endpoint or a field value does not fit
        BaseManagerGetError: When reading the endpoints fails
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    parent_type_id, child_type_id = resolve_object_relation_endpoints(
        relation,
        data.get(ObjectRelationKey.RELATION_PARENT_ID.value),
        data.get(ObjectRelationKey.RELATION_CHILD_ID.value),
        objects_manager,
        request_user,
    )
    data[ObjectRelationKey.RELATION_PARENT_TYPE_ID.value] = parent_type_id
    data[ObjectRelationKey.RELATION_CHILD_TYPE_ID.value] = child_type_id

    guard_object_relation_field_values(relation, data.get(ObjectRelationKey.FIELD_VALUES.value))


@object_relations_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.ADD.value)
@object_relations_blueprint.validate(build_write_schema(CmdbObjectRelation.SCHEMA))
@handle_route_errors("while creating the ObjectRelation")
def insert_cmdb_object_relation(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbObjectRelation into the database

    The referenced CmdbRelation must still exist, and the two endpoints must be different CmdbObjects that exist,
    that the caller may read, and whose types the relation allows on their side. Their type ids are stamped from
    the objects, and every field value must name a field the relation declares
    (``stamp_object_relation_references``). `author_id` and `creation_time` are stamped from the request and
    `last_edit_time` is cleared, so none of the three is ever taken from the body

    Args:
        data (CmdbObjectRelation.SCHEMA): Data of the CmdbObjectRelation which should be inserted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 if the referenced CmdbRelation is gone, an endpoint is missing, the same object,
                       unknown or unreadable, of a type the relation does not allow, a field value names an
                       undeclared or repeated field, reading the endpoints fails or the insert fails; 404 if
                       the created CmdbObjectRelation cannot be read back; 500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbObjectRelation and its public_id
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS, request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS, request_user)

        relation: dict[str, Any] = get_existing_relation_or_abort(
            relations_manager, data.get(ObjectRelationKey.RELATION_ID.value),
        )
        stamp_object_relation_references(data, relation, request_user)

        # Stamp server-controlled fields: none of the three is ever trusted from the body. Clearing
        # last_edit_time is what keeps "never edited" a real state - a create is not an edit
        data[ObjectRelationKey.AUTHOR_ID.value] = request_user.get_public_id()
        data[ObjectRelationKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        data[ObjectRelationKey.LAST_EDIT_TIME.value] = None

        result_id: int = object_relations_manager.insert_object_relation(data)

        created_object_relation = object_relations_manager.get_object_relation(result_id)

        if not created_object_relation:
            abort(404, "Could not retrieve the created ObjectRelation from the database!")

        log_object_relation_change(
            object_relation_logs_manager, request_user, LogInteraction.CREATE, None, created_object_relation,
        )

        return InsertSingleResponse(created_object_relation, result_id).make_response()
    except ObjectRelationsManagerInsertError as err:
        abort_if_too_large(err)
        LOGGER.error("[insert_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, "Could not insert the new ObjectRelation in the database!")
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[insert_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ObjectRelation from the database!")
    except BaseManagerGetError as err:
        LOGGER.error("[insert_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@object_relations_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.VIEW.value)
@object_relations_blueprint.parse_collection_parameters()
@handle_route_errors("while iterating the ObjectRelations")
def get_cmdb_object_relations(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbObjectRelations

    A CmdbObjectRelation with an object the caller may not read at either end is left out, ahead of the
    caller's own filter and of the paging, so the total counts the same set as the rows

    Args:
        params (CollectionParameters): Filter for requested CmdbObjectRelations
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 if the types the caller may not read cannot be resolved or the iteration fails,
                       500 on an unexpected error

    Returns:
        GetMultiResponse: All the CmdbObjectRelations matching the CollectionParameters
    """
    try:
        body = request_wants_body()

        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbObjectRelation] = object_relations_manager.iterate(
            builder_params, resolve_unreadable_type_ids_or_abort(request_user),
        )

        object_relation_list = [CmdbObjectRelation.to_json(object_relation) for object_relation
                                in iteration_result.results]

        api_response = GetMultiResponse(object_relation_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ObjectRelationsManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_object_relations] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the ObjectRelations from database!")


@object_relations_blueprint.route('/tabs/<int:object_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.VIEW.value)
@handle_route_errors("while retrieving the ObjectRelation tabs")
def get_cmdb_object_relation_tabs(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for the relation-tab descriptors of a single CmdbObject

    Returns one descriptor per (relation_id, role) group - relation_id, role, role-oriented label /
    icon / color and the instance count - so the frontend can build the relation tabs without
    loading any CmdbObjectRelation instances.

    The tabs are as readable as the object, and a relation whose other object the caller may not read is not
    counted - a group made only of such relations is no tab at all

    Args:
        object_id (int): public_id of the CmdbObject whose relation tabs are requested
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 if the caller may not read the object, 404 if it does not exist, 400 if reading it,
                       resolving the types the caller may not read or the aggregation fails, 500 on an
                       unexpected error

    Returns:
        DefaultResponse: ``{'results': [...]}`` with one entry per relation tab
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        read_tab_object_or_abort(object_id, request_user, objects_manager)

        tabs = object_relations_manager.get_relation_tabs(
            object_id, resolve_unreadable_type_ids_or_abort(request_user),
        )

        return DefaultResponse({TabInstancesKey.RESULTS.value: tabs}).make_response()
    except ObjectRelationsManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_object_relation_tabs] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the ObjectRelation tabs from database!")


@object_relations_blueprint.route('/tabs/<int:object_id>/instances', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.VIEW.value)
@handle_route_errors("while retrieving the ObjectRelation tab instances")
def get_cmdb_object_relation_tab_instances(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route for one page of a relation tab's object relations

    A tab is identified by the ``relation_id`` and ``role`` query parameters (role 'parent' or
    'child'). Returns the paginated instances of that group, each with its own field_values and the
    resolved counterpart (the object on the other side; null when it is missing or inactive).
    ``total`` is the group size and drives the table pagination.

    The tab is as readable as the object, and a relation whose other object is of a type the caller may not
    read is left out of the page and of ``total``. Only ``public_id`` sorts a tab

    Args:
        object_id (int): public_id of the CmdbObject whose relations are listed
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 if the caller may not read the object, 404 if it does not exist, 400 if the tab or
                       the pagination parameters are invalid, or reading the object, resolving the types the
                       caller may not read or the query fails, 500 on an unexpected error

    Returns:
        DefaultResponse: ``{'total': int, 'count': int, 'results': [...]}``
    """
    try:
        relation_id = request.args.get(ObjectRelationTabParam.RELATION_ID.value, type=int)
        role = request.args.get(ObjectRelationTabParam.ROLE.value)

        if relation_id is None or not ObjectRelationRole.is_valid(role):
            abort(400, "A 'relation_id' and a valid 'role' ('parent' or 'child') are required!")

        limit, skip, sort, order = _parse_tab_page_params()

        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        read_tab_object_or_abort(object_id, request_user, objects_manager)

        instances, total = object_relations_manager.get_relation_tab_instances(
            object_id, relation_id, role, limit=limit, skip=skip, sort=sort, order=order,
            denied_type_ids=resolve_unreadable_type_ids_or_abort(request_user),
        )

        results = _build_tab_instance_rows(instances, role, request_user, objects_manager)

        return DefaultResponse({
            TabInstancesKey.TOTAL.value: total,
            TabInstancesKey.COUNT.value: len(results),
            TabInstancesKey.RESULTS.value: results,
        }).make_response()
    except ObjectRelationsManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_object_relation_tab_instances] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the ObjectRelation tab instances from database!")


@object_relations_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.VIEW.value)
@handle_route_errors("while retrieving the ObjectRelation with ID:{public_id}")
def get_cmdb_object_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbObjectRelation

    Refused with a 403 when the caller may not read the object at either end

    Args:
        public_id (int): public_id of the CmdbObjectRelation
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no such CmdbObjectRelation exists, 403 if the caller may not read one of its
                       objects, 400 if the read or resolving the types the caller may not read fails,
                       500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbObjectRelation
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)

        requested_object_relation = object_relations_manager.get_object_relation(public_id)

        if requested_object_relation:
            if not is_object_relation_readable(requested_object_relation,
                                               resolve_unreadable_type_ids_or_abort(request_user)):
                abort(403, OBJECT_RELATION_ACCESS_DENIED_MESSAGE.format(public_id=public_id))

            api_response = GetSingleResponse(requested_object_relation, body=request_wants_body())

            return api_response.make_response()

        abort(404, f"The ObjectRelation with ID:{public_id} was not found!")
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the requested ObjectRelation with ID:{public_id} from the database!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@object_relations_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.EDIT.value)
@object_relations_blueprint.validate(build_write_schema(CmdbObjectRelation.SCHEMA))
@handle_route_errors("while updating ObjectRelation with ID:{public_id}")
def update_cmdb_object_relation(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbObjectRelation

    The whole document is replaced, so the update passes the same rules as a create: the referenced
    CmdbRelation must still exist, both endpoints are read and judged and their type ids stamped, and the
    field values must name the relation's declared fields (``stamp_object_relation_references``). The stored
    creation time survives; the editing user becomes `author_id` and `last_edit_time` is stamped.
    The response is the document as it was stored, not the submitted body

    Args:
        public_id (int): public_id of the CmdbObjectRelation which should be updated
        data (CmdbObjectRelation.SCHEMA): New CmdbObjectRelation data
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no such CmdbObjectRelation exists, 400 if the referenced CmdbRelation is
                       gone, an endpoint or a field value does not fit it (as on create), reading the endpoints
                       fails, the data is unusable or the write fails, 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The stored data of the CmdbObjectRelation
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS, request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(
            ManagerType.RELATIONS, request_user)

        relation: dict[str, Any] = get_existing_relation_or_abort(
            relations_manager, data.get(ObjectRelationKey.RELATION_ID.value),
        )
        # An update replaces both endpoints wholesale, so it has to be as sound as a create
        stamp_object_relation_references(data, relation, request_user)

        to_update_object_relation = object_relations_manager.get_object_relation(public_id)

        if not to_update_object_relation:
            abort(404, f"The ObjectRelation with ID: {public_id} was not found!")

        # The creation time describes how this relation came to exist and is preserved; `author_id`
        # doubles as "who last touched this" (there is no separate editor field), so it becomes the
        # editing user. Without pinning creation_time, a body that omits it would reset it to "now"
        pin_public_id(data, public_id)
        data[ObjectRelationKey.CREATION_TIME.value] = to_update_object_relation.get(
            ObjectRelationKey.CREATION_TIME.value)
        data[ObjectRelationKey.AUTHOR_ID.value] = request_user.get_public_id()
        data[ObjectRelationKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        try:
            updated_object_relation = CmdbObjectRelation.to_json(CmdbObjectRelation.from_data(data))
        except Exception as err:
            LOGGER.error("[update_cmdb_object_relation] Unusable ObjectRelation data: %s", err, exc_info=True)
            abort(400, f"The data of the ObjectRelation with ID:{public_id} is not usable!")

        object_relations_manager.update_object_relation(public_id, updated_object_relation)

        # Logged only once the write went through, so the history can never claim a change that failed
        log_object_relation_update(
            object_relation_logs_manager, request_user, to_update_object_relation, updated_object_relation,
        )

        return UpdateSingleResponse(result=updated_object_relation).make_response()
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[update_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectRelation with ID:{public_id} which should be updated!")
    except ObjectRelationsManagerUpdateError as err:
        abort_if_too_large(err)
        LOGGER.error("[update_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to update the ObjectRelation with ID:{public_id}!")
    except BaseManagerGetError as err:
        LOGGER.error("[update_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, OBJECT_RELATION_ENDPOINT_LOOKUP_FAILED_MESSAGE)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@object_relations_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.DELETE.value)
@handle_route_errors("while deleting the ObjectRelation with ID:{public_id}")
def delete_cmdb_object_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbObjectRelation

    The relation is read first (its history entry and the response need the document), and the delete has
    to remove it: when another request deleted it in between, this one answers 404 and logs nothing, so a
    deletion is recorded once, by the request that performed it

    Args:
        public_id (int): public_id of the CmdbObjectRelation which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no such CmdbObjectRelation exists (or it was deleted concurrently), 400 if the
                       read or the delete fails, 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbObjectRelation data
    """
    not_found_message: str = f"The ObjectRelation with ID: {public_id} was not found!"

    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS, request_user)

        to_delete_object_relation = object_relations_manager.get_object_relation(public_id)

        if not to_delete_object_relation:
            abort(404, not_found_message)

        if not object_relations_manager.delete_object_relation(public_id):
            abort(404, not_found_message)

        log_object_relation_change(
            object_relation_logs_manager, request_user, LogInteraction.DELETE, to_delete_object_relation, None,
        )

        return DeleteSingleResponse(to_delete_object_relation).make_response()
    except ObjectRelationsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Could not delete the ObjectRelation with ID:{public_id}!")
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[delete_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectRelation with ID:{public_id} from the database!")


@object_relations_blueprint.route('/delete/many', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.DELETE.value)
@handle_route_errors("while deleting the ObjectRelations")
def delete_many_object_relations(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to delete multiple CmdbObjectRelations at once

    The body is ``{'target_ids': [<public_id>, ...]}`` - numbers or digit strings, at most
    MAX_BULK_DELETE_OBJECT_RELATIONS distinct ids (see ``read_bulk_delete_selection``). Every id is deleted by
    its own atomic read-and-delete (``delete_object_relations``), and one DELETE log is written per document
    that call removed: a relation another request deleted in the meantime is neither deleted nor logged here.
    public_ids that match nothing are ignored; only a selection of which nothing was deleted is reported.

    A delete that fails part-way answers 400 naming how many were deleted before it; those are logged too

    Args:
        request_user (CmdbUser): CmdbUser which is using this route

    Raises:
        HTTPException: 400 if the body is no object, no usable public_ids were provided, too many were, none
                       of them was deleted, or a delete fails; 500 on an unexpected error

    Returns:
        DefaultResponse: True when the matched CmdbObjectRelations were deleted
    """
    deleted: list[dict[str, Any]] = []

    try:
        selection: list[int] = read_bulk_delete_selection(request.get_json())

        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS, request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS, request_user)

        try:
            delete_object_relations(object_relations_manager, selection, deleted)
        finally:
            # Also after a failure part-way: what was deleted before it is history all the same
            log_object_relation_deletions(object_relation_logs_manager, request_user, deleted)

        if not deleted:
            abort(400, OBJECT_RELATION_BULK_NONE_EXIST_MESSAGE)

        return DefaultResponse(True).make_response()
    except BaseManagerDeleteError as err:
        LOGGER.error("[delete_many_object_relations] %s", err, exc_info=True)
        abort(400, OBJECT_RELATION_BULK_DELETE_FAILED_MESSAGE.format(deleted=len(deleted)))

# -------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------ #

def _read_int_arg(name: str, default: int) -> int:
    """
    Reads one whole-number query parameter, refusing a value that is not a number

    Flask's own typed lookup falls back to the default when the value does not convert, which would
    silently turn `?order=desc` into ascending - a wrong result rather than a reported mistake. An
    absent or empty parameter still means "use the default"

    Args:
        name (str): Name of the query parameter to read
        default (int): Value to use when the parameter is absent or empty

    Raises:
        HTTPException: 400 if the parameter is present but not a whole number

    Returns:
        int: The parameter value, or the default
    """
    raw_value = request.args.get(name)

    if raw_value is None or raw_value == '':
        return default

    try:
        return int(raw_value)
    except ValueError:
        abort(400, f"'{name}' must be a whole number!")


def _parse_tab_page_params() -> tuple[int, int, str, int]:
    """
    Reads and validates the pagination parameters of the relation-tab instances route

    Every parameter is optional. An out-of-range `limit`, a `sort` key outside TAB_SORT_KEYS or an
    `order` that is not a MongoDB sort direction is refused instead of being clamped: `limit=0` would
    mean "no limit" and could dump a whole tab in one response, any other sort key leaves the tab's
    index and sorts the whole group in memory, and an unknown direction would otherwise silently sort
    ascending

    Raises:
        HTTPException: 400 if a parameter is not a whole number, `limit` is outside
                       1..MAX_TAB_PAGE_SIZE, `page` is below 1, `sort` is not in TAB_SORT_KEYS or
                       `order` is not 1 / -1

    Returns:
        tuple[int, int, str, int]: The page size, the number of documents to skip, the sort field and
                                   the sort direction
    """
    limit = _read_int_arg(ObjectRelationTabParam.LIMIT.value, DEFAULT_TAB_PAGE_SIZE)
    page = _read_int_arg(ObjectRelationTabParam.PAGE.value, 1)
    sort = request.args.get(ObjectRelationTabParam.SORT.value) or ObjectRelationKey.PUBLIC_ID.value
    order = _read_int_arg(ObjectRelationTabParam.ORDER.value, 1)

    if limit < 1 or limit > MAX_TAB_PAGE_SIZE:
        abort(400, f"'limit' must be between 1 and {MAX_TAB_PAGE_SIZE}!")

    if page < 1:
        abort(400, "'page' must be 1 or higher!")

    if sort not in TAB_SORT_KEYS:
        abort(400, TAB_SORT_KEY_INVALID_MESSAGE.format(allowed=', '.join(TAB_SORT_KEYS)))

    if order not in SORT_DIRECTIONS:
        abort(400, "'order' must be 1 (ascending) or -1 (descending)!")

    return limit, (page - 1) * limit, sort, order


def _build_tab_instance_rows(
    instances: list[dict[str, Any]],
    role: str,
    request_user: CmdbUser,
    objects_manager: ObjectsManager,
) -> list[dict[str, Any]]:
    """
    Projects a page of CmdbObjectRelations into relation-tab rows with their counterpart resolved

    The counterpart is the object on the other side of the relation, so the side to resolve is the
    opposite of the tab's role. All counterparts of the page are rendered in one ACL-scoped batch;
    a row whose counterpart is missing or inactive carries `None`. A counterpart the caller may not read
    never reaches this point - the manager leaves its relation out of the page

    Args:
        instances (list[dict[str, Any]]): The page's CmdbObjectRelation documents
        role (str): The role the tab's own object plays ('parent' or 'child')
        request_user (CmdbUser): The user requesting the page (for ACL-scoped rendering)
        objects_manager (ObjectsManager): Manager used to read the counterpart objects

    Returns:
        list[dict[str, Any]]: One row per instance, in the order the instances were given
    """
    counterpart_field = (ObjectRelationKey.RELATION_CHILD_ID.value if role == ObjectRelationRole.PARENT
                         else ObjectRelationKey.RELATION_PARENT_ID.value)

    counterparts = resolve_counterpart_summaries(
        [instance.get(counterpart_field) for instance in instances], request_user, objects_manager)

    return [
        {
            ObjectRelationKey.PUBLIC_ID.value: instance.get(ObjectRelationKey.PUBLIC_ID.value),
            ObjectRelationKey.RELATION_ID.value: instance.get(ObjectRelationKey.RELATION_ID.value),
            ObjectRelationKey.FIELD_VALUES.value: instance.get(ObjectRelationKey.FIELD_VALUES.value, []),
            TabInstancesKey.COUNTERPART.value: counterparts.get(instance.get(counterpart_field)),
        }
        for instance in instances
    ]
