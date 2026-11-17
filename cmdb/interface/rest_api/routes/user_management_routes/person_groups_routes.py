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
The ``/person_groups`` routes - a layer over the objects of the Types carrying PERSON_GROUP

A person group is an object (``person_records_helper``); these routes keep the old request and response shape: a record
``{public_id, name, email, group_members}``, ``public_id`` the object id, ``group_members`` its members (persons;
the object write judges them like any person selection). Every route asks the object right of its operation and the
Type's ACL - the person group rights are gone. ADMIN level, no licence gate
"""
from http import HTTPStatus
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.class_schema.person_group_model.cmdb_person_group_schema import get_cmdb_person_group_schema
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    InsertSingleResponse,
    UpdateSingleResponse,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.user_management_routes.person_records_helper import (
    create_record,
    delete_record,
    list_records,
    read_record,
    update_record,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    PERSON_GROUP_LABEL,
    RECORD_ACCESS_DENIED_MESSAGE,
    RECORD_CREATE_FAILED_MESSAGE,
    RECORD_DELETE_FAILED_MESSAGE,
    RECORD_READ_FAILED_MESSAGE,
    RECORD_UPDATE_FAILED_MESSAGE,
)
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerDeleteError,
    ObjectsManagerGetError,
    ObjectsManagerInsertError,
    ObjectsManagerUpdateError,
)
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

MARKER: SpecialType = SpecialType.PERSON_GROUP
PERSON_GROUP_WRITE_SCHEMA: dict[str, Any] = build_write_schema(get_cmdb_person_group_schema())

person_group_blueprint = APIBlueprint('person_group', __name__)

# The manager failures of every route, by what was going on
_READ_FAILURES: dict[type[Exception], str] = {
    ObjectsManagerGetError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_GROUP_LABEL),
    BaseManagerIterationError: RECORD_READ_FAILED_MESSAGE.format(label=PERSON_GROUP_LABEL),
}
_CREATE_FAILURES: dict[type[Exception], str] = {
    **_READ_FAILURES,
    ObjectsManagerInsertError: RECORD_CREATE_FAILED_MESSAGE.format(label=PERSON_GROUP_LABEL),
    ObjectsManagerUpdateError: RECORD_CREATE_FAILED_MESSAGE.format(label=PERSON_GROUP_LABEL),
}
_ACCESS_DENIED: str = RECORD_ACCESS_DENIED_MESSAGE.format(label=PERSON_GROUP_LABEL)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@person_group_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right=ObjectRightName.ADD.value)
@person_group_blueprint.validate(PERSON_GROUP_WRITE_SCHEMA)
@handle_route_errors("while creating the PersonGroup")
@handle_manager_errors(_CREATE_FAILURES)
def insert_cmdb_person_group(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route creating a person group - an object of the default PERSON_GROUP Type

    Args:
        data (dict[str, Any]): The person group record
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: what the object create answers (400 for a broken rule or a member that is no person, 403 for
            the Type's ACL or a member the writer may not read), 400 without a default Type

    Returns:
        InsertSingleResponse: The new person group record and its public_id
    """
    try:
        public_id: int = create_record(MARKER, data, request_user)

        return InsertSingleResponse(read_record(MARKER, public_id, request_user), public_id).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@person_group_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@person_group_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving PersonGroups")
@handle_manager_errors(_READ_FAILURES)
def get_cmdb_person_groups(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route listing the person groups of every PERSON_GROUP Type the caller may READ

    The filter and the sort run on the record keys

    Args:
        params (CollectionParameters): Filter, sort and page
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when the person groups could not be read, 503 when the read ran past its time budget

    Returns:
        GetMultiResponse: The person group records of the page and their total
    """
    records, total = list_records(MARKER, params, request_user)

    return GetMultiResponse(records, total, params, request.url, request_wants_body()).make_response()


@person_group_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right=ObjectRightName.VIEW.value)
@handle_route_errors("while retrieving the PersonGroup with ID: {public_id}")
@handle_manager_errors(_READ_FAILURES)
def get_cmdb_person_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route reading one person group

    Args:
        public_id (int): The person group's object id
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 for an id naming no person group, 403 for one of a Type the caller may not READ

    Returns:
        GetSingleResponse: The person group record
    """
    try:
        return GetSingleResponse(read_record(MARKER, public_id, request_user),
                                 body=request_wants_body()).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@person_group_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right=ObjectRightName.EDIT.value)
@person_group_blueprint.validate(PERSON_GROUP_WRITE_SCHEMA)
@handle_route_errors("while updating the PersonGroup with ID: {public_id}")
@handle_manager_errors({**_READ_FAILURES, ObjectsManagerUpdateError: RECORD_UPDATE_FAILED_MESSAGE.format(
    label=PERSON_GROUP_LABEL, public_id='{public_id}')})
def update_cmdb_person_group(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route updating a person group - the keys the body carries, `group_members` its members

    Args:
        public_id (int): The person group's object id
        data (dict[str, Any]): The person group record
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 / 403 as the read; what the object update answers - a member that is no person 400, one
            the writer may not read 403

    Returns:
        UpdateSingleResponse: The stored person group record
    """
    try:
        update_record(MARKER, public_id, data, request_user)

        return UpdateSingleResponse(read_record(MARKER, public_id, request_user)).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@person_group_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@person_group_blueprint.protect(auth=True, right=ObjectRightName.DELETE.value)
@handle_route_errors("while deleting the PersonGroup with ID: {public_id}")
@handle_manager_errors({**_READ_FAILURES, ObjectsManagerDeleteError: RECORD_DELETE_FAILED_MESSAGE.format(
    label=PERSON_GROUP_LABEL, public_id='{public_id}')})
def delete_cmdb_person_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route deleting a person group - the object delete, with its guards and clean-up

    The group leaves every ISMS document; the delete is refused while it owns a risk assessment or is the only
    selection of a required person selector

    Args:
        public_id (int): The person group's object id
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 / 403 as the read; what the object delete answers

    Returns:
        DeleteSingleResponse: The deleted person group record
    """
    try:
        return DeleteSingleResponse(delete_record(MARKER, public_id, request_user)).make_response()
    except AccessDeniedError:
        abort(HTTPStatus.FORBIDDEN, _ACCESS_DENIED)
